"""
SocketIO Service

Centralized WebSocket event emission and notification creation.
All state-changing routes call this service instead of emitting directly.
"""

from models import db, Notification, Order, User
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SocketIOService:
    def __init__(self, socketio):
        self.socketio = socketio

    def _create_notification(self, user_id, type, title, message, link=None):
        """Create a notification in DB and emit via WebSocket."""
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            link=link,
            created_at=utcnow()
        )
        db.session.add(notification)
        db.session.commit()

        # Emit to user's personal room
        user = db.session.get(User, user_id)
        if user:
            room = f"{user.role}_{user.id}"
            self.socketio.emit('notification:new', notification.to_dict(), room=room, namespace='/')

        return notification

    def _get_admin_ids(self):
        """Get all admin user IDs."""
        return [u.id for u in User.query.filter_by(role='admin', is_active=True).all()]

    def emit_order_created(self, order):
        """Emit when a new order is created."""
        payload = {
            'order_id': order.id,
            'order_number': order.order_number,
            'restaurant_name': order.restaurant_name,
            'customer_name': order.customer_name,
            'delivery_address': order.delivery_address,
            'status': order.status,
            'created_at': order.created_at.isoformat(),
            'order_value': order.order_value,
            'pickup_latitude': order.pickup_latitude,
            'pickup_longitude': order.pickup_longitude,
            'delivery_latitude': order.delivery_latitude,
            'delivery_longitude': order.delivery_longitude
        }

        self.socketio.emit('order:created', payload, room='admin', namespace='/')
        self.socketio.emit('order:created', payload, room=f'restaurant_{order.restaurant_id}', namespace='/')

        # Notifications for admins
        for admin_id in self._get_admin_ids():
            self._create_notification(
                admin_id, 'order_created',
                f'New order #{order.order_number}',
                f'Restaurant {order.restaurant_name} created an order for {order.customer_name}',
                f'/admin/order/{order.id}'
            )

    def emit_order_assigned(self, order):
        """Emit when a courier is assigned to an order."""
        courier = db.session.get(User, order.courier_id)
        courier_name = courier.full_name if courier else 'Unknown'
        vehicle = courier.vehicle_type if courier else ''

        payload = {
            'order_id': order.id,
            'order_number': order.order_number,
            'courier_id': order.courier_id,
            'courier_name': courier_name,
            'estimated_pickup': order.estimated_pickup_time,
            'estimated_delivery': order.estimated_delivery_time,
            'estimated_total': order.estimated_total_time
        }

        self.socketio.emit('order:assigned', payload, room='admin', namespace='/')
        self.socketio.emit('order:assigned', payload, room=f'restaurant_{order.restaurant_id}', namespace='/')
        self.socketio.emit('order:assigned', payload, room=f'courier_{order.courier_id}', namespace='/')
        self.socketio.emit('order:assigned', payload, room=f'order_{order.id}', namespace='/')

        # Notification for courier
        self._create_notification(
            order.courier_id, 'order_assigned',
            f'New order #{order.order_number}',
            f'Pick up from {order.restaurant_name}, deliver to {order.delivery_address}',
            f'/courier/order/{order.id}'
        )

        # Notification for restaurant
        self._create_notification(
            order.restaurant_id, 'order_assigned',
            f'Courier assigned to #{order.order_number}',
            f'Courier {courier_name} ({vehicle}) will pick up the order',
            f'/restaurant/order/{order.id}'
        )

    def emit_order_status_changed(self, order, old_status, new_status):
        """Emit when order status changes."""
        courier = db.session.get(User, order.courier_id) if order.courier_id else None
        courier_name = courier.full_name if courier else ''

        payload = {
            'order_id': order.id,
            'order_number': order.order_number,
            'old_status': old_status,
            'new_status': new_status,
            'timestamp': utcnow().isoformat()
        }

        self.socketio.emit('order:status_changed', payload, room='admin', namespace='/')
        self.socketio.emit('order:status_changed', payload, room=f'restaurant_{order.restaurant_id}', namespace='/')
        if order.courier_id:
            self.socketio.emit('order:status_changed', payload, room=f'courier_{order.courier_id}', namespace='/')
        self.socketio.emit('order:status_changed', payload, room=f'order_{order.id}', namespace='/')

        # Notifications based on status
        if new_status == 'picked_up':
            self._create_notification(
                order.restaurant_id, 'order_status_changed',
                f'Order #{order.order_number} picked up',
                f'Courier {courier_name} picked up the order',
                f'/restaurant/order/{order.id}'
            )
        elif new_status == 'delivered':
            self._create_notification(
                order.restaurant_id, 'order_status_changed',
                f'Order #{order.order_number} delivered',
                f'Order successfully delivered to the customer',
                f'/restaurant/order/{order.id}'
            )
            for admin_id in self._get_admin_ids():
                self._create_notification(
                    admin_id, 'order_status_changed',
                    f'Order #{order.order_number} delivered',
                    f'Delivered by courier {courier_name}',
                    f'/admin/order/{order.id}'
                )

    def emit_order_cancelled(self, order):
        """Emit when an order is cancelled."""
        payload = {
            'order_id': order.id,
            'order_number': order.order_number,
            'cancelled_by': order.restaurant_name
        }

        self.socketio.emit('order:cancelled', payload, room='admin', namespace='/')
        self.socketio.emit('order:cancelled', payload, room=f'restaurant_{order.restaurant_id}', namespace='/')
        self.socketio.emit('order:cancelled', payload, room=f'order_{order.id}', namespace='/')

        if order.courier_id:
            self.socketio.emit('order:cancelled', payload, room=f'courier_{order.courier_id}', namespace='/')
            self._create_notification(
                order.courier_id, 'order_cancelled',
                f'Order #{order.order_number} cancelled',
                f'Restaurant {order.restaurant_name} cancelled the order',
                f'/courier/order/{order.id}'
            )

    def emit_order_rejected(self, order, courier_id, courier_name):
        """Emit when a courier rejects an order."""
        payload = {
            'order_id': order.id,
            'order_number': order.order_number,
            'courier_id': courier_id,
            'courier_name': courier_name
        }

        self.socketio.emit('order:rejected', payload, room='admin', namespace='/')
        self.socketio.emit('order:rejected', payload, room=f'restaurant_{order.restaurant_id}', namespace='/')
        self.socketio.emit('order:rejected', payload, room=f'order_{order.id}', namespace='/')

        for admin_id in self._get_admin_ids():
            self._create_notification(
                admin_id, 'order_rejected',
                f'Order #{order.order_number} rejected',
                f'Courier {courier_name} rejected the order',
                f'/admin/order/{order.id}'
            )
        self._create_notification(
            order.restaurant_id, 'order_rejected',
            f'Order #{order.order_number} rejected by courier',
            f'Looking for a new courier...',
            f'/restaurant/order/{order.id}'
        )

    def emit_courier_location(self, courier):
        """Emit when courier updates their location."""
        payload = {
            'courier_id': courier.id,
            'courier_name': courier.full_name,
            'latitude': courier.last_known_latitude,
            'longitude': courier.last_known_longitude,
            'location_description': courier.current_location
        }

        self.socketio.emit('courier:location_updated', payload, room='admin', namespace='/')

        # Also emit to all active order rooms for this courier
        active_orders = Order.query.filter_by(courier_id=courier.id).filter(
            Order.status.in_(['assigned', 'picked_up', 'in_transit'])
        ).all()
        for order in active_orders:
            self.socketio.emit('courier:location_updated', payload, room=f'order_{order.id}', namespace='/')

    def emit_courier_availability(self, courier):
        """Emit when courier availability changes."""
        payload = {
            'courier_id': courier.id,
            'courier_name': courier.full_name,
            'is_available': courier.is_available,
            'pending_unavailable': courier.pending_unavailable
        }
        self.socketio.emit('courier:availability_changed', payload, room='admin', namespace='/')

    def emit_ai_description_ready(self, order):
        """Emit when AI description is ready for an order."""
        payload = {
            'order_id': order.id,
            'ai_enhanced_description': order.ai_enhanced_description
        }
        self.socketio.emit('ai:description_ready', payload, room=f'restaurant_{order.restaurant_id}', namespace='/')
        self.socketio.emit('ai:description_ready', payload, room=f'order_{order.id}', namespace='/')

    def emit_ai_insights_ready(self, user_id, summary_type, summary_text):
        """Emit when AI insights are ready."""
        payload = {
            'user_id': user_id,
            'summary_type': summary_type,
            'summary_text': summary_text
        }
        if user_id:
            user = db.session.get(User, user_id)
            if user:
                self.socketio.emit('ai:insights_ready', payload, room=f'{user.role}_{user.id}', namespace='/')
        else:
            # Admin system summary
            self.socketio.emit('ai:insights_ready', payload, room='admin', namespace='/')
