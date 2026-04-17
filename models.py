from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model with role-based access"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'restaurant', 'courier'
    full_name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Courier-specific fields
    is_available = db.Column(db.Boolean, default=True)  # For couriers only
    pending_unavailable = db.Column(db.Boolean, default=False)  # Courier wants to go unavailable after completing orders
    current_location = db.Column(db.String(200))  # For future GPS integration
    vehicle_type = db.Column(db.String(20), default='bike')  # bike, scooter, motorcycle, car, van

    # Basic courier tracking
    total_deliveries = db.Column(db.Integer, default=0)
    successful_deliveries = db.Column(db.Integer, default=0)
    rejected_orders = db.Column(db.Integer, default=0)  # Orders courier rejected
    last_known_latitude = db.Column(db.Float)
    last_known_longitude = db.Column(db.Float)

    # Relationships
    created_orders = db.relationship('Order', backref='restaurant_user', lazy=True, foreign_keys='Order.restaurant_id')
    assigned_orders = db.relationship('Order', backref='courier_user', lazy=True, foreign_keys='Order.courier_id')

    def set_password(self, password):
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify password against hash"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Order(db.Model):
    """Order model for tracking deliveries"""
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)

    # Restaurant information
    restaurant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    restaurant_name = db.Column(db.String(120), nullable=False)

    # Delivery details
    customer_name = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    delivery_address = db.Column(db.Text, nullable=False)
    pickup_address = db.Column(db.Text, nullable=False)

    # Order details
    items_description = db.Column(db.Text)
    ai_enhanced_description = db.Column(db.Text)  # AI-standardized version of items_description
    special_instructions = db.Column(db.Text)
    order_value = db.Column(db.Float, default=0.0)

    # Assignment and status
    courier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, assigned, picked_up, in_transit, delivered, cancelled
    priority = db.Column(db.Integer, default=0)  # For future AI optimization

    # Delivery proof
    delivery_proof_photo = db.Column(db.String(255))  # Path to uploaded photo
    delivery_proof_analysis = db.Column(db.JSON)  # Image analysis results (GPS, quality, privacy)

    # Rejection tracking (for timeout-based reassignment)
    rejected_by_couriers = db.Column(db.JSON)  # [{courier_id: X, rejected_at: timestamp}, ...]

    # Geocoding cache
    pickup_latitude = db.Column(db.Float)
    pickup_longitude = db.Column(db.Float)
    delivery_latitude = db.Column(db.Float)
    delivery_longitude = db.Column(db.Float)

    # Timestamps (critical for AI analysis)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    assigned_at = db.Column(db.DateTime)
    picked_up_at = db.Column(db.DateTime)
    in_transit_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)

    # Estimated times (in minutes)
    estimated_pickup_time = db.Column(db.Integer)  # Minutes for courier to reach restaurant
    estimated_delivery_time = db.Column(db.Integer)  # Minutes from restaurant to customer
    estimated_total_time = db.Column(db.Integer)  # Total minutes (pickup + delivery)

    # Relationships
    delivery_logs = db.relationship('DeliveryLog', backref='order', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.order_number} - {self.status}>'


class DeliveryLog(db.Model):
    """Delivery log for tracking order events and AI analysis"""
    __tablename__ = 'delivery_logs'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)

    # Event tracking
    event_type = db.Column(db.String(50), nullable=False)  # status_change, location_update, note, etc.
    event_description = db.Column(db.Text)
    old_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20))

    # Actor information
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_role = db.Column(db.String(20))

    # Location data (for future AI route optimization)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    location_description = db.Column(db.String(200))

    # Timing data (critical for AI analysis)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    duration_from_previous = db.Column(db.Integer)  # Seconds since last event

    # Additional metadata for AI training
    event_metadata = db.Column(db.JSON)  # Flexible JSON field for future data

    def __repr__(self):
        return f'<DeliveryLog Order#{self.order_id} - {self.event_type}>'


class SavedCustomer(db.Model):
    """Saved customer addresses for quick order creation"""
    __tablename__ = 'saved_customers'

    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    customer_name = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    delivery_address = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<SavedCustomer {self.customer_name}>'


class AIStatisticsSummary(db.Model):
    """Cache for AI-generated statistics summaries"""
    __tablename__ = 'ai_statistics_summaries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # NULL for admin/system summaries
    summary_type = db.Column(db.String(50), nullable=False)  # 'courier_daily', 'restaurant_weekly', 'admin_system'
    summary_text = db.Column(db.Text, nullable=False)  # AI generated text
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    stats_data = db.Column(db.JSON)  # Raw data used for AI generation (for debugging/re-generation)

    # Relationship to user (optional)
    user = db.relationship('User', backref='ai_summaries', lazy=True)

    def __repr__(self):
        return f'<AIStatisticsSummary {self.summary_type} - {self.generated_at}>'


class Notification(db.Model):
    """In-app notifications for users"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'link': self.link,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<Notification {self.type} for user {self.user_id}>'
