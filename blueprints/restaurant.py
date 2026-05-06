"""Restaurant routes: profile, dashboard, orders CRUD, AI insights."""
import secrets
from datetime import datetime

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user

from models import db, User, Order, DeliveryLog, SavedCustomer
from extensions import socketio, init_socketio_service
from common.decorators import role_required
from common.utils import utcnow
from common.background import auto_transition_order_statuses, enhance_in_background
from common.logging_config import get_logger

logger = get_logger(__name__)


def register(app):
    @app.route('/restaurant/profile', methods=['GET', 'POST'])
    @role_required('restaurant')
    def restaurant_profile():
        if request.method == 'POST':
            current_user.full_name = request.form.get('full_name')
            current_user.email = request.form.get('email')
            current_user.current_location = request.form.get('current_location')

            plat = request.form.get('pickup_latitude')
            plon = request.form.get('pickup_longitude')
            if plat and plon:
                try:
                    current_user.last_known_latitude = float(plat)
                    current_user.last_known_longitude = float(plon)
                except ValueError:
                    flash('Invalid GPS coordinates.', 'error')
                    return render_template('restaurant/profile.html')
            else:
                flash('⚠️ Please select your restaurant pickup location on the map!', 'error')
                return render_template('restaurant/profile.html')

            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('restaurant_dashboard'))
        return render_template('restaurant/profile.html')

    @app.route('/restaurant/statistics')
    @role_required('restaurant')
    def restaurant_statistics():
        from services.ai_statistics import calculate_restaurant_stats
        stats = calculate_restaurant_stats(current_user.id)
        return render_template('restaurant/statistics.html', stats=stats)

    @app.route('/api/restaurant/ai-insights')
    @role_required('restaurant')
    def api_restaurant_ai_insights():
        from models import AIStatisticsSummary
        cached = AIStatisticsSummary.query.filter_by(
            user_id=current_user.id, summary_type='restaurant_weekly'
        ).first()
        if cached:
            return jsonify({
                'status': 'ready', 'summary': cached.summary_text,
                'generated_at': cached.generated_at.isoformat(), 'is_cached': True,
            })
        return jsonify({'status': 'loading', 'message': 'AI insights are being generated in the background...'})

    @app.route('/restaurant/dashboard')
    @role_required('restaurant')
    def restaurant_dashboard():
        auto_transition_order_statuses()

        active_orders_list = Order.query.filter_by(restaurant_id=current_user.id).filter(
            Order.status.in_(['pending', 'assigned', 'picked_up', 'in_transit'])
        ).order_by(Order.created_at.desc()).all()

        all_orders = Order.query.filter_by(restaurant_id=current_user.id).all()
        total_orders = len(all_orders)
        pending_orders = sum(1 for o in all_orders if o.status == 'pending')
        active_orders = sum(1 for o in all_orders if o.status in ['assigned', 'picked_up', 'in_transit'])
        completed_orders = sum(1 for o in all_orders if o.status == 'delivered')

        available_couriers = User.query.filter_by(role='courier', is_available=True, is_active=True).count()

        return render_template('restaurant/dashboard.html',
                               orders=active_orders_list, total_orders=total_orders,
                               pending_orders=pending_orders, active_orders=active_orders,
                               completed_orders=completed_orders, available_couriers=available_couriers)

    @app.route('/restaurant/order/create', methods=['GET', 'POST'])
    @role_required('restaurant')
    def restaurant_create_order():
        if request.method == 'POST':
            from services.assignment_algorithm import default_assignment_service

            customer_name = request.form.get('customer_name')
            customer_phone = request.form.get('customer_phone')
            delivery_address = request.form.get('delivery_address')
            save_customer = request.form.get('save_customer') == 'on'

            if save_customer:
                existing = SavedCustomer.query.filter_by(
                    restaurant_id=current_user.id, customer_phone=customer_phone
                ).first()
                if not existing:
                    db.session.add(SavedCustomer(
                        restaurant_id=current_user.id,
                        customer_name=customer_name, customer_phone=customer_phone,
                        delivery_address=delivery_address, last_used_at=utcnow(),
                    ))
                else:
                    existing.last_used_at = utcnow()

            pickup_address = request.form.get('pickup_address')
            pickup_lat_str = request.form.get('pickup_latitude')
            pickup_lon_str = request.form.get('pickup_longitude')
            delivery_lat_str = request.form.get('delivery_latitude')
            delivery_lon_str = request.form.get('delivery_longitude')

            def _saved():
                return SavedCustomer.query.filter_by(restaurant_id=current_user.id).order_by(
                    SavedCustomer.last_used_at.desc()
                ).all()

            if not delivery_lat_str or not delivery_lon_str:
                flash('⚠️ Please select a delivery location on the map!', 'error')
                return render_template('restaurant/create_order.html', saved_customers=_saved())
            if not pickup_lat_str or not pickup_lon_str:
                flash('⚠️ Pickup location is missing. Please contact administrator.', 'error')
                return render_template('restaurant/create_order.html', saved_customers=_saved())
            try:
                pickup_lat = float(pickup_lat_str)
                pickup_lon = float(pickup_lon_str)
                delivery_lat = float(delivery_lat_str)
                delivery_lon = float(delivery_lon_str)
            except ValueError:
                flash('⚠️ Invalid GPS coordinates. Please select locations on the map.', 'error')
                return render_template('restaurant/create_order.html', saved_customers=_saved())

            order_number = f"ORD-{utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
            items_description = request.form.get('items_description')

            order = Order(
                order_number=order_number, restaurant_id=current_user.id,
                restaurant_name=current_user.full_name,
                customer_name=customer_name, customer_phone=customer_phone,
                delivery_address=delivery_address, pickup_address=pickup_address,
                items_description=items_description, ai_enhanced_description=None,
                special_instructions=request.form.get('special_instructions'),
                order_value=float(request.form.get('order_value') or 0),
                status='pending',
                pickup_latitude=pickup_lat, pickup_longitude=pickup_lon,
                delivery_latitude=delivery_lat, delivery_longitude=delivery_lon,
            )

            db.session.add(order)
            db.session.flush()

            db.session.add(DeliveryLog(
                order_id=order.id, event_type='order_created',
                event_description=f'Order created by {current_user.full_name}',
                new_status='pending', user_id=current_user.id, user_role='restaurant',
                timestamp=utcnow(),
            ))
            db.session.commit()

            svc = init_socketio_service()
            svc.emit_order_created(order)

            if items_description and items_description.strip():
                socketio.start_background_task(enhance_in_background, current_app._get_current_object(), order.id, items_description)

            success, message, courier = default_assignment_service.auto_assign_order(order)
            if success:
                svc.emit_order_assigned(order)
                msg = f'Order {order.order_number} created and assigned to {courier.full_name}!'
                if order.estimated_total_time:
                    msg += f' Estimated delivery: {order.estimated_total_time} minutes'
                    if order.estimated_pickup_time:
                        msg += f' (pickup in ~{order.estimated_pickup_time} min, delivery in ~{order.estimated_delivery_time} min)'
                flash(msg, 'success')
            else:
                flash(f'Order {order.order_number} created. {message}', 'warning')

            return redirect(url_for('restaurant_dashboard'))

        saved_customers = SavedCustomer.query.filter_by(restaurant_id=current_user.id).order_by(
            SavedCustomer.last_used_at.desc()
        ).all()
        return render_template('restaurant/create_order.html', saved_customers=saved_customers)

    @app.route('/restaurant/orders/history')
    @role_required('restaurant')
    def restaurant_order_history():
        page = request.args.get('page', 1, type=int)
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '').strip()
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        query = Order.query.filter_by(restaurant_id=current_user.id)
        if status_filter != 'all':
            query = query.filter_by(status=status_filter)
        if search_query:
            pattern = f'%{search_query}%'
            query = query.filter(db.or_(
                Order.order_number.ilike(pattern),
                Order.customer_name.ilike(pattern),
                Order.customer_phone.ilike(pattern),
            ))
        if date_from:
            try:
                query = query.filter(Order.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
            except ValueError:
                pass
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                query = query.filter(Order.created_at <= to_date)
            except ValueError:
                pass

        pagination = query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
        return render_template('restaurant/order_history.html',
                               orders=pagination.items, pagination=pagination,
                               status_filter=status_filter, search_query=search_query,
                               date_from=date_from, date_to=date_to)

    @app.route('/restaurant/order/<int:order_id>')
    @role_required('restaurant')
    def restaurant_view_order(order_id):
        auto_transition_order_statuses()
        order = Order.query.get_or_404(order_id)
        if order.restaurant_id != current_user.id:
            flash('You do not have permission to view this order.', 'danger')
            return redirect(url_for('restaurant_dashboard'))

        logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

        if not order.ai_enhanced_description and order.items_description:
            socketio.start_background_task(enhance_in_background, current_app._get_current_object(), order.id, order.items_description)
            logger.info(f"Started background generation for order {order.order_number}")

        return render_template('restaurant/view_order.html', order=order, logs=logs)

    @app.route('/restaurant/order/<int:order_id>/edit', methods=['GET', 'POST'])
    @role_required('restaurant')
    def restaurant_edit_order(order_id):
        order = Order.query.get_or_404(order_id)
        if order.restaurant_id != current_user.id:
            flash('You do not have permission to edit this order.', 'danger')
            return redirect(url_for('restaurant_dashboard'))
        if order.status not in ['pending', 'assigned']:
            flash('Cannot edit order after it has been picked up.', 'danger')
            return redirect(url_for('restaurant_view_order', order_id=order.id))

        if request.method == 'POST':
            order.customer_name = request.form.get('customer_name')
            order.customer_phone = request.form.get('customer_phone')
            order.delivery_address = request.form.get('delivery_address')
            order.pickup_address = request.form.get('pickup_address')
            order.items_description = request.form.get('items_description')
            order.special_instructions = request.form.get('special_instructions')
            order.order_value = float(request.form.get('order_value') or 0)

            db.session.add(DeliveryLog(
                order_id=order.id, event_type='order_edited',
                event_description=f'Order details updated by {current_user.full_name}',
                user_id=current_user.id, user_role='restaurant',
            ))
            db.session.commit()
            flash('Order updated successfully!', 'success')
            return redirect(url_for('restaurant_view_order', order_id=order.id))
        return render_template('restaurant/edit_order.html', order=order)

    @app.route('/restaurant/order/<int:order_id>/cancel', methods=['POST'])
    @role_required('restaurant')
    def restaurant_cancel_order(order_id):
        order = Order.query.get_or_404(order_id)
        if order.restaurant_id != current_user.id:
            flash('You do not have permission to cancel this order.', 'danger')
            return redirect(url_for('restaurant_dashboard'))
        if order.status not in ['pending', 'assigned']:
            flash('Cannot cancel order after it has been picked up.', 'danger')
            return redirect(url_for('restaurant_view_order', order_id=order.id))

        cancel_reason = request.form.get('cancel_reason', 'No reason provided')
        old_status = order.status
        order.status = 'cancelled'

        if order.courier_id and order.status == 'assigned':
            courier = db.session.get(User, order.courier_id)
            if courier:
                courier.is_available = True

        db.session.add(DeliveryLog(
            order_id=order.id, event_type='order_cancelled',
            event_description=f'Order cancelled by {current_user.full_name}. Reason: {cancel_reason}',
            old_status=old_status, new_status='cancelled',
            user_id=current_user.id, user_role='restaurant',
        ))
        db.session.commit()
        init_socketio_service().emit_order_cancelled(order)

        flash(f'Order {order.order_number} has been cancelled.', 'success')
        return redirect(url_for('restaurant_dashboard'))

    @app.route('/restaurant/order/<int:order_id>/update-status', methods=['POST'])
    @role_required('restaurant')
    def restaurant_update_order_status(order_id):
        order = Order.query.get_or_404(order_id)
        if order.restaurant_id != current_user.id:
            flash('You do not have permission to update this order.', 'danger')
            return redirect(url_for('restaurant_dashboard'))

        new_status = request.form.get('status')
        old_status = order.status
        order.status = new_status

        if new_status == 'picked_up' and not order.picked_up_at:
            order.picked_up_at = utcnow()
        elif new_status == 'in_transit' and not order.in_transit_at:
            order.in_transit_at = utcnow()

        db.session.add(DeliveryLog(
            order_id=order.id, event_type='status_change',
            event_description=f'Status changed from {old_status} to {new_status} by {current_user.full_name}',
            old_status=old_status, new_status=new_status,
            user_id=current_user.id, user_role='restaurant',
        ))
        db.session.commit()
        init_socketio_service().emit_order_status_changed(order, old_status, new_status)

        flash(f'Order status updated to {new_status}.', 'success')
        return redirect(url_for('restaurant_view_order', order_id=order.id))
