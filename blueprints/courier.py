"""Courier routes: dashboard, availability, orders, profile, statistics."""
import json
import os
import secrets
from datetime import datetime

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user
from werkzeug.utils import secure_filename
from PIL import Image

from models import db, User, Order, DeliveryLog
from extensions import socketio, init_socketio_service, limiter
from common.decorators import role_required
from common.utils import utcnow, allowed_file
from common.background import (
    auto_transition_order_statuses,
    enhance_in_background,
    transition_to_in_transit_background,
    analyze_delivery_photo_background,
)
from common.logging_config import get_logger

logger = get_logger(__name__)


def register(app):
    @app.route('/courier/dashboard')
    @role_required('courier')
    def courier_dashboard():
        auto_transition_order_statuses()

        active_orders = Order.query.filter_by(courier_id=current_user.id).filter(
            Order.status.in_(['assigned', 'picked_up', 'in_transit'])
        ).order_by(Order.created_at.desc()).all()

        all_orders = Order.query.filter_by(courier_id=current_user.id).all()
        completed_today = [o for o in all_orders if o.status == 'delivered'
                           and o.delivered_at and o.delivered_at.date() == utcnow().date()]

        active_orders_json = json.dumps([{
            'id': o.id, 'order_number': o.order_number,
            'restaurant_name': o.restaurant_name, 'customer_name': o.customer_name,
            'pickup_address': o.pickup_address, 'delivery_address': o.delivery_address,
            'pickup_latitude': o.pickup_latitude, 'pickup_longitude': o.pickup_longitude,
            'delivery_latitude': o.delivery_latitude, 'delivery_longitude': o.delivery_longitude,
            'status': o.status,
        } for o in active_orders])

        return render_template('courier/dashboard.html',
                               active_orders=active_orders,
                               completed_orders=completed_today,
                               is_available=current_user.is_available,
                               active_orders_json=active_orders_json)

    @app.route('/courier/toggle-availability')
    @role_required('courier')
    def courier_toggle_availability():
        active_orders = Order.query.filter_by(courier_id=current_user.id).filter(
            Order.status.in_(['assigned', 'picked_up', 'in_transit'])
        ).count()

        svc = init_socketio_service()
        if active_orders > 0 and current_user.is_available:
            current_user.pending_unavailable = True
            current_user.is_available = False
            db.session.commit()
            svc.emit_courier_availability(current_user)
            flash(f'You have {active_orders} active order(s). You are now unavailable for new orders '
                  f'and will remain unavailable after completing all deliveries.', 'info')
            return redirect(url_for('courier_dashboard'))

        current_user.is_available = not current_user.is_available
        current_user.pending_unavailable = False
        db.session.commit()
        svc.emit_courier_availability(current_user)

        status = 'available' if current_user.is_available else 'unavailable'
        flash(f'You are now {status} for new orders.', 'success')
        return redirect(url_for('courier_dashboard'))

    @app.route('/courier/update-location', methods=['GET', 'POST'])
    @role_required('courier')
    def courier_update_location():
        if request.method == 'POST':
            latitude = float(request.form.get('latitude'))
            longitude = float(request.form.get('longitude'))
            current_user.last_known_latitude = latitude
            current_user.last_known_longitude = longitude
            db.session.commit()
            init_socketio_service().emit_courier_location(current_user)
            flash('Your location has been updated successfully!', 'success')
            return redirect(url_for('courier_dashboard'))
        return render_template('courier/update_location.html')

    @app.route('/courier/profile', methods=['GET', 'POST'])
    @role_required('courier')
    def courier_profile():
        if request.method == 'POST':
            current_user.full_name = request.form.get('full_name')
            current_user.email = request.form.get('email')
            current_user.vehicle_type = request.form.get('vehicle_type')
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('courier_dashboard'))
        return render_template('courier/profile.html')

    @app.route('/courier/statistics')
    @role_required('courier')
    def courier_statistics():
        from services.ai_statistics import calculate_courier_stats
        stats = calculate_courier_stats(current_user.id)
        return render_template('courier/statistics.html', stats=stats)

    @app.route('/api/courier/ai-insights')
    @role_required('courier')
    @limiter.limit("10 per minute")
    def api_courier_ai_insights():
        from models import AIStatisticsSummary
        cached = AIStatisticsSummary.query.filter_by(
            user_id=current_user.id, summary_type='courier_daily'
        ).first()
        if cached:
            return jsonify({
                'status': 'ready', 'summary': cached.summary_text,
                'generated_at': cached.generated_at.isoformat(), 'is_cached': True,
            })
        return jsonify({'status': 'loading', 'message': 'AI insights are being generated in the background...'})

    @app.route('/courier/order/<int:order_id>/reject', methods=['POST'])
    @role_required('courier')
    def courier_reject_order(order_id):
        order = Order.query.get_or_404(order_id)
        if order.courier_id != current_user.id:
            flash('You can only reject orders assigned to you.', 'error')
            return redirect(url_for('courier_dashboard'))
        if order.status not in ['assigned']:
            flash("You can only reject orders that haven't been picked up yet.", 'error')
            return redirect(url_for('courier_view_order', order_id=order.id))

        current_user.rejected_orders = (current_user.rejected_orders or 0) + 1
        current_user.total_deliveries = (current_user.total_deliveries or 0) + 1

        if not order.rejected_by_couriers:
            order.rejected_by_couriers = []
        order.rejected_by_couriers.append({
            'courier_id': current_user.id, 'rejected_at': utcnow().isoformat(),
        })

        db.session.add(DeliveryLog(
            order_id=order.id, event_type='order_rejected',
            event_description=f'Order rejected by {current_user.full_name}',
            old_status='assigned', new_status='pending',
            user_id=current_user.id, user_role='courier', timestamp=utcnow(),
        ))

        old_courier = order.courier_id
        order.courier_id = None
        order.status = 'pending'
        order.assigned_at = None
        order.estimated_pickup_time = None
        order.estimated_delivery_time = None
        order.estimated_total_time = None
        db.session.commit()

        svc = init_socketio_service()
        svc.emit_order_rejected(order, current_user.id, current_user.full_name)
        flash('Order rejected. It will be reassigned to another courier.', 'info')

        from services.assignment_algorithm import default_assignment_service
        success, message, new_courier = default_assignment_service.auto_assign_order(
            order, exclude_courier_id=old_courier
        )
        if success:
            svc.emit_order_assigned(order)
            flash(f'Order automatically reassigned to {new_courier.full_name}.', 'success')
        else:
            flash(f'Warning: {message}', 'warning')
        return redirect(url_for('courier_dashboard'))

    @app.route('/courier/order/<int:order_id>/update', methods=['POST'])
    @role_required('courier')
    def courier_update_order_status(order_id):
        try:
            order = Order.query.get_or_404(order_id)
            if order.courier_id != current_user.id:
                flash('You do not have permission to update this order.', 'danger')
                return redirect(url_for('courier_dashboard'))

            new_status = request.form.get('status')
            old_status = order.status

            if 'delivery_proof' in request.files:
                file = request.files['delivery_proof']
                if file and file.filename and allowed_file(file.filename):
                    # Validate image content with Pillow
                    try:
                        img = Image.open(file)
                        img.verify()
                        if img.format not in ('JPEG', 'PNG', 'WEBP'):
                            flash('Delivery proof must be JPEG, PNG, or WEBP format.', 'danger')
                            return redirect(url_for('courier_view_order', order_id=order.id))
                        file.seek(0)  # Reset stream after verify
                    except Exception:
                        flash('Invalid image file or corrupted delivery proof.', 'danger')
                        return redirect(url_for('courier_view_order', order_id=order.id))

                    filename = secure_filename(
                        f"{order.order_number}_{secrets.token_hex(4)}.{file.filename.rsplit('.', 1)[1].lower()}"
                    )
                    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    order.delivery_proof_photo = filename

                    # Start async photo analysis in background
                    socketio.start_background_task(
                        analyze_delivery_photo_background,
                        current_app._get_current_object(), order.id, filepath,
                        order.items_description or order.ai_enhanced_description
                    )

                    db.session.add(DeliveryLog(
                        order_id=order.id, event_type='delivery_proof_uploaded',
                        event_description=f'Delivery proof photo uploaded by {current_user.full_name}',
                        user_id=current_user.id, user_role='courier',
                    ))

            order.status = new_status
            if new_status == 'picked_up' and not order.picked_up_at:
                order.picked_up_at = utcnow()
            elif new_status == 'in_transit' and not order.in_transit_at:
                order.in_transit_at = utcnow()
            elif new_status == 'delivered' and not order.delivered_at:
                order.delivered_at = utcnow()
                current_user.successful_deliveries = (current_user.successful_deliveries or 0) + 1
                current_user.total_deliveries = (current_user.total_deliveries or 0) + 1

                if order.delivery_latitude and order.delivery_longitude:
                    current_user.last_known_latitude = order.delivery_latitude
                    current_user.last_known_longitude = order.delivery_longitude

                if current_user.pending_unavailable:
                    remaining = Order.query.filter_by(courier_id=current_user.id).filter(
                        Order.status.in_(['assigned', 'picked_up', 'in_transit']),
                        Order.id != order.id,
                    ).count()
                    if remaining == 0:
                        current_user.pending_unavailable = False
                        flash('You have completed all active deliveries and are now marked as unavailable.', 'info')
                else:
                    current_user.is_available = True

            db.session.add(DeliveryLog(
                order_id=order.id, event_type='status_change',
                event_description=f'Status changed from {old_status} to {new_status}',
                old_status=old_status, new_status=new_status,
                user_id=current_user.id, user_role='courier', timestamp=utcnow(),
            ))
            db.session.commit()

            svc = init_socketio_service()
            svc.emit_order_status_changed(order, old_status, new_status)
            if new_status == 'delivered':
                svc.emit_courier_availability(current_user)

            if new_status == 'picked_up':
                socketio.start_background_task(
                    transition_to_in_transit_background, order.id, current_app._get_current_object()
                )

            flash(f'Order status updated to {new_status}.', 'success')
            return redirect(url_for('courier_view_order', order_id=order.id))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating order status {order_id}: {e}")
            flash(f'Error updating order status: {e}', 'danger')
            return redirect(url_for('courier_view_order', order_id=order_id))

    @app.route('/courier/orders/history')
    @role_required('courier')
    def courier_order_history():
        page = request.args.get('page', 1, type=int)
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '').strip()
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        query = Order.query.filter_by(courier_id=current_user.id)
        if status_filter != 'all':
            query = query.filter_by(status=status_filter)
        if search_query:
            pattern = f'%{search_query}%'
            query = query.filter(db.or_(
                Order.order_number.ilike(pattern),
                Order.customer_name.ilike(pattern),
                Order.restaurant_name.ilike(pattern),
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
        return render_template('courier/order_history.html',
                               orders=pagination.items, pagination=pagination,
                               status_filter=status_filter, search_query=search_query,
                               date_from=date_from, date_to=date_to)

    @app.route('/courier/order/<int:order_id>')
    @role_required('courier')
    def courier_view_order(order_id):
        auto_transition_order_statuses()
        order = Order.query.get_or_404(order_id)
        if order.courier_id != current_user.id:
            flash('You do not have permission to view this order.', 'danger')
            return redirect(url_for('courier_dashboard'))

        logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

        if not order.ai_enhanced_description and order.items_description:
            socketio.start_background_task(enhance_in_background, current_app._get_current_object(), order.id, order.items_description)
            logger.info(f"Started background generation for order {order.order_number}")

        return render_template('courier/view_order.html', order=order, logs=logs)
