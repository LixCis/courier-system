from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps
from config import Config
from models import db, User, Order, DeliveryLog, SavedCustomer
from datetime import datetime
import secrets
import os
import sys
from werkzeug.utils import secure_filename
from services.llm_service import enhance_order_description

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

# Initialize background scheduler for pending orders
from services.order_scheduler import init_scheduler
scheduler = init_scheduler(app)


# Pre-generate AI insights on startup
def pregenerate_ai_insights():
    """Pre-generate AI insights for all users on startup (runs in background)"""
    import time
    import threading

    time.sleep(0.5)  # Wait 500ms for app to fully initialize

    with app.app_context():
        from services.ai_statistics import get_or_generate_ai_summary

        print("\n[AI] Pre-generating insights for all users...")

        try:
            # Generate for all couriers
            couriers = User.query.filter_by(role='courier').all()
            for courier in couriers:
                print(f"[AI] Generating insights for courier: {courier.full_name}")
                get_or_generate_ai_summary(courier.id, 'courier_daily')

            # Generate for all restaurants
            restaurants = User.query.filter_by(role='restaurant').all()
            for restaurant in restaurants:
                print(f"[AI] Generating insights for restaurant: {restaurant.full_name}")
                get_or_generate_ai_summary(restaurant.id, 'restaurant_weekly')

            # Generate admin summary
            print(f"[AI] Generating system-wide insights for admin")
            get_or_generate_ai_summary(None, 'admin_system')

            print("[AI] ✓ All insights pre-generated successfully!\n")
        except Exception as e:
            print(f"[AI] Error pre-generating insights: {e}\n")

# Start AI pre-generation in background thread (only in main process, not reloader)
import threading
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    ai_thread = threading.Thread(target=pregenerate_ai_insights, daemon=True)
    ai_thread.start()


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


def enhance_in_background(order_id, description):
    """Background task to enhance order description with AI"""
    with app.app_context():
        try:
            ai_enhanced = enhance_order_description(description)
            if ai_enhanced:
                # Update order with AI description
                order_to_update = Order.query.get(order_id)
                if order_to_update:
                    order_to_update.ai_enhanced_description = ai_enhanced
                    db.session.commit()
                    print(f"[AI] Description updated for order {order_to_update.order_number}")
        except Exception as e:
            print(f"[AI] Error enhancing order description in background: {e}")


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

    # If AI description is missing, generate it in background
    if not order.ai_enhanced_description and order.items_description:
        import threading
        bg_thread = threading.Thread(
            target=enhance_in_background,
            args=(order.id, order.items_description),
            daemon=True
        )
        bg_thread.start()
        print(f"[AI] Started background generation for order {order.order_number}")

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
        # Handle reset statistics for courier
        if 'reset_stats' in request.form and user.role == 'courier':
            user.total_deliveries = 0
            user.successful_deliveries = 0
            user.rejected_orders = 0
            db.session.commit()
            flash(f'Statistics reset for {user.full_name}!', 'success')
            return redirect(url_for('admin_edit_user', user_id=user.id))

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

        # Update location for restaurants (with GPS)
        if user.role == 'restaurant':
            user.current_location = request.form.get('current_location', '')
            pickup_lat_str = request.form.get('pickup_latitude')
            pickup_lon_str = request.form.get('pickup_longitude')

            if pickup_lat_str and pickup_lon_str:
                try:
                    user.last_known_latitude = float(pickup_lat_str)
                    user.last_known_longitude = float(pickup_lon_str)
                except ValueError:
                    flash('Invalid GPS coordinates.', 'error')
                    return render_template('admin/edit_user.html', user=user)

        # Update vehicle type for couriers
        if user.role == 'courier':
            user.vehicle_type = request.form.get('vehicle_type', 'bike')

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


@app.route('/admin/analytics')
@role_required('admin')
def admin_analytics():
    """Admin analytics page with system-wide AI insights"""
    from services.ai_statistics import get_or_generate_ai_summary, calculate_admin_stats

    # Get real-time stats
    stats = calculate_admin_stats()

    # Get AI summary (cached or generate new)
    ai_result = get_or_generate_ai_summary(
        user_id=None,  # Admin summaries have no user_id
        summary_type='admin_system',
        force_refresh=request.args.get('refresh') == '1'
    )

    return render_template('admin/analytics.html',
                         stats=stats,
                         ai_summary=ai_result['summary_text'],
                         ai_generated_at=ai_result['generated_at'],
                         ai_is_cached=ai_result['is_cached'])


@app.route('/admin/force-refresh-ai-cache', methods=['POST'])
@role_required('admin')
def admin_force_refresh_ai_cache():
    """Force refresh all AI summary cache (for testing)"""
    from services.ai_statistics import clear_all_ai_cache

    deleted_count = clear_all_ai_cache()

    flash(f'AI cache cleared successfully! {deleted_count} entries removed. New summaries will be generated on next view.', 'success')
    return redirect(request.referrer or url_for('admin_analytics'))


# ==================== Restaurant Routes ====================

@app.route('/restaurant/profile', methods=['GET', 'POST'])
@role_required('restaurant')
def restaurant_profile():
    """Restaurant profile edit page"""
    if request.method == 'POST':
        # Update basic info
        current_user.full_name = request.form.get('full_name')
        current_user.email = request.form.get('email')
        current_user.current_location = request.form.get('current_location')

        # Update pickup location (GPS)
        pickup_lat_str = request.form.get('pickup_latitude')
        pickup_lon_str = request.form.get('pickup_longitude')

        if pickup_lat_str and pickup_lon_str:
            try:
                current_user.last_known_latitude = float(pickup_lat_str)
                current_user.last_known_longitude = float(pickup_lon_str)
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
    """Restaurant statistics page with AI insights"""
    from services.ai_statistics import get_or_generate_ai_summary, calculate_restaurant_stats

    # Get real-time stats
    stats = calculate_restaurant_stats(current_user.id)

    # Get AI summary (cached or generate new)
    ai_result = get_or_generate_ai_summary(
        user_id=current_user.id,
        summary_type='restaurant_weekly',
        force_refresh=request.args.get('refresh') == '1'
    )

    return render_template('restaurant/statistics.html',
                         stats=stats,
                         ai_summary=ai_result['summary_text'],
                         ai_generated_at=ai_result['generated_at'],
                         ai_is_cached=ai_result['is_cached'])


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

        # Get GPS coordinates from map (required)
        pickup_address = request.form.get('pickup_address')
        pickup_lat_str = request.form.get('pickup_latitude')
        pickup_lon_str = request.form.get('pickup_longitude')
        delivery_lat_str = request.form.get('delivery_latitude')
        delivery_lon_str = request.form.get('delivery_longitude')

        # Validate GPS coordinates
        if not delivery_lat_str or not delivery_lon_str:
            flash('⚠️ Please select a delivery location on the map!', 'error')
            saved_customers = SavedCustomer.query.filter_by(restaurant_id=current_user.id).order_by(SavedCustomer.last_used_at.desc()).all()
            return render_template('restaurant/create_order.html', saved_customers=saved_customers)

        if not pickup_lat_str or not pickup_lon_str:
            flash('⚠️ Pickup location is missing. Please contact administrator.', 'error')
            saved_customers = SavedCustomer.query.filter_by(restaurant_id=current_user.id).order_by(SavedCustomer.last_used_at.desc()).all()
            return render_template('restaurant/create_order.html', saved_customers=saved_customers)

        try:
            pickup_lat = float(pickup_lat_str)
            pickup_lon = float(pickup_lon_str)
            delivery_lat = float(delivery_lat_str)
            delivery_lon = float(delivery_lon_str)
        except ValueError:
            flash('⚠️ Invalid GPS coordinates. Please select locations on the map.', 'error')
            saved_customers = SavedCustomer.query.filter_by(restaurant_id=current_user.id).order_by(SavedCustomer.last_used_at.desc()).all()
            return render_template('restaurant/create_order.html', saved_customers=saved_customers)

        # Generate unique order number
        order_number = f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"

        # Get items description (AI enhancement will happen in background)
        items_description = request.form.get('items_description')

        # Create new order (without AI description for now)
        order = Order(
            order_number=order_number,
            restaurant_id=current_user.id,
            restaurant_name=current_user.full_name,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_address=delivery_address,
            pickup_address=pickup_address,
            items_description=items_description,
            ai_enhanced_description=None,  # Will be filled in by background task
            special_instructions=request.form.get('special_instructions'),
            order_value=float(request.form.get('order_value') or 0),
            status='pending',
            # GPS coordinates from map (always provided)
            pickup_latitude=pickup_lat,
            pickup_longitude=pickup_lon,
            delivery_latitude=delivery_lat,
            delivery_longitude=delivery_lon
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

        # Start AI description enhancement in background (non-blocking)
        if items_description and items_description.strip():
            import threading
            bg_thread = threading.Thread(
                target=enhance_in_background,
                args=(order.id, items_description),
                daemon=True
            )
            bg_thread.start()

        # Auto-assign to courier
        success, message, courier = default_assignment_service.auto_assign_order(order)

        if success:
            # Build detailed success message with estimated times
            msg = f'Order {order.order_number} created and assigned to {courier.full_name}!'

            if order.estimated_total_time:
                msg += f' Estimated delivery: {order.estimated_total_time} minutes'
                if order.estimated_pickup_time:
                    msg += f' (pickup in ~{order.estimated_pickup_time} min, delivery in ~{order.estimated_delivery_time} min)'

            flash(msg, 'success')
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

    # If AI description is missing, generate it in background
    if not order.ai_enhanced_description and order.items_description:
        import threading
        bg_thread = threading.Thread(
            target=enhance_in_background,
            args=(order.id, order.items_description),
            daemon=True
        )
        bg_thread.start()
        print(f"[AI] Started background generation for order {order.order_number}")

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


@app.route('/courier/update-location', methods=['GET', 'POST'])
@role_required('courier')
def courier_update_location():
    """Update courier's current location"""
    if request.method == 'POST':
        latitude = float(request.form.get('latitude'))
        longitude = float(request.form.get('longitude'))

        # Update courier's location
        current_user.last_known_latitude = latitude
        current_user.last_known_longitude = longitude
        db.session.commit()

        flash('Your location has been updated successfully!', 'success')
        return redirect(url_for('courier_dashboard'))

    return render_template('courier/update_location.html')


@app.route('/courier/profile', methods=['GET', 'POST'])
@role_required('courier')
def courier_profile():
    """Courier profile edit page"""
    if request.method == 'POST':
        # Update basic info
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
    """Courier statistics page with AI insights"""
    from services.ai_statistics import get_or_generate_ai_summary, calculate_courier_stats

    # Get real-time stats
    stats = calculate_courier_stats(current_user.id)

    # Get AI summary (cached or generate new)
    ai_result = get_or_generate_ai_summary(
        user_id=current_user.id,
        summary_type='courier_daily',
        force_refresh=request.args.get('refresh') == '1'
    )

    return render_template('courier/statistics.html',
                         stats=stats,
                         ai_summary=ai_result['summary_text'],
                         ai_generated_at=ai_result['generated_at'],
                         ai_is_cached=ai_result['is_cached'])


@app.route('/courier/order/<int:order_id>/reject', methods=['POST'])
@role_required('courier')
def courier_reject_order(order_id):
    """Courier rejects an assigned order"""
    order = Order.query.get_or_404(order_id)

    # Verify order is assigned to this courier
    if order.courier_id != current_user.id:
        flash('You can only reject orders assigned to you.', 'error')
        return redirect(url_for('courier_dashboard'))

    # Only allow rejection if order hasn't been picked up yet
    if order.status not in ['assigned']:
        flash('You can only reject orders that haven\'t been picked up yet.', 'error')
        return redirect(url_for('courier_view_order', order_id=order.id))

    # Update rejection statistics
    current_user.rejected_orders = (current_user.rejected_orders or 0) + 1
    current_user.total_deliveries = (current_user.total_deliveries or 0) + 1

    # Track rejection with timestamp for timeout-based reassignment
    if not order.rejected_by_couriers:
        order.rejected_by_couriers = []

    order.rejected_by_couriers.append({
        'courier_id': current_user.id,
        'rejected_at': datetime.utcnow().isoformat()
    })

    # Log the rejection
    log_entry = DeliveryLog(
        order_id=order.id,
        event_type='order_rejected',
        event_description=f'Order rejected by {current_user.full_name}',
        old_status='assigned',
        new_status='pending',
        user_id=current_user.id,
        user_role='courier',
        timestamp=datetime.utcnow()
    )
    db.session.add(log_entry)

    # Reset order to pending
    old_courier = order.courier_id
    order.courier_id = None
    order.status = 'pending'
    order.assigned_at = None
    order.estimated_pickup_time = None
    order.estimated_delivery_time = None
    order.estimated_total_time = None

    db.session.commit()

    flash('Order rejected. It will be reassigned to another courier.', 'info')

    # Try to auto-reassign to another courier (excluding the one who just rejected)
    from services.assignment_algorithm import default_assignment_service
    success, message, new_courier = default_assignment_service.auto_assign_order(order, exclude_courier_id=old_courier)

    if success:
        flash(f'Order automatically reassigned to {new_courier.full_name}.', 'success')
    else:
        flash(f'Warning: {message}', 'warning')

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

            # Process image (GPS extraction, quality check, AI vision analysis)
            try:
                from services.image_analyzer import analyze_delivery_photo, get_analysis_for_db

                # Get order description for AI context
                order_desc = order.items_description or order.ai_enhanced_description

                # Analyze photo with AI vision
                analysis_result = analyze_delivery_photo(
                    filepath,
                    order_description=order_desc,
                    use_ai_vision=True
                )

                # Store analysis in database
                order.delivery_proof_analysis = get_analysis_for_db(analysis_result)

            except Exception as e:
                # If processing fails, still allow upload
                print(f"[Image Analysis] Error: {e}")
                order.delivery_proof_analysis = {
                    'error': str(e),
                    'gps_verified': False,
                    'gps_latitude': None,
                    'gps_longitude': None,
                    'gps_note': 'Image processing failed',
                    'image_timestamp': None,
                    'camera_make': None,
                    'camera_model': None,
                    'quality_score': 0,
                    'quality_acceptable': True,  # Don't block uploads
                    'quality_issues': [],
                    'ai_description': 'Analysis unavailable',
                    'ai_confidence': 0,
                    'ai_legitimate': True,
                    'ai_flags': [],
                    'ai_raw_answers': [],
                    'summary': 'Image uploaded (processing failed)'
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

        # Update courier performance stats
        current_user.successful_deliveries = (current_user.successful_deliveries or 0) + 1
        current_user.total_deliveries = (current_user.total_deliveries or 0) + 1

        # Update courier location to delivery address (where they just delivered)
        if order.delivery_latitude and order.delivery_longitude:
            current_user.last_known_latitude = order.delivery_latitude
            current_user.last_known_longitude = order.delivery_longitude

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

    # If AI description is missing, generate it in background
    if not order.ai_enhanced_description and order.items_description:
        import threading
        bg_thread = threading.Thread(
            target=enhance_in_background,
            args=(order.id, order.items_description),
            daemon=True
        )
        bg_thread.start()
        print(f"[AI] Started background generation for order {order.order_number}")

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


@app.route('/api/order/<int:order_id>/ai-description')
@login_required
def api_get_ai_description(order_id):
    """API endpoint to check if AI description is ready"""
    order = Order.query.get_or_404(order_id)

    # Check permissions
    if current_user.role == 'restaurant' and order.restaurant_id != current_user.id:
        from flask import jsonify
        return jsonify({'error': 'Unauthorized'}), 403
    elif current_user.role == 'courier' and order.courier_id != current_user.id:
        from flask import jsonify
        return jsonify({'error': 'Unauthorized'}), 403

    from flask import jsonify
    return jsonify({
        'ai_enhanced_description': order.ai_enhanced_description,
        'is_ready': order.ai_enhanced_description is not None
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

        # Create restaurant users (Ostrava locations with GPS)
        restaurant1 = User(
            username='pizza_palace',
            email='contact@pizzapalace.com',
            full_name='Pizza Palace Ostrava',
            role='restaurant',
            current_location='Nádražní 164/215, 702 00 Moravská Ostrava, Czechia',
            last_known_latitude=49.8348,  # Ostrava Main Station area
            last_known_longitude=18.2820
        )
        restaurant1.set_password('rest123')

        restaurant2 = User(
            username='burger_king',
            email='info@burgerking.com',
            full_name='Burger Kingdom Stodolní',
            role='restaurant',
            current_location='Stodolní 3, 702 00 Ostrava-Moravská Ostrava, Czechia',
            last_known_latitude=49.8385,  # Stodolní street
            last_known_longitude=18.2875
        )
        restaurant2.set_password('rest123')

        # Create courier users with Ostrava GPS locations
        courier1 = User(
            username='john_courier',
            email='john@courier.com',
            full_name='John Doe',
            role='courier',
            is_available=True,
            vehicle_type='bike',  # Fastest for city center
            last_known_latitude=49.8209,  # Ostrava city center
            last_known_longitude=18.2625,
            total_deliveries=0,
            successful_deliveries=0
        )
        courier1.set_password('courier123')

        courier2 = User(
            username='jane_courier',
            email='jane@courier.com',
            full_name='Jane Smith',
            role='courier',
            is_available=True,
            vehicle_type='scooter',  # Good balance
            last_known_latitude=49.8350,  # Ostrava north
            last_known_longitude=18.2820,
            total_deliveries=0,
            successful_deliveries=0
        )
        courier2.set_password('courier123')

        courier3 = User(
            username='mike_courier',
            email='mike@courier.com',
            full_name='Mike Johnson',
            role='courier',
            is_available=False,
            vehicle_type='motorcycle',  # Fastest overall
            last_known_latitude=49.8050,  # Ostrava south
            last_known_longitude=18.2500,
            total_deliveries=0,
            successful_deliveries=0
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


@app.cli.command()
def seed_enhanced():
    """Seed database with enhanced realistic data for AI statistics"""
    with app.app_context():
        from datetime import timedelta
        import random

        # Run normal seed first
        print("Running basic seed...")
        if not User.query.first():
            print("No users found, running standard seed first...")
            os.system(f"{sys.executable} -m flask seed-db")

        # Get users
        restaurant1 = User.query.filter_by(username='pizza_palace').first()
        restaurant2 = User.query.filter_by(username='burger_king').first()
        courier1 = User.query.filter_by(username='john_courier').first()
        courier2 = User.query.filter_by(username='jane_courier').first()
        courier3 = User.query.filter_by(username='mike_courier').first()

        if not all([restaurant1, restaurant2, courier1, courier2, courier3]):
            print("Error: Users not found. Run 'flask seed-db' first.")
            return

        # Sample areas in Ostrava
        delivery_areas = [
            {'area': 'Poruba', 'lat': 49.8209, 'lon': 18.1625, 'address': 'Opavská 1234, Poruba'},
            {'area': 'Stodolní', 'lat': 49.8385, 'lon': 18.2875, 'address': 'Stodolní 15, Moravská Ostrava'},
            {'area': 'Vítkovice', 'lat': 49.7987, 'lon': 18.2656, 'address': 'Ruská 567, Vítkovice'},
            {'area': 'Dubina', 'lat': 49.8123, 'lon': 18.2945, 'address': 'Dubinská 890, Dubina'},
            {'area': 'Zábřeh', 'lat': 49.8456, 'lon': 18.2234, 'address': 'Výškovická 321, Zábřeh'},
            {'area': 'Mariánské Hory', 'lat': 49.8234, 'lon': 18.2678, 'address': 'Horní 456, Mariánské Hory'},
        ]

        # Sample food items
        food_items = [
            "2x Pizza Margherita, 1x Coca Cola",
            "Velký burger s hranolky, 2x kečup",
            "3x Sushi set, wasabi extra",
            "Pizza Pepperoni (velká), 2x sprite",
            "Burger menu, bez okurek, přidat sýr",
            "4x Pizza (2x Margherita, 2x Salami)",
            "Kebab box, extra omáčka",
            "2x Burger, 3x hranolky, 2x cola",
            "Caesar salát s kuřecím, bez cibule, extra dresink",
            "Pasta Carbonara, extra parmezan, česnekový chléb",
            "2x Chicken wings (BBQ), 1x ranch omáčka",
            "Vegetarian wrap, avokádo, extra zelenina",
            "Pho bowl s hovězím, extra lime, sriracha",
            "Fish & chips, tartar omáčka, citron",
            "Pad Thai s krevetami, medium spicy",
            "3x Tacos (beef, chicken, veggie)",
            "Ramen s vepřovým, extra egg, nori",
            "Falafel wrap, hummus, extra tahini",
            "Chicken tikka masala, naan bread, 2x rice",
            "Poke bowl s lososem, extra wasabi, soy sauce",
        ]

        print("\nGenerating enhanced order data...")

        orders_created = 0
        now = datetime.utcnow()

        # Generate orders for last 14 days
        for days_ago in range(14):
            day_date = now - timedelta(days=days_ago)

            # More orders on weekends
            num_orders_per_day = random.randint(8, 15) if day_date.weekday() >= 5 else random.randint(4, 8)

            for _ in range(num_orders_per_day):
                # Random restaurant
                restaurant = random.choice([restaurant1, restaurant2])

                # Random delivery area
                delivery_loc = random.choice(delivery_areas)

                # Random time during the day (lunch 11-14, dinner 17-22)
                if random.random() > 0.5:
                    hour = random.randint(11, 14)  # Lunch
                else:
                    hour = random.randint(17, 22)  # Dinner

                minute = random.randint(0, 59)
                created_time = day_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # Create order
                order_number = f"ORD-{created_time.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"

                order = Order(
                    order_number=order_number,
                    restaurant_id=restaurant.id,
                    restaurant_name=restaurant.full_name,
                    customer_name=random.choice(['Jan Novák', 'Petra Svobodová', 'Martin Dvořák', 'Eva Kučerová', 'Tomáš Procházka']),
                    customer_phone=f"+420{random.randint(600000000, 799999999)}",
                    delivery_address=delivery_loc['address'],
                    pickup_address=restaurant.current_location,
                    items_description=random.choice(food_items),
                    order_value=random.randint(150, 800),
                    status='delivered',  # Most are delivered
                    pickup_latitude=restaurant.last_known_latitude,
                    pickup_longitude=restaurant.last_known_longitude,
                    delivery_latitude=delivery_loc['lat'],
                    delivery_longitude=delivery_loc['lon'],
                    created_at=created_time
                )

                # Assign courier and set timestamps
                courier = random.choice([courier1, courier2, courier3])
                order.courier_id = courier.id

                # Realistic timestamps
                order.assigned_at = created_time + timedelta(minutes=random.randint(1, 5))
                order.picked_up_at = order.assigned_at + timedelta(minutes=random.randint(5, 15))
                order.in_transit_at = order.picked_up_at + timedelta(seconds=5)
                order.delivered_at = order.in_transit_at + timedelta(minutes=random.randint(10, 30))

                # Update courier stats
                courier.total_deliveries += 1
                courier.successful_deliveries += 1

                db.session.add(order)
                orders_created += 1

                # Occasionally add a cancelled order
                if random.random() < 0.1:  # 10% cancelled
                    cancelled_order = Order(
                        order_number=f"ORD-{created_time.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
                        restaurant_id=restaurant.id,
                        restaurant_name=restaurant.full_name,
                        customer_name=random.choice(['Jan Novák', 'Petra Svobodová']),
                        customer_phone=f"+420{random.randint(600000000, 799999999)}",
                        delivery_address=delivery_loc['address'],
                        pickup_address=restaurant.current_location,
                        items_description=random.choice(food_items),
                        order_value=random.randint(150, 800),
                        status='cancelled',
                        pickup_latitude=restaurant.last_known_latitude,
                        pickup_longitude=restaurant.last_known_longitude,
                        delivery_latitude=delivery_loc['lat'],
                        delivery_longitude=delivery_loc['lon'],
                        created_at=created_time + timedelta(minutes=5)
                    )
                    db.session.add(cancelled_order)
                    orders_created += 1

        db.session.commit()

        print(f'\n[SUCCESS] Enhanced seed completed!')
        print(f'   - Created {orders_created} historical orders')
        print(f'   - Courier stats updated')
        print(f'   - Ready for AI statistics generation!')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
