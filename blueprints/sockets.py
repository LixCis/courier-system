"""WebSocket event handlers (bound to shared socketio instance)."""
from flask_login import current_user
from flask_socketio import emit, join_room, leave_room

from models import db, Order, Notification
from extensions import socketio, init_socketio_service


@socketio.on('connect')
def handle_connect():
    if not current_user.is_authenticated:
        return False

    if current_user.role == 'admin':
        join_room('admin')
        join_room(f'admin_{current_user.id}')
    else:
        join_room(f'{current_user.role}_{current_user.id}')

    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    recent = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(20).all()

    emit('dashboard:data', {
        'unread_notifications_count': unread_count,
        'recent_notifications': [n.to_dict() for n in recent],
    })


@socketio.on('disconnect')
def handle_disconnect():
    pass


@socketio.on('order:join')
def handle_order_join(data):
    if not current_user.is_authenticated:
        return

    order_id = data.get('order_id')
    if not order_id:
        return

    order = db.session.get(Order, order_id)
    if not order:
        return

    if (current_user.role == 'admin'
            or (current_user.role == 'restaurant' and order.restaurant_id == current_user.id)
            or (current_user.role == 'courier' and order.courier_id == current_user.id)):
        join_room(f'order_{order_id}')


@socketio.on('order:leave')
def handle_order_leave(data):
    order_id = data.get('order_id')
    if order_id:
        leave_room(f'order_{order_id}')


@socketio.on('notification:mark_read')
def handle_mark_read(data):
    if not current_user.is_authenticated:
        return
    notification_id = data.get('notification_id')
    notification = db.session.get(Notification, notification_id)
    if notification and notification.user_id == current_user.id:
        notification.is_read = True
        db.session.commit()


@socketio.on('notification:mark_all_read')
def handle_mark_all_read(data):
    if not current_user.is_authenticated:
        return
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()


@socketio.on('courier:update_location')
def handle_courier_location(data):
    if not current_user.is_authenticated or current_user.role != 'courier':
        return
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    location_description = data.get('location_description', '')

    if latitude is not None and longitude is not None:
        current_user.last_known_latitude = float(latitude)
        current_user.last_known_longitude = float(longitude)
        if location_description:
            current_user.current_location = location_description
        db.session.commit()
        init_socketio_service().emit_courier_location(current_user)
