from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps
from config import Config
from models import db, User, Order, DeliveryLog, SavedCustomer
from datetime import datetime
import secrets
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config.from_object(Config)

# Make Python built-ins available in Jinja2 templates
app.jinja_env.globals.update(min=min, max=max)

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login"""
    return User.query.get(int(user_id))


def role_required(*roles):
    """Decorator to restrict access based on user role"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def auto_transition_order_statuses():
    """Automatically transition orders from picked_up to in_transit after 3 seconds
    Returns set of order IDs that were recently transitioned (within last 10 seconds)"""
    from datetime import timedelta

    # Find all orders with status 'picked_up'
    picked_up_orders = Order.query.filter_by(status='picked_up').all()

    if picked_up_orders:
        print(f"[auto_transition] Found {len(picked_up_orders)} orders with status 'picked_up'")

    transitions_made = 0
    transitioned_order_ids = set()

    for order in picked_up_orders:
        if order.picked_up_at:
            # Calculate time elapsed since pickup
            time_elapsed = datetime.utcnow() - order.picked_up_at
            seconds = time_elapsed.total_seconds()

            print(f"[auto_transition] Order #{order.order_number}: picked_up_at={order.picked_up_at}, elapsed={seconds:.1f}s")

            # If more than 3 seconds have passed, transition to in_transit
            if seconds >= 3:
                old_status = order.status
                order.status = 'in_transit'
                order.in_transit_at = datetime.utcnow()

                print(f"[auto_transition] >> Transitioning Order #{order.order_number} from {old_status} to in_transit")

                # Log the automatic status change
                log_entry = DeliveryLog(
                    order_id=order.id,
                    event_type='status_change',
                    event_description=f'Status automatically changed from {old_status} to in_transit',
                    old_status=old_status,
                    new_status='in_transit',
                    timestamp=datetime.utcnow()
                )
                db.session.add(log_entry)
                transitions_made += 1
                transitioned_order_ids.add(order.id)

    # Commit all changes
    if transitions_made > 0:
        db.session.commit()
        print(f"[auto_transition] Committed {transitions_made} transitions")

    # Also include orders that transitioned recently (within last 1 seconds)
    # This catches orders that transitioned between button click and page load
    recent_transitions = Order.query.filter(
        Order.status == 'in_transit',
        Order.in_transit_at.isnot(None)
    ).all()

    for order in recent_transitions:
        if order.in_transit_at:
            time_since_transition = datetime.utcnow() - order.in_transit_at
            if time_since_transition.total_seconds() <= 1:  # Reduced from 10 to 1 seconds to prevent reload loop
                transitioned_order_ids.add(order.id)

    return transitioned_order_ids


# ==================== Authentication Routes ====================

@app.route('/')
def index():
    """Landing page - redirect to dashboard if logged in"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated.', 'danger')
                return redirect(url_for('login'))

            login_user(user)
            flash(f'Welcome back, {user.full_name}!', 'success')

            # Redirect to appropriate dashboard
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    """Route to appropriate dashboard based on user role"""
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'restaurant':
        return redirect(url_for('restaurant_dashboard'))
    elif current_user.role == 'courier':
        return redirect(url_for('courier_dashboard'))
    else:
        flash('Invalid user role.', 'danger')
        return redirect(url_for('logout'))


# ==================== Admin Routes ====================

@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    """Admin dashboard with full system oversight"""
    # Auto-transition orders from picked_up to in_transit
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

    # Recent orders with pagination
    orders_pagination = Order.query.order_by(Order.created_at.desc()).paginate(
        page=orders_page, per_page=per_page, error_out=False
    )

    # Recent delivery logs with pagination
    logs_pagination = DeliveryLog.query.order_by(DeliveryLog.timestamp.desc()).paginate(
        page=logs_page, per_page=15, error_out=False
    )

    return render_template('admin/dashboard.html',
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         active_orders=active_orders,
                         completed_orders=completed_orders,
                         total_couriers=total_couriers,
                         available_couriers=available_couriers,
                         total_restaurants=total_restaurants,
                         orders_pagination=orders_pagination,
                         logs_pagination=logs_pagination)


@app.route('/admin/orders')
@role_required('admin')
def admin_orders():
    """View all orders with search and filter"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    status_filter = request.args.get('status', 'all')
    search_query = request.args.get('search', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Start with base query
    query = Order.query

    # Apply status filter
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    # Apply search filter (order number, customer name, or restaurant name)
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            db.or_(
                Order.order_number.ilike(search_pattern),
                Order.customer_name.ilike(search_pattern),
                Order.restaurant_name.ilike(search_pattern),
                Order.customer_phone.ilike(search_pattern)
            )
        )

    # Apply date range filter
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(Order.created_at >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            # Add one day to include the entire end date
            to_date = to_date.replace(hour=23, minute=59, second=59)
            query = query.filter(Order.created_at <= to_date)
        except ValueError:
            pass

    pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/orders.html',
                         pagination=pagination,
                         status_filter=status_filter,
                         search_query=search_query,
                         date_from=date_from,
                         date_to=date_to)


@app.route('/admin/order/<int:order_id>')
@role_required('admin')
def admin_view_order(order_id):
    """View order details (admin)"""
    # Auto-transition orders from picked_up to in_transit
    auto_transition_order_statuses()

    order = Order.query.get_or_404(order_id)
    logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

    return render_template('admin/view_order.html', order=order, logs=logs)


@app.route('/admin/users')
@role_required('admin')
def admin_users():
    """Manage users"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    pagination = User.query.order_by(User.role, User.full_name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/users.html', pagination=pagination)


@app.route('/admin/users/create', methods=['GET', 'POST'])
@role_required('admin')
def admin_create_user():
    """Create a new user"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        role = request.form.get('role')
        password = request.form.get('password')

        # Prevent creating additional admin accounts
        if role == 'admin':
            flash('Cannot create additional admin accounts. Only one admin is allowed.', 'danger')
            return render_template('admin/create_user.html')

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('admin/create_user.html')

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return render_template('admin/create_user.html')

        # Create new user
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            role=role,
            is_active=True
        )
        user.set_password(password)

        # Set courier-specific fields
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
    """Edit an existing user"""
    user = User.query.get_or_404(user_id)

    # Prevent editing admin account
    if user.role == 'admin':
        flash('Cannot edit the admin account.', 'danger')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        # Check if username is taken by another user
        username = request.form.get('username')
        if username != user.username and User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('admin/edit_user.html', user=user)

        # Check if email is taken by another user
        email = request.form.get('email')
        if email != user.email and User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return render_template('admin/edit_user.html', user=user)

        # Update user details
        user.username = username
        user.email = email
        user.full_name = request.form.get('full_name')
        user.role = request.form.get('role')
        user.is_active = request.form.get('is_active') == 'on'

        # Update location for restaurants
        if user.role == 'restaurant':
            user.current_location = request.form.get('current_location', '')

        # Update password if provided
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
    """Delete a user"""
    user = User.query.get_or_404(user_id)

    # Prevent deleting admin account
    if user.role == 'admin':
        flash('Cannot delete the admin account.', 'danger')
        return redirect(url_for('admin_users'))

    # Check if user has associated orders
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
    """Toggle courier availability"""
    courier = User.query.get_or_404(courier_id)

    if courier.role != 'courier':
        flash('Invalid courier.', 'danger')
        return redirect(url_for('admin_users'))

    courier.is_available = not courier.is_available
    db.session.commit()

    status = 'available' if courier.is_available else 'unavailable'
    flash(f'{courier.full_name} is now {status}.', 'success')

    return redirect(request.referrer or url_for('admin_users'))


# ==================== Restaurant Routes ====================

@app.route('/restaurant/dashboard')
@role_required('restaurant')
def restaurant_dashboard():
    """Restaurant dashboard - show only active orders"""
    # Auto-transition orders from picked_up to in_transit
    auto_transition_order_statuses()

    # Only show active orders (not delivered, not cancelled)
    active_orders_list = Order.query.filter_by(restaurant_id=current_user.id).filter(
        Order.status.in_(['pending', 'assigned', 'picked_up', 'in_transit'])
    ).order_by(Order.created_at.desc()).all()

    # Statistics
    all_orders = Order.query.filter_by(restaurant_id=current_user.id).all()
    total_orders = len(all_orders)
    pending_orders = sum(1 for o in all_orders if o.status == 'pending')
    active_orders = sum(1 for o in all_orders if o.status in ['assigned', 'picked_up', 'in_transit'])
    completed_orders = sum(1 for o in all_orders if o.status == 'delivered')

    # Count available couriers
    available_couriers = User.query.filter_by(role='courier', is_available=True, is_active=True).count()

    return render_template('restaurant/dashboard.html',
                         orders=active_orders_list,
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         active_orders=active_orders,
                         completed_orders=completed_orders,
                         available_couriers=available_couriers)


@app.route('/restaurant/order/create', methods=['GET', 'POST'])
@role_required('restaurant')
def restaurant_create_order():
    """Create a new order"""
    if request.method == 'POST':
        from services.assignment_algorithm import default_assignment_service

        customer_name = request.form.get('customer_name')
        customer_phone = request.form.get('customer_phone')
        delivery_address = request.form.get('delivery_address')
        save_customer = request.form.get('save_customer') == 'on'

        # Save customer if requested and not already saved
        if save_customer:
            existing = SavedCustomer.query.filter_by(
                restaurant_id=current_user.id,
                customer_phone=customer_phone
            ).first()

            if not existing:
                saved_customer = SavedCustomer(
                    restaurant_id=current_user.id,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    delivery_address=delivery_address,
                    last_used_at=datetime.utcnow()
                )
                db.session.add(saved_customer)
            else:
                # Update last used time
                existing.last_used_at = datetime.utcnow()

        # Generate unique order number
        order_number = f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"

        # Create new order
        order = Order(
            order_number=order_number,
            restaurant_id=current_user.id,
            restaurant_name=current_user.full_name,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_address=delivery_address,
            pickup_address=request.form.get('pickup_address', current_user.current_location or ''),
            items_description=request.form.get('items_description'),
            special_instructions=request.form.get('special_instructions'),
            order_value=float(request.form.get('order_value') or 0),
            status='pending'
        )

        db.session.add(order)
        db.session.flush()  # Get order ID

        # Log order creation
        log_entry = DeliveryLog(
            order_id=order.id,
            event_type='order_created',
            event_description=f'Order created by {current_user.full_name}',
            new_status='pending',
            user_id=current_user.id,
            user_role='restaurant',
            timestamp=datetime.utcnow()
        )
        db.session.add(log_entry)
        db.session.commit()

        # Auto-assign to courier
        success, message, courier = default_assignment_service.auto_assign_order(order)

        if success:
            flash(f'Order {order.order_number} created and assigned to {courier.full_name}!', 'success')
        else:
            flash(f'Order {order.order_number} created. {message}', 'warning')

        return redirect(url_for('restaurant_dashboard'))

    # Load saved customers for dropdown
    saved_customers = SavedCustomer.query.filter_by(restaurant_id=current_user.id).order_by(SavedCustomer.last_used_at.desc()).all()
    return render_template('restaurant/create_order.html', saved_customers=saved_customers)


@app.route('/restaurant/orders/history')
@role_required('restaurant')
def restaurant_order_history():
    """Restaurant order history with search, filters, and pagination"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    status_filter = request.args.get('status', 'all')
    search_query = request.args.get('search', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Start with base query
    query = Order.query.filter_by(restaurant_id=current_user.id)

    # Apply status filter
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    # Apply search filter
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            db.or_(
                Order.order_number.ilike(search_pattern),
                Order.customer_name.ilike(search_pattern),
                Order.customer_phone.ilike(search_pattern)
            )
        )

    # Apply date range filter
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(Order.created_at >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            to_date = to_date.replace(hour=23, minute=59, second=59)
            query = query.filter(Order.created_at <= to_date)
        except ValueError:
            pass

    # Paginate
    pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('restaurant/order_history.html',
                         orders=pagination.items,
                         pagination=pagination,
                         status_filter=status_filter,
                         search_query=search_query,
                         date_from=date_from,
                         date_to=date_to)


@app.route('/restaurant/order/<int:order_id>')
@role_required('restaurant')
def restaurant_view_order(order_id):
    """View order details"""
    # Auto-transition orders from picked_up to in_transit
    auto_transition_order_statuses()

    order = Order.query.get_or_404(order_id)

    # Ensure restaurant can only view their own orders
    if order.restaurant_id != current_user.id:
        flash('You do not have permission to view this order.', 'danger')
        return redirect(url_for('restaurant_dashboard'))

    logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

    return render_template('restaurant/view_order.html', order=order, logs=logs)


@app.route('/restaurant/order/<int:order_id>/edit', methods=['GET', 'POST'])
@role_required('restaurant')
def restaurant_edit_order(order_id):
    """Edit order (only before courier picks up)"""
    order = Order.query.get_or_404(order_id)

    # Ensure restaurant can only edit their own orders
    if order.restaurant_id != current_user.id:
        flash('You do not have permission to edit this order.', 'danger')
        return redirect(url_for('restaurant_dashboard'))

    # Only allow editing if order hasn't been picked up yet
    if order.status not in ['pending', 'assigned']:
        flash('Cannot edit order after it has been picked up.', 'danger')
        return redirect(url_for('restaurant_view_order', order_id=order.id))

    if request.method == 'POST':
        # Update order details
        order.customer_name = request.form.get('customer_name')
        order.customer_phone = request.form.get('customer_phone')
        order.delivery_address = request.form.get('delivery_address')
        order.pickup_address = request.form.get('pickup_address')
        order.items_description = request.form.get('items_description')
        order.special_instructions = request.form.get('special_instructions')
        order.order_value = float(request.form.get('order_value') or 0)

        # Log the edit
        log_entry = DeliveryLog(
            order_id=order.id,
            event_type='order_edited',
            event_description=f'Order details updated by {current_user.full_name}',
            user_id=current_user.id,
            user_role='restaurant'
        )
        db.session.add(log_entry)
        db.session.commit()

        flash('Order updated successfully!', 'success')
        return redirect(url_for('restaurant_view_order', order_id=order.id))

    return render_template('restaurant/edit_order.html', order=order)


@app.route('/restaurant/order/<int:order_id>/cancel', methods=['POST'])
@role_required('restaurant')
def restaurant_cancel_order(order_id):
    """Cancel an order"""
    order = Order.query.get_or_404(order_id)

    # Ensure restaurant can only cancel their own orders
    if order.restaurant_id != current_user.id:
        flash('You do not have permission to cancel this order.', 'danger')
        return redirect(url_for('restaurant_dashboard'))

    # Only allow cancelling if order hasn't been picked up yet
    if order.status not in ['pending', 'assigned']:
        flash('Cannot cancel order after it has been picked up.', 'danger')
        return redirect(url_for('restaurant_view_order', order_id=order.id))

    cancel_reason = request.form.get('cancel_reason', 'No reason provided')
    old_status = order.status

    # Update order status to cancelled
    order.status = 'cancelled'

    # If courier was assigned, make them available again
    if order.courier_id and order.status == 'assigned':
        courier = User.query.get(order.courier_id)
        if courier:
            courier.is_available = True

    # Log the cancellation
    log_entry = DeliveryLog(
        order_id=order.id,
        event_type='order_cancelled',
        event_description=f'Order cancelled by {current_user.full_name}. Reason: {cancel_reason}',
        old_status=old_status,
        new_status='cancelled',
        user_id=current_user.id,
        user_role='restaurant'
    )
    db.session.add(log_entry)
    db.session.commit()

    flash(f'Order {order.order_number} has been cancelled.', 'success')
    return redirect(url_for('restaurant_dashboard'))


@app.route('/restaurant/order/<int:order_id>/update-status', methods=['POST'])
@role_required('restaurant')
def restaurant_update_order_status(order_id):
    """Update order status (for restaurants)"""
    order = Order.query.get_or_404(order_id)

    # Ensure restaurant can only update their own orders
    if order.restaurant_id != current_user.id:
        flash('You do not have permission to update this order.', 'danger')
        return redirect(url_for('restaurant_dashboard'))

    new_status = request.form.get('status')
    old_status = order.status

    # Update status and timestamps
    order.status = new_status

    if new_status == 'picked_up' and not order.picked_up_at:
        order.picked_up_at = datetime.utcnow()
    elif new_status == 'in_transit' and not order.in_transit_at:
        order.in_transit_at = datetime.utcnow()

    # Log the status change
    log_entry = DeliveryLog(
        order_id=order.id,
        event_type='status_change',
        event_description=f'Status changed from {old_status} to {new_status} by {current_user.full_name}',
        old_status=old_status,
        new_status=new_status,
        user_id=current_user.id,
        user_role='restaurant'
    )
    db.session.add(log_entry)
    db.session.commit()

    flash(f'Order status updated to {new_status}.', 'success')
    return redirect(url_for('restaurant_view_order', order_id=order.id))


# ==================== Courier Routes ====================

@app.route('/courier/dashboard')
@role_required('courier')
def courier_dashboard():
    """Courier dashboard - only shows active orders"""
    # Auto-transition orders from picked_up to in_transit
    auto_transition_order_statuses()

    # Only show active orders
    active_orders = Order.query.filter_by(courier_id=current_user.id).filter(
        Order.status.in_(['assigned', 'picked_up', 'in_transit'])
    ).order_by(Order.created_at.desc()).all()

    # Statistics
    all_orders = Order.query.filter_by(courier_id=current_user.id).all()
    completed_today = [o for o in all_orders if o.status == 'delivered' and
                      o.delivered_at and o.delivered_at.date() == datetime.utcnow().date()]

    return render_template('courier/dashboard.html',
                         active_orders=active_orders,
                         completed_orders=completed_today,
                         is_available=current_user.is_available)


@app.route('/courier/toggle-availability')
@role_required('courier')
def courier_toggle_availability():
    """Toggle courier's own availability"""
    # Check if courier has active orders
    active_orders = Order.query.filter_by(courier_id=current_user.id).filter(
        Order.status.in_(['assigned', 'picked_up', 'in_transit'])
    ).count()

    if active_orders > 0 and current_user.is_available:
        # Trying to go unavailable while having active orders
        # Set pending_unavailable flag and mark as unavailable immediately
        current_user.pending_unavailable = True
        current_user.is_available = False
        db.session.commit()

        flash(f'You have {active_orders} active order(s). You are now unavailable for new orders and will remain unavailable after completing all deliveries.', 'info')
        return redirect(url_for('courier_dashboard'))

    # Normal toggle (no active orders)
    current_user.is_available = not current_user.is_available
    current_user.pending_unavailable = False  # Clear flag if manually toggling back to available
    db.session.commit()

    status = 'available' if current_user.is_available else 'unavailable'
    flash(f'You are now {status} for new orders.', 'success')

    return redirect(url_for('courier_dashboard'))


@app.route('/courier/order/<int:order_id>/update', methods=['POST'])
@role_required('courier')
def courier_update_order_status(order_id):
    """Update order status"""
    order = Order.query.get_or_404(order_id)

    # Ensure courier can only update their assigned orders
    if order.courier_id != current_user.id:
        flash('You do not have permission to update this order.', 'danger')
        return redirect(url_for('courier_dashboard'))

    new_status = request.form.get('status')
    old_status = order.status

    # Handle file upload for delivery proof
    if 'delivery_proof' in request.files:
        file = request.files['delivery_proof']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{order.order_number}_{secrets.token_hex(4)}.{file.filename.rsplit('.', 1)[1].lower()}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            order.delivery_proof_photo = filename

            # Process image (GPS extraction, quality check, privacy protection)
            try:
                from image_processing import process_delivery_image
                analysis_result = process_delivery_image(filepath, apply_privacy_protection=True)
                order.delivery_proof_analysis = {
                    'gps_verified': analysis_result['metadata']['has_gps'],
                    'gps_latitude': analysis_result['metadata']['gps_latitude'],
                    'gps_longitude': analysis_result['metadata']['gps_longitude'],
                    'gps_note': analysis_result['metadata']['gps_note'],
                    'quality_score': analysis_result['quality']['quality_score'],
                    'quality_acceptable': analysis_result['quality']['is_acceptable'],
                    'quality_issues': analysis_result['quality']['issues'],
                    'faces_blurred': analysis_result['privacy']['faces_blurred'],
                    'summary': analysis_result['summary']
                }
            except Exception as e:
                # If processing fails (e.g., Pillow not installed), still allow upload
                order.delivery_proof_analysis = {
                    'error': str(e),
                    'gps_note': 'Image processing not available - install Pillow to enable',
                    'quality_score': 0,
                    'quality_acceptable': True,  # Don't block uploads
                    'quality_issues': [],
                    'faces_blurred': 0,
                    'summary': 'Image uploaded (processing unavailable)'
                }

            # Log photo upload
            log_entry = DeliveryLog(
                order_id=order.id,
                event_type='delivery_proof_uploaded',
                event_description=f'Delivery proof photo uploaded by {current_user.full_name}',
                user_id=current_user.id,
                user_role='courier'
            )
            db.session.add(log_entry)

    # Update status and timestamps
    order.status = new_status

    if new_status == 'picked_up' and not order.picked_up_at:
        order.picked_up_at = datetime.utcnow()
    elif new_status == 'in_transit' and not order.in_transit_at:
        order.in_transit_at = datetime.utcnow()
    elif new_status == 'delivered' and not order.delivered_at:
        order.delivered_at = datetime.utcnow()

        # Check if courier has pending_unavailable flag
        if current_user.pending_unavailable:
            # Check if this was the last active order
            remaining_active = Order.query.filter_by(courier_id=current_user.id).filter(
                Order.status.in_(['assigned', 'picked_up', 'in_transit']),
                Order.id != order.id  # Exclude current order (already marked as delivered)
            ).count()

            if remaining_active == 0:
                # This was the last order - clear flag and stay unavailable
                current_user.pending_unavailable = False
                flash('You have completed all active deliveries and are now marked as unavailable.', 'info')
            # else: courier still has more orders, stay unavailable for new orders
        else:
            # No pending_unavailable flag - make courier available again as normal
            current_user.is_available = True

    # Log the status change
    log_entry = DeliveryLog(
        order_id=order.id,
        event_type='status_change',
        event_description=f'Status changed from {old_status} to {new_status}',
        old_status=old_status,
        new_status=new_status,
        user_id=current_user.id,
        user_role='courier',
        timestamp=datetime.utcnow()
    )

    db.session.add(log_entry)
    db.session.commit()

    flash(f'Order status updated to {new_status}.', 'success')
    return redirect(url_for('courier_view_order', order_id=order.id))


@app.route('/courier/orders/history')
@role_required('courier')
def courier_order_history():
    """Courier order history with search, filters, and pagination"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    status_filter = request.args.get('status', 'all')
    search_query = request.args.get('search', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Start with base query
    query = Order.query.filter_by(courier_id=current_user.id)

    # Apply status filter
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    # Apply search filter
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            db.or_(
                Order.order_number.ilike(search_pattern),
                Order.customer_name.ilike(search_pattern),
                Order.restaurant_name.ilike(search_pattern)
            )
        )

    # Apply date range filter
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(Order.created_at >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            to_date = to_date.replace(hour=23, minute=59, second=59)
            query = query.filter(Order.created_at <= to_date)
        except ValueError:
            pass

    # Paginate
    pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('courier/order_history.html',
                         orders=pagination.items,
                         pagination=pagination,
                         status_filter=status_filter,
                         search_query=search_query,
                         date_from=date_from,
                         date_to=date_to)


@app.route('/courier/order/<int:order_id>')
@role_required('courier')
def courier_view_order(order_id):
    """View order details"""
    # Auto-transition orders from picked_up to in_transit
    auto_transition_order_statuses()

    order = Order.query.get_or_404(order_id)

    # Ensure courier can only view their assigned orders
    if order.courier_id != current_user.id:
        flash('You do not have permission to view this order.', 'danger')
        return redirect(url_for('courier_dashboard'))

    logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

    return render_template('courier/view_order.html', order=order, logs=logs)


# ==================== Error Handlers ====================

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500


# ==================== API Routes (for AJAX polling) ====================

@app.route('/api/admin/dashboard-data')
@role_required('admin')
def api_admin_dashboard_data():
    """API endpoint for admin dashboard real-time data"""
    auto_transition_order_statuses()

    # Statistics
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    active_orders = Order.query.filter(Order.status.in_(['assigned', 'picked_up', 'in_transit'])).count()
    completed_orders = Order.query.filter_by(status='delivered').count()
    total_couriers = User.query.filter_by(role='courier').count()
    available_couriers = User.query.filter_by(role='courier', is_available=True).count()
    total_restaurants = User.query.filter_by(role='restaurant').count()

    # Recent orders (last 10)
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()

    # Recent logs (last 15)
    recent_logs = DeliveryLog.query.order_by(DeliveryLog.timestamp.desc()).limit(15).all()

    from flask import jsonify
    return jsonify({
        'statistics': {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'active_orders': active_orders,
            'completed_orders': completed_orders,
            'total_couriers': total_couriers,
            'available_couriers': available_couriers,
            'total_restaurants': total_restaurants
        },
        'recent_orders': [{
            'id': order.id,
            'order_number': order.order_number,
            'restaurant_name': order.restaurant_name,
            'customer_name': order.customer_name,
            'status': order.status,
            'courier_name': order.courier_user.full_name if order.courier_user else None,
            'created_at': order.created_at.isoformat(),
            'order_value': order.order_value
        } for order in recent_orders],
        'recent_logs': [{
            'id': log.id,
            'order_id': log.order_id,
            'order_number': log.order.order_number if log.order else None,
            'event_type': log.event_type,
            'event_description': log.event_description,
            'timestamp': log.timestamp.isoformat()
        } for log in recent_logs]
    })


@app.route('/api/admin/order/<int:order_id>')
@role_required('admin')
def api_admin_order_detail(order_id):
    """API endpoint for order detail real-time data"""
    transitioned_ids = auto_transition_order_statuses()
    db.session.expire_all()  # Clear cache to get fresh data

    order = Order.query.get_or_404(order_id)
    logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

    from flask import jsonify
    return jsonify({
        'auto_transitioned': order.id in transitioned_ids,  # Flag if this order just transitioned
        'order': {
            'id': order.id,
            'order_number': order.order_number,
            'status': order.status,
            'restaurant_name': order.restaurant_name,
            'customer_name': order.customer_name,
            'customer_phone': order.customer_phone,
            'delivery_address': order.delivery_address,
            'pickup_address': order.pickup_address,
            'courier_name': order.courier_user.full_name if order.courier_user else None,
            'courier_id': order.courier_id,
            'order_value': order.order_value,
            'items_description': order.items_description,
            'special_instructions': order.special_instructions,
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'assigned_at': order.assigned_at.isoformat() if order.assigned_at else None,
            'picked_up_at': order.picked_up_at.isoformat() if order.picked_up_at else None,
            'in_transit_at': order.in_transit_at.isoformat() if order.in_transit_at else None,
            'delivered_at': order.delivered_at.isoformat() if order.delivered_at else None
        },
        'logs': [{
            'id': log.id,
            'event_type': log.event_type,
            'event_description': log.event_description,
            'old_status': log.old_status,
            'new_status': log.new_status,
            'timestamp': log.timestamp.isoformat()
        } for log in logs]
    })


@app.route('/api/restaurant/dashboard-data')
@role_required('restaurant')
def api_restaurant_dashboard_data():
    """API endpoint for restaurant dashboard real-time data"""
    auto_transition_order_statuses()

    # Active orders only
    active_orders_list = Order.query.filter_by(restaurant_id=current_user.id).filter(
        Order.status.in_(['pending', 'assigned', 'picked_up', 'in_transit'])
    ).order_by(Order.created_at.desc()).all()

    # Statistics
    all_orders = Order.query.filter_by(restaurant_id=current_user.id).all()
    total_orders = len(all_orders)
    pending_orders = sum(1 for o in all_orders if o.status == 'pending')
    active_orders = sum(1 for o in all_orders if o.status in ['assigned', 'picked_up', 'in_transit'])
    completed_orders = sum(1 for o in all_orders if o.status == 'delivered')
    available_couriers = User.query.filter_by(role='courier', is_available=True, is_active=True).count()

    from flask import jsonify
    return jsonify({
        'statistics': {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'active_orders': active_orders,
            'completed_orders': completed_orders,
            'available_couriers': available_couriers
        },
        'active_orders': [{
            'id': order.id,
            'order_number': order.order_number,
            'customer_name': order.customer_name,
            'customer_phone': order.customer_phone,
            'delivery_address': order.delivery_address,
            'status': order.status,
            'courier_name': order.courier_user.full_name if order.courier_user else None,
            'created_at': order.created_at.isoformat(),
            'order_value': order.order_value
        } for order in active_orders_list]
    })


@app.route('/api/restaurant/order/<int:order_id>')
@role_required('restaurant')
def api_restaurant_order_detail(order_id):
    """API endpoint for restaurant order detail"""
    transitioned_ids = auto_transition_order_statuses()
    db.session.expire_all()  # Clear cache to get fresh data

    order = Order.query.get_or_404(order_id)

    # Ensure restaurant can only access their own orders
    if order.restaurant_id != current_user.id:
        from flask import jsonify
        return jsonify({'error': 'Unauthorized'}), 403

    logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

    from flask import jsonify
    return jsonify({
        'auto_transitioned': order.id in transitioned_ids,  # Flag if this order just transitioned
        'order': {
            'id': order.id,
            'order_number': order.order_number,
            'status': order.status,
            'customer_name': order.customer_name,
            'customer_phone': order.customer_phone,
            'delivery_address': order.delivery_address,
            'pickup_address': order.pickup_address,
            'courier_name': order.courier_user.full_name if order.courier_user else None,
            'courier_id': order.courier_id,
            'order_value': order.order_value,
            'items_description': order.items_description,
            'special_instructions': order.special_instructions,
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'assigned_at': order.assigned_at.isoformat() if order.assigned_at else None,
            'picked_up_at': order.picked_up_at.isoformat() if order.picked_up_at else None,
            'in_transit_at': order.in_transit_at.isoformat() if order.in_transit_at else None,
            'delivered_at': order.delivered_at.isoformat() if order.delivered_at else None
        },
        'logs': [{
            'id': log.id,
            'event_type': log.event_type,
            'event_description': log.event_description,
            'old_status': log.old_status,
            'new_status': log.new_status,
            'timestamp': log.timestamp.isoformat()
        } for log in logs]
    })


@app.route('/api/courier/dashboard-data')
@role_required('courier')
def api_courier_dashboard_data():
    """API endpoint for courier dashboard real-time data"""
    auto_transition_order_statuses()

    # Active orders
    active_orders = Order.query.filter_by(courier_id=current_user.id).filter(
        Order.status.in_(['assigned', 'picked_up', 'in_transit'])
    ).order_by(Order.created_at.desc()).all()

    # Completed today
    all_orders = Order.query.filter_by(courier_id=current_user.id).all()
    completed_today = [o for o in all_orders if o.status == 'delivered' and
                      o.delivered_at and o.delivered_at.date() == datetime.utcnow().date()]

    from flask import jsonify
    return jsonify({
        'statistics': {
            'active_orders_count': len(active_orders),
            'completed_today_count': len(completed_today),
            'is_available': current_user.is_available,
            'pending_unavailable': current_user.pending_unavailable
        },
        'active_orders': [{
            'id': order.id,
            'order_number': order.order_number,
            'restaurant_name': order.restaurant_name,
            'customer_name': order.customer_name,
            'customer_phone': order.customer_phone,
            'delivery_address': order.delivery_address,
            'pickup_address': order.pickup_address,
            'status': order.status,
            'created_at': order.created_at.isoformat(),
            'order_value': order.order_value
        } for order in active_orders]
    })


@app.route('/api/courier/order/<int:order_id>')
@role_required('courier')
def api_courier_order_detail(order_id):
    """API endpoint for courier order detail"""
    transitioned_ids = auto_transition_order_statuses()
    db.session.expire_all()  # Clear cache to get fresh data

    order = Order.query.get_or_404(order_id)

    # Ensure courier can only access their assigned orders
    if order.courier_id != current_user.id:
        from flask import jsonify
        return jsonify({'error': 'Unauthorized'}), 403

    logs = DeliveryLog.query.filter_by(order_id=order.id).order_by(DeliveryLog.timestamp.desc()).all()

    from flask import jsonify
    return jsonify({
        'auto_transitioned': order.id in transitioned_ids,  # Flag if this order just transitioned
        'order': {
            'id': order.id,
            'order_number': order.order_number,
            'status': order.status,
            'restaurant_name': order.restaurant_name,
            'customer_name': order.customer_name,
            'customer_phone': order.customer_phone,
            'delivery_address': order.delivery_address,
            'pickup_address': order.pickup_address,
            'order_value': order.order_value,
            'items_description': order.items_description,
            'special_instructions': order.special_instructions,
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'assigned_at': order.assigned_at.isoformat() if order.assigned_at else None,
            'picked_up_at': order.picked_up_at.isoformat() if order.picked_up_at else None,
            'in_transit_at': order.in_transit_at.isoformat() if order.in_transit_at else None,
            'delivered_at': order.delivered_at.isoformat() if order.delivered_at else None
        },
        'logs': [{
            'id': log.id,
            'event_type': log.event_type,
            'event_description': log.event_description,
            'old_status': log.old_status,
            'new_status': log.new_status,
            'timestamp': log.timestamp.isoformat()
        } for log in logs]
    })


# ==================== Database Initialization ====================

@app.cli.command()
def init_db():
    """Initialize the database"""
    with app.app_context():
        db.create_all()
        print('Database initialized!')


@app.cli.command()
def seed_db():
    """Seed the database with sample data"""
    with app.app_context():
        # Check if data already exists
        if User.query.first():
            print('Database already contains data. Skipping seed.')
            return

        # Create admin user
        admin = User(
            username='admin',
            email='admin@courier.com',
            full_name='System Administrator',
            role='admin'
        )
        admin.set_password('admin123')

        # Create restaurant users
        restaurant1 = User(
            username='pizza_palace',
            email='contact@pizzapalace.com',
            full_name='Pizza Palace',
            role='restaurant',
            current_location='123 Main St, Downtown'
        )
        restaurant1.set_password('rest123')

        restaurant2 = User(
            username='burger_king',
            email='info@burgerking.com',
            full_name='Burger Kingdom',
            role='restaurant',
            current_location='456 Oak Ave, Midtown'
        )
        restaurant2.set_password('rest123')

        # Create courier users
        courier1 = User(
            username='john_courier',
            email='john@courier.com',
            full_name='John Doe',
            role='courier',
            is_available=True
        )
        courier1.set_password('courier123')

        courier2 = User(
            username='jane_courier',
            email='jane@courier.com',
            full_name='Jane Smith',
            role='courier',
            is_available=True
        )
        courier2.set_password('courier123')

        courier3 = User(
            username='mike_courier',
            email='mike@courier.com',
            full_name='Mike Johnson',
            role='courier',
            is_available=False
        )
        courier3.set_password('courier123')

        db.session.add_all([admin, restaurant1, restaurant2, courier1, courier2, courier3])
        db.session.commit()

        print('Database seeded successfully!')
        print('\nLogin Credentials:')
        print('Admin: admin / admin123')
        print('Restaurant: pizza_palace / rest123')
        print('Restaurant: burger_king / rest123')
        print('Courier: john_courier / courier123')
        print('Courier: jane_courier / courier123')
        print('Courier: mike_courier / courier123')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
