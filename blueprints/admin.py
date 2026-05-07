"""Admin routes: dashboard, user management, analytics, AI insights."""
import json
from datetime import datetime

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user

from models import db, User, Order, DeliveryLog
from extensions import socketio, init_socketio_service, limiter
from common.decorators import role_required
from common.background import auto_transition_order_statuses, enhance_in_background, pregenerate_ai_insights
from common.logging_config import get_logger

logger = get_logger(__name__)


def register(app):
    @app.route('/admin/dashboard')
    @role_required('admin')
    def admin_dashboard():
        auto_transition_order_statuses()

        orders_page = request.args.get('orders_page', 1, type=int)
        logs_page = request.args.get('logs_page', 1, type=int)
        per_page = 10

        total_orders = Order.query.count()
        pending_orders = Order.query.filter_by(status='pending').count()
        active_orders = Order.query.filter(Order.status.in_(['assigned', 'picked_up', 'in_transit'])).count()
        completed_orders = Order.query.filter_by(status='delivered').count()

        total_couriers = User.query.filter_by(role='courier').count()
        available_couriers = User.query.filter_by(role='courier', is_available=True).count()
        total_restaurants = User.query.filter_by(role='restaurant').count()

        orders_pagination = Order.query.order_by(Order.created_at.desc()).paginate(
            page=orders_page, per_page=per_page, error_out=False
        )
        logs_pagination = DeliveryLog.query.order_by(DeliveryLog.timestamp.desc()).paginate(
            page=logs_page, per_page=15, error_out=False
        )

        all_couriers = User.query.filter_by(role='courier', is_active=True).all()

        # Aggregate active orders per courier to avoid N+1
        from sqlalchemy import func
        courier_orders = db.session.query(
            Order.courier_id,
            func.count(Order.id).label('active_orders_count')
        ).filter(Order.status.in_(['assigned', 'picked_up', 'in_transit'])).group_by(
            Order.courier_id
        ).all()
        orders_map = {courier_id: count for courier_id, count in courier_orders}

        couriers_json = json.dumps([{
            'id': c.id, 'name': c.full_name,
            'latitude': c.last_known_latitude, 'longitude': c.last_known_longitude,
            'is_available': c.is_available, 'vehicle_type': c.vehicle_type or 'bike',
            'active_orders_count': orders_map.get(c.id, 0)
        } for c in all_couriers])

        active_orders_list = Order.query.filter(
            Order.status.in_(['pending', 'assigned', 'picked_up', 'in_transit'])
        ).all()
        active_orders_json = json.dumps([{
            'id': o.id, 'order_number': o.order_number,
            'restaurant_name': o.restaurant_name, 'customer_name': o.customer_name,
            'status': o.status, 'pickup_address': o.pickup_address,
            'delivery_address': o.delivery_address,
            'pickup_latitude': o.pickup_latitude, 'pickup_longitude': o.pickup_longitude,
            'delivery_latitude': o.delivery_latitude, 'delivery_longitude': o.delivery_longitude
        } for o in active_orders_list])

        return render_template('admin/dashboard.html',
                               total_orders=total_orders, pending_orders=pending_orders,
                               active_orders=active_orders, completed_orders=completed_orders,
                               total_couriers=total_couriers, available_couriers=available_couriers,
                               total_restaurants=total_restaurants,
                               orders_pagination=orders_pagination, logs_pagination=logs_pagination,
                               couriers_json=couriers_json, active_orders_json=active_orders_json)

    @app.route('/admin/orders')
    @role_required('admin')
    def admin_orders():
        page = request.args.get('page', 1, type=int)
        per_page = 20
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '').strip()
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        query = Order.query
        if status_filter != 'all':
            query = query.filter_by(status=status_filter)

        if search_query:
            pattern = f'%{search_query}%'
            query = query.filter(db.or_(
                Order.order_number.ilike(pattern),
                Order.customer_name.ilike(pattern),
                Order.restaurant_name.ilike(pattern),
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
            page=page, per_page=per_page, error_out=False
        )
        return render_template('admin/orders.html', pagination=pagination,
                               status_filter=status_filter, search_query=search_query,
                               date_from=date_from, date_to=date_to)

    @app.route('/admin/order/<int:order_id>')
    @role_required('admin')
    def admin_view_order(order_id):
        auto_transition_order_statuses()
        order = Order.query.get_or_404(order_id)
        logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

        if not order.ai_enhanced_description and order.items_description:
            socketio.start_background_task(enhance_in_background, current_app._get_current_object(), order.id, order.items_description)
            logger.info(f"Started background generation for order {order.order_number}")

        return render_template('admin/view_order.html', order=order, logs=logs)

    @app.route('/admin/users')
    @role_required('admin')
    def admin_users():
        page = request.args.get('page', 1, type=int)
        pagination = User.query.order_by(User.role, User.full_name).paginate(
            page=page, per_page=20, error_out=False
        )
        return render_template('admin/users.html', pagination=pagination)

    @app.route('/admin/users/create', methods=['GET', 'POST'])
    @role_required('admin')
    def admin_create_user():
        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            full_name = request.form.get('full_name')
            role = request.form.get('role')
            password = request.form.get('password')

            if role == 'admin':
                flash('Cannot create additional admin accounts. Only one admin is allowed.', 'danger')
                return render_template('admin/create_user.html')
            if User.query.filter_by(username=username).first():
                flash('Username already exists.', 'danger')
                return render_template('admin/create_user.html')
            if User.query.filter_by(email=email).first():
                flash('Email already exists.', 'danger')
                return render_template('admin/create_user.html')

            user = User(username=username, email=email, full_name=full_name, role=role, is_active=True)
            user.set_password(password)
            if role == 'courier':
                user.is_available = True

            db.session.add(user)
            db.session.commit()

            flash(f'User {full_name} created successfully!', 'success')
            return redirect(url_for('admin_users'))
        return render_template('admin/create_user.html')

    @app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
    @role_required('admin')
    def admin_edit_user(user_id):
        user = User.query.get_or_404(user_id)
        if user.role == 'admin':
            flash('Cannot edit the admin account.', 'danger')
            return redirect(url_for('admin_users'))

        if request.method == 'POST':
            if 'reset_stats' in request.form and user.role == 'courier':
                user.total_deliveries = 0
                user.successful_deliveries = 0
                user.rejected_orders = 0
                db.session.commit()
                flash(f'Statistics reset for {user.full_name}!', 'success')
                return redirect(url_for('admin_edit_user', user_id=user.id))

            username = request.form.get('username')
            if username != user.username and User.query.filter_by(username=username).first():
                flash('Username already exists.', 'danger')
                return render_template('admin/edit_user.html', user=user)
            email = request.form.get('email')
            if email != user.email and User.query.filter_by(email=email).first():
                flash('Email already exists.', 'danger')
                return render_template('admin/edit_user.html', user=user)

            user.username = username
            user.email = email
            user.full_name = request.form.get('full_name')
            user.role = request.form.get('role')
            user.is_active = request.form.get('is_active') == 'on'

            if user.role == 'restaurant':
                user.current_location = request.form.get('current_location', '')
                plat = request.form.get('pickup_latitude')
                plon = request.form.get('pickup_longitude')
                if plat and plon:
                    try:
                        user.last_known_latitude = float(plat)
                        user.last_known_longitude = float(plon)
                    except ValueError:
                        flash('Invalid GPS coordinates.', 'error')
                        return render_template('admin/edit_user.html', user=user)

            if user.role == 'courier':
                user.vehicle_type = request.form.get('vehicle_type', 'bike')

            new_password = request.form.get('password')
            if new_password:
                user.set_password(new_password)

            db.session.commit()
            flash(f'User {user.full_name} updated successfully!', 'success')
            return redirect(url_for('admin_users'))

        return render_template('admin/edit_user.html', user=user)

    @app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
    @role_required('admin')
    def admin_delete_user(user_id):
        user = User.query.get_or_404(user_id)
        if user.role == 'admin':
            flash('Cannot delete the admin account.', 'danger')
            return redirect(url_for('admin_users'))
        if user.role == 'restaurant' and user.created_orders:
            flash(f'Cannot delete {user.full_name}. User has {len(user.created_orders)} orders.', 'danger')
            return redirect(url_for('admin_users'))
        if user.role == 'courier' and user.assigned_orders:
            flash(f'Cannot delete {user.full_name}. User has {len(user.assigned_orders)} assigned orders.', 'danger')
            return redirect(url_for('admin_users'))

        full_name = user.full_name
        db.session.delete(user)
        db.session.commit()
        flash(f'User {full_name} deleted successfully.', 'success')
        return redirect(url_for('admin_users'))

    @app.route('/admin/couriers/toggle/<int:courier_id>')
    @role_required('admin')
    def admin_toggle_courier_availability(courier_id):
        courier = User.query.get_or_404(courier_id)
        if courier.role != 'courier':
            flash('Invalid courier.', 'danger')
            return redirect(url_for('admin_users'))

        courier.is_available = not courier.is_available
        db.session.commit()
        init_socketio_service().emit_courier_availability(courier)

        status = 'available' if courier.is_available else 'unavailable'
        flash(f'{courier.full_name} is now {status}.', 'success')
        return redirect(request.referrer or url_for('admin_users'))

    @app.route('/admin/analytics')
    @role_required('admin')
    def admin_analytics():
        from services.ai_statistics import calculate_admin_stats
        stats = calculate_admin_stats()
        return render_template('admin/analytics.html', stats=stats)

    @app.route('/api/admin/ai-insights')
    @role_required('admin')
    @limiter.limit("10 per minute")
    def api_admin_ai_insights():
        from models import AIStatisticsSummary
        cached = AIStatisticsSummary.query.filter_by(user_id=None, summary_type='admin_system').first()
        if cached:
            return jsonify({
                'status': 'ready', 'summary': cached.summary_text,
                'generated_at': cached.generated_at.isoformat(), 'is_cached': True,
            })
        return jsonify({'status': 'loading', 'message': 'AI insights are being generated in the background...'})

    @app.route('/admin/force-refresh-ai-cache', methods=['POST'])
    @role_required('admin')
    def admin_force_refresh_ai_cache():
        from services.ai_statistics import clear_all_ai_cache
        deleted_count = clear_all_ai_cache()
        socketio.start_background_task(pregenerate_ai_insights, app)
        flash(f'AI cache cleared successfully! {deleted_count} entries removed. New summaries are being generated in the background.', 'success')
        return redirect(request.referrer or url_for('admin_analytics'))
