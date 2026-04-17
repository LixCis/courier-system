# WebSocket, Mapy & Notifikace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all AJAX polling with Flask-SocketIO WebSockets, add Leaflet.js map visualization with OSRM routing, and implement an in-app notification system with a bell icon in the header.

**Architecture:** Flask-SocketIO event-driven communication using role-based rooms (admin, restaurant_{id}, courier_{id}, order_{id}). A centralized `SocketIOService` handles all event emission and notification creation. Leaflet.js maps display courier positions, order markers, and OSRM driving routes. The notification system persists to a new `Notification` DB model and delivers in real-time via WebSocket.

**Tech Stack:** Flask-SocketIO 5.x, gevent, Leaflet.js 1.9.4, OSRM (free routing API), Socket.IO client 4.7.x

**Spec:** `docs/superpowers/specs/2026-04-05-realtime-maps-notifications-design.md`

---

## File Structure

### New files:
```
services/socketio_service.py    — Centralized WebSocket event emission + notification creation
static/js/socket_base.js        — SocketIO client connection, reconnect, notification bell logic
static/js/map_utils.js           — Leaflet map initialization, marker management, OSRM routing
```

### Deleted files:
```
static/js/auto-refresh.js
static/js/dashboard-updater.js
static/js/order-detail-polling.js
static/js/order-detail-updater.js
static/js/page-refresh-polling.js
```

### Modified files:
```
requirements.txt                          — Add flask-socketio, gevent dependencies
models.py                                 — Add Notification model
app.py                                    — SocketIO init, connect/disconnect handlers, emit calls
                                            in all state-changing routes, remove /api/* endpoints,
                                            add GET /notifications endpoint
services/geocoding_service.py             — Add reverse_geocode() method
services/order_scheduler.py               — Add emit after auto-assign
templates/base.html                       — Add CDN scripts, notification bell, socket_base.js
templates/admin/dashboard.html            — Add overview map, replace polling with SocketIO handlers
templates/admin/view_order.html           — Add route map, SocketIO handlers
templates/courier/dashboard.html          — Add delivery map, SocketIO handlers
templates/courier/view_order.html         — Add route map, SocketIO handlers
templates/courier/update_location.html    — Add SocketIO emit after location update
templates/restaurant/dashboard.html       — Replace polling with SocketIO handlers
templates/restaurant/view_order.html      — Add route map, SocketIO handlers
templates/restaurant/create_order.html    — Map already exists via location_map component, no changes needed
setup.py                                  — Change app.run() to socketio.run()
```

---

## Task 1: Dependencies and Notification Model

**Files:**
- Modify: `requirements.txt`
- Modify: `models.py` (add after line 174, before the closing of file)

- [ ] **Step 1: Add dependencies to requirements.txt**

Add these lines at the end of `requirements.txt`:

```
# WebSocket real-time communication
flask-socketio==5.3.6
gevent==24.2.1
gevent-websocket==0.10.1
```

- [ ] **Step 2: Add Notification model to models.py**

Add after the `AIStatisticsSummary` class (after line 174) in `models.py`:

```python


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
```

- [ ] **Step 3: Install dependencies**

Run:
```bash
pip install flask-socketio==5.3.6 gevent==24.2.1 gevent-websocket==0.10.1
```

- [ ] **Step 4: Verify models load correctly**

Run:
```bash
python -c "from models import Notification; print('Notification model OK')"
```
Expected: `Notification model OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt models.py
git commit -m "feat: add Notification model and WebSocket dependencies"
```

---

## Task 2: SocketIO Service

**Files:**
- Create: `services/socketio_service.py`

- [ ] **Step 1: Create services/socketio_service.py**

```python
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
        db.session.flush()

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
                f'Nova objednavka #{order.order_number}',
                f'Restaurace {order.restaurant_name} vytvorila objednavku pro {order.customer_name}',
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
            f'Nova objednavka #{order.order_number}',
            f'Objednavka k vyzvednuti z {order.restaurant_name}, dorucit na {order.delivery_address}',
            f'/courier/order/{order.id}'
        )

        # Notification for restaurant
        self._create_notification(
            order.restaurant_id, 'order_assigned',
            f'Kuryr prirazen k #{order.order_number}',
            f'Kuryr {courier_name} ({vehicle}) vyzvedne objednavku',
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
                f'Objednavka #{order.order_number} vyzvednuta',
                f'Kuryr {courier_name} vyzvednul objednavku',
                f'/restaurant/order/{order.id}'
            )
        elif new_status == 'delivered':
            self._create_notification(
                order.restaurant_id, 'order_status_changed',
                f'Objednavka #{order.order_number} dorucena',
                f'Objednavka uspesne dorucena zakaznikovi',
                f'/restaurant/order/{order.id}'
            )
            for admin_id in self._get_admin_ids():
                self._create_notification(
                    admin_id, 'order_status_changed',
                    f'Objednavka #{order.order_number} dorucena',
                    f'Dorucena kuryrem {courier_name}',
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
                f'Objednavka #{order.order_number} zrusena',
                f'Restaurace {order.restaurant_name} zrusila objednavku',
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
                f'Objednavka #{order.order_number} odmitnuta',
                f'Kuryr {courier_name} odmitl objednavku',
                f'/admin/order/{order.id}'
            )
        self._create_notification(
            order.restaurant_id, 'order_rejected',
            f'Objednavka #{order.order_number} odmitnuta kuryrem',
            f'Hleda se novy kuryr...',
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
```

- [ ] **Step 2: Verify the service file loads**

Run:
```bash
python -c "from services.socketio_service import SocketIOService; print('SocketIOService OK')"
```
Expected: `SocketIOService OK`

- [ ] **Step 3: Commit**

```bash
git add services/socketio_service.py
git commit -m "feat: add centralized SocketIO service for event emission"
```

---

## Task 3: Initialize SocketIO in app.py and Add Connect/Disconnect Handlers

**Files:**
- Modify: `app.py` (lines 1-42 for imports/init, end of file for `__main__`)

- [ ] **Step 1: Add SocketIO import and initialization**

In `app.py`, after line 10 (`from werkzeug.utils import secure_filename`), add:

```python
from flask_socketio import SocketIO, emit, join_room, leave_room
```

After line 33 (`db.init_app(app)`) and before the login_manager setup (line 34), add:

```python
# Initialize SocketIO
socketio = SocketIO(app, manage_session=False, async_mode='gevent', cors_allowed_origins="*")
```

After the scheduler initialization (after line 41 `scheduler = init_scheduler(app)`), add:

```python
# Initialize SocketIO service
from services.socketio_service import SocketIOService
socketio_service = SocketIOService(socketio)
```

- [ ] **Step 2: Add WebSocket connect/disconnect handlers**

Add before the `# ==================== Authentication Routes ====================` comment (before line 196), a new section:

```python
# ==================== WebSocket Handlers ====================

@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection - join role-based rooms."""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return False  # Reject connection

    # Join role-based room
    if current_user.role == 'admin':
        join_room('admin')
    else:
        join_room(f'{current_user.role}_{current_user.id}')

    # Send initial notification data
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    recent = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(20).all()

    emit('dashboard:data', {
        'unread_notifications_count': unread_count,
        'recent_notifications': [n.to_dict() for n in recent]
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection."""
    pass  # Rooms are automatically cleaned up


@socketio.on('order:join')
def handle_order_join(data):
    """Join an order-specific room for real-time updates."""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return

    order_id = data.get('order_id')
    if not order_id:
        return

    # Verify permission
    order = db.session.get(Order, order_id)
    if not order:
        return

    if current_user.role == 'admin':
        join_room(f'order_{order_id}')
    elif current_user.role == 'restaurant' and order.restaurant_id == current_user.id:
        join_room(f'order_{order_id}')
    elif current_user.role == 'courier' and order.courier_id == current_user.id:
        join_room(f'order_{order_id}')


@socketio.on('order:leave')
def handle_order_leave(data):
    """Leave an order-specific room."""
    order_id = data.get('order_id')
    if order_id:
        leave_room(f'order_{order_id}')


@socketio.on('notification:mark_read')
def handle_mark_read(data):
    """Mark a single notification as read."""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return

    notification_id = data.get('notification_id')
    notification = db.session.get(Notification, notification_id)
    if notification and notification.user_id == current_user.id:
        notification.is_read = True
        db.session.commit()


@socketio.on('notification:mark_all_read')
def handle_mark_all_read(data):
    """Mark all notifications as read for the current user."""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return

    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()


@socketio.on('courier:update_location')
def handle_courier_location(data):
    """Handle courier location update via WebSocket."""
    from flask_login import current_user
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

        socketio_service.emit_courier_location(current_user)
```

- [ ] **Step 3: Update the Notification import at the top of app.py**

Change line 5:
```python
from models import db, User, Order, DeliveryLog, SavedCustomer
```
to:
```python
from models import db, User, Order, DeliveryLog, SavedCustomer, Notification
```

- [ ] **Step 4: Change server startup at end of app.py**

Change line 2074-2075:
```python
if __name__ == '__main__':
    app.run(debug=True, port=5000)
```
to:
```python
if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
```

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: initialize SocketIO with connect/disconnect and WebSocket handlers"
```

---

## Task 4: Wire SocketIO Emits Into All State-Changing Routes

**Files:**
- Modify: `app.py` (multiple route functions)

This task adds `socketio_service.emit_*()` calls after each state change in the existing routes.

- [ ] **Step 1: restaurant_create_order (around line 833)**

After `db.session.commit()` (line 833) and before the AI background thread start (line 836), add:

```python
        # Emit WebSocket event
        socketio_service.emit_order_created(order)
```

After the auto-assign block (after line 846 `success, message, courier = default_assignment_service.auto_assign_order(order)`), inside the `if success:` block (after line 848), add:

```python
            socketio_service.emit_order_assigned(order)
```

- [ ] **Step 2: restaurant_cancel_order (around line 1040)**

After `db.session.commit()` (line 1040), before the flash message (line 1042), add:

```python
    socketio_service.emit_order_cancelled(order)
```

- [ ] **Step 3: restaurant_update_order_status (around line 1079)**

After `db.session.commit()` (line 1079), add:

```python
    socketio_service.emit_order_status_changed(order, old_status, new_status)
```

- [ ] **Step 4: courier_toggle_availability (around line 1124 and 1132)**

After `db.session.commit()` on line 1124 (pending_unavailable path), add:

```python
        socketio_service.emit_courier_availability(current_user)
```

After `db.session.commit()` on line 1132 (normal toggle path), add:

```python
    socketio_service.emit_courier_availability(current_user)
```

- [ ] **Step 5: courier_update_location (around line 1151)**

After `db.session.commit()` (line 1151), add:

```python
        socketio_service.emit_courier_location(current_user)
```

- [ ] **Step 6: courier_reject_order (around line 1268)**

After `db.session.commit()` (line 1268), add:

```python
    socketio_service.emit_order_rejected(order, current_user.id, current_user.full_name)
```

After the auto-reassign success block (after line 1276 `if success:`), add inside it:

```python
        socketio_service.emit_order_assigned(order)
```

- [ ] **Step 7: courier_update_order_status (around line 1406)**

After `db.session.commit()` (line 1406), add:

```python
    socketio_service.emit_order_status_changed(order, old_status, new_status)
    if new_status == 'delivered':
        socketio_service.emit_courier_availability(current_user)
```

- [ ] **Step 8: admin_toggle_courier_availability (around line 560)**

After `db.session.commit()` (line 560), add:

```python
    socketio_service.emit_courier_availability(courier)
```

- [ ] **Step 9: enhance_in_background (around line 127)**

After `db.session.commit()` (line 127), add:

```python
                    socketio_service.emit_ai_description_ready(order_to_update)
```

Note: This function runs in a background thread. Flask-SocketIO supports emitting from background threads when using `socketio.emit()` which `SocketIOService` does internally.

- [ ] **Step 10: Commit**

```bash
git add app.py
git commit -m "feat: wire SocketIO emits into all state-changing routes"
```

---

## Task 5: Wire SocketIO Into Order Scheduler

**Files:**
- Modify: `services/order_scheduler.py`

- [ ] **Step 1: Add SocketIO emit after auto-assignment**

In `order_scheduler.py`, modify the `assign_pending_orders` method. After line 68 (`print(f"✓ Order {order.order_number} assigned to {courier.full_name}")`), add:

```python
                        # Emit WebSocket event
                        try:
                            from services.socketio_service import SocketIOService
                            # Get the global socketio_service from app module
                            import app as app_module
                            if hasattr(app_module, 'socketio_service'):
                                app_module.socketio_service.emit_order_assigned(order)
                        except Exception as e:
                            print(f"[SocketIO] Error emitting order:assigned from scheduler: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add services/order_scheduler.py
git commit -m "feat: emit WebSocket events from order auto-assignment scheduler"
```

---

## Task 6: Remove All AJAX Polling Endpoints and JS Files

**Files:**
- Modify: `app.py` (remove lines ~1515-1810)
- Delete: `static/js/auto-refresh.js`
- Delete: `static/js/dashboard-updater.js`
- Delete: `static/js/order-detail-polling.js`
- Delete: `static/js/order-detail-updater.js`
- Delete: `static/js/page-refresh-polling.js`

- [ ] **Step 1: Remove all /api/* polling endpoints from app.py**

Delete the entire section from line 1515 (`# ==================== API Routes (for AJAX polling) ====================`) through line 1810 (end of `api_get_ai_description`). This removes these 11 endpoints:

- `/api/admin/dashboard-data`
- `/api/admin/order/<id>`
- `/api/admin/ai-insights`
- `/api/restaurant/dashboard-data`
- `/api/restaurant/order/<id>`
- `/api/restaurant/ai-insights`
- `/api/courier/dashboard-data`
- `/api/courier/order/<id>`
- `/api/courier/ai-insights`
- `/api/order/<id>/ai-description`

**IMPORTANT:** Keep the `/api/admin/ai-insights`, `/api/restaurant/ai-insights`, and `/api/courier/ai-insights` endpoints. Actually, per the spec these should be removed and replaced by the `ai:insights_ready` WebSocket event. However, the AI insights loading pattern (polling for cache readiness) currently happens only on statistics pages, NOT on dashboards. To avoid complexity, convert these 3 endpoints to use simple HTTP GET (they already are) and keep them for now since the statistics pages don't use WebSocket-based loading. Only remove the 8 dashboard/order polling endpoints.

Revised: Remove these 8 endpoints:
- `/api/admin/dashboard-data` (lines 1517-1567)
- `/api/admin/order/<id>` (lines 1570-1611)
- `/api/restaurant/dashboard-data` (lines 1614-1653)
- `/api/restaurant/order/<id>` (lines 1656-1702)
- `/api/courier/dashboard-data` (lines 1705-1741)
- `/api/courier/order/<id>` (lines 1744-1789)
- `/api/order/<id>/ai-description` (lines 1792-1810)

Keep the 3 AI insights endpoints as-is.

- [ ] **Step 2: Delete the 5 polling JavaScript files**

```bash
rm static/js/auto-refresh.js
rm static/js/dashboard-updater.js
rm static/js/order-detail-polling.js
rm static/js/order-detail-updater.js
rm static/js/page-refresh-polling.js
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove AJAX polling endpoints and JS files"
```

---

## Task 7: Add Notifications HTTP Endpoint

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add GET /notifications route**

Add before the error handlers section (`# ==================== Error Handlers ====================`):

```python
# ==================== Notifications ====================

@app.route('/notifications')
@login_required
def notifications_page():
    """View all notifications with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    pagination = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    return render_template('notifications.html', pagination=pagination)
```

- [ ] **Step 2: Create templates/notifications.html**

Create `templates/notifications.html`:

```html
{% extends "base.html" %}

{% block title %}Notifikace - Courier System{% endblock %}

{% block content %}
<div class="py-6">
    <div class="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
        <h1 class="text-2xl font-semibold text-gray-900 mb-6">Vsechny notifikace</h1>

        {% if pagination.items %}
        <div class="space-y-2">
            {% for n in pagination.items %}
            <a href="{{ n.link or '#' }}" class="block p-4 rounded-lg border {% if not n.is_read %}bg-blue-50 border-blue-200{% else %}bg-white border-gray-200{% endif %} hover:shadow-md transition-shadow">
                <div class="flex justify-between items-start">
                    <div>
                        <p class="font-medium text-gray-900">{{ n.title }}</p>
                        <p class="text-sm text-gray-600 mt-1">{{ n.message }}</p>
                    </div>
                    <span class="text-xs text-gray-400 whitespace-nowrap ml-4">{{ n.created_at.strftime('%d.%m. %H:%M') }}</span>
                </div>
            </a>
            {% endfor %}
        </div>

        <!-- Pagination -->
        {% if pagination.pages > 1 %}
        <nav class="mt-6 flex justify-center">
            <ul class="flex space-x-1">
                {% for p in pagination.iter_pages(left_edge=1, right_edge=1, left_current=2, right_current=2) %}
                    {% if p %}
                        <li>
                            <a href="{{ url_for('notifications_page', page=p) }}"
                               class="px-3 py-2 rounded-md text-sm {% if p == pagination.page %}bg-blue-600 text-white{% else %}bg-white text-gray-700 hover:bg-gray-50 border{% endif %}">
                                {{ p }}
                            </a>
                        </li>
                    {% else %}
                        <li><span class="px-2 py-2 text-gray-400">...</span></li>
                    {% endif %}
                {% endfor %}
            </ul>
        </nav>
        {% endif %}

        {% else %}
        <div class="text-center py-12 text-gray-500">
            <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
            <p class="mt-2">Zadne notifikace</p>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add app.py templates/notifications.html
git commit -m "feat: add notifications page with pagination"
```

---

## Task 8: Frontend — socket_base.js (SocketIO Client + Notification Bell)

**Files:**
- Create: `static/js/socket_base.js`

- [ ] **Step 1: Create static/js/socket_base.js**

```javascript
/**
 * Socket Base - SocketIO client connection, reconnect logic, and notification bell.
 * Included on every page via base.html.
 */

// Connect to SocketIO
const socket = io({
    transports: ['websocket', 'polling']
});

// --- Connection status indicator ---
socket.on('connect', () => {
    const indicator = document.getElementById('connection-status');
    if (indicator) indicator.classList.add('hidden');
});

socket.on('disconnect', () => {
    const indicator = document.getElementById('connection-status');
    if (indicator) indicator.classList.remove('hidden');
});

// --- Notification Bell ---
let notifications = [];
let unreadCount = 0;

// Initial data from server on connect
socket.on('dashboard:data', (data) => {
    if (data.recent_notifications) {
        notifications = data.recent_notifications;
        renderNotifications();
    }
    if (data.unread_notifications_count !== undefined) {
        unreadCount = data.unread_notifications_count;
        updateBadge();
    }
});

// New notification arrives
socket.on('notification:new', (data) => {
    notifications.unshift(data);
    if (notifications.length > 20) notifications.pop();
    unreadCount++;
    updateBadge();
    renderNotifications();
    showToast(data);
});

function updateBadge() {
    const badge = document.getElementById('notification-badge');
    if (!badge) return;
    if (unreadCount > 0) {
        badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function renderNotifications() {
    const list = document.getElementById('notification-list');
    const empty = document.getElementById('notification-empty');
    if (!list) return;

    if (notifications.length === 0) {
        list.innerHTML = '';
        if (empty) empty.classList.remove('hidden');
        return;
    }

    if (empty) empty.classList.add('hidden');
    list.innerHTML = notifications.map(n => `
        <a href="${n.link || '#'}"
           class="block px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${n.is_read ? '' : 'bg-blue-50'}"
           onclick="markRead(${n.id})">
            <p class="text-sm font-medium text-gray-900">${escapeHtml(n.title)}</p>
            <p class="text-xs text-gray-500 mt-1">${escapeHtml(n.message)}</p>
            <p class="text-xs text-gray-400 mt-1">${formatTime(n.created_at)}</p>
        </a>
    `).join('');
}

function markRead(id) {
    socket.emit('notification:mark_read', { notification_id: id });
    const n = notifications.find(n => n.id === id);
    if (n && !n.is_read) {
        n.is_read = true;
        unreadCount = Math.max(0, unreadCount - 1);
        updateBadge();
    }
}

function markAllRead() {
    socket.emit('notification:mark_all_read', {});
    notifications.forEach(n => n.is_read = true);
    unreadCount = 0;
    updateBadge();
    renderNotifications();
}

function showToast(notification) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'bg-white border border-gray-200 rounded-lg shadow-lg p-4 mb-2 max-w-sm animate-slide-in';
    toast.innerHTML = `
        <p class="text-sm font-medium text-gray-900">${escapeHtml(notification.title)}</p>
        <p class="text-xs text-gray-500 mt-1">${escapeHtml(notification.message)}</p>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// --- Notification dropdown toggle ---
document.addEventListener('DOMContentLoaded', () => {
    const bell = document.getElementById('notification-bell');
    const dropdown = document.getElementById('notification-dropdown');

    if (bell && dropdown) {
        bell.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('hidden');
        });

        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !bell.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });
    }

    const markAllBtn = document.getElementById('mark-all-read');
    if (markAllBtn) {
        markAllBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            markAllRead();
        });
    }
});

// --- Utilities ---
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);

    if (diffMin < 1) return 'Prave ted';
    if (diffMin < 60) return `Pred ${diffMin} min`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `Pred ${diffHours} hod`;
    return date.toLocaleDateString('cs-CZ', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
}
```

- [ ] **Step 2: Commit**

```bash
git add static/js/socket_base.js
git commit -m "feat: add SocketIO client with notification bell logic"
```

---

## Task 9: Frontend — map_utils.js (Leaflet Maps, Markers, OSRM Routing)

**Files:**
- Create: `static/js/map_utils.js`

- [ ] **Step 1: Create static/js/map_utils.js**

```javascript
/**
 * Map Utilities - Leaflet map initialization, marker management, and OSRM routing.
 * Included on every page via base.html. Functions are called by page-specific scripts.
 */

// Ostrava center coordinates
const OSTRAVA_CENTER = [49.8209, 18.2625];
const DEFAULT_ZOOM = 13;

// Custom marker icons using Leaflet divIcon (no external images needed)
function createIcon(color, label) {
    return L.divIcon({
        className: 'custom-marker',
        html: `<div style="
            background-color: ${color};
            width: 28px; height: 28px;
            border-radius: 50%;
            border: 3px solid white;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            display: flex; align-items: center; justify-content: center;
            color: white; font-size: 12px; font-weight: bold;
        ">${label || ''}</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -16]
    });
}

const ICONS = {
    courierAvailable: createIcon('#10b981', ''),      // green
    courierBusy: createIcon('#f59e0b', ''),            // orange
    courierUnavailable: createIcon('#9ca3af', ''),     // gray
    pickup: createIcon('#3b82f6', 'P'),                // blue with P
    delivery: createIcon('#ef4444', 'D'),              // red with D
    courierPosition: createIcon('#6366f1', 'C')        // indigo with C
};

function getCourierIcon(courier) {
    if (!courier.is_available) return ICONS.courierUnavailable;
    if (courier.active_orders_count > 0) return ICONS.courierBusy;
    return ICONS.courierAvailable;
}

/**
 * Initialize a Leaflet map in a container.
 * @param {string} containerId - DOM element ID
 * @param {object} options - { center, zoom, fitBounds }
 * @returns {L.Map}
 */
function initMap(containerId, options = {}) {
    const center = options.center || OSTRAVA_CENTER;
    const zoom = options.zoom || DEFAULT_ZOOM;

    const map = L.map(containerId).setView(center, zoom);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);

    return map;
}

/**
 * Draw a driving route between two points using OSRM.
 * @param {L.Map} map
 * @param {Array} start - [lat, lng]
 * @param {Array} end - [lat, lng]
 * @param {object} options - { color, weight, dashArray }
 * @returns {Promise<L.Polyline|null>}
 */
async function drawRoute(map, start, end, options = {}) {
    const color = options.color || '#3b82f6';
    const weight = options.weight || 4;

    try {
        const url = `https://router.project-osrm.org/route/v1/driving/${start[1]},${start[0]};${end[1]},${end[0]}?overview=full&geometries=geojson`;
        const response = await fetch(url);
        const data = await response.json();

        if (data.code === 'Ok' && data.routes.length > 0) {
            const coords = data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
            const polyline = L.polyline(coords, {
                color: color,
                weight: weight,
                opacity: 0.7,
                dashArray: options.dashArray || null
            }).addTo(map);
            return polyline;
        }
    } catch (e) {
        console.warn('OSRM routing failed, drawing straight line:', e);
    }

    // Fallback: straight line
    const polyline = L.polyline([start, end], {
        color: color,
        weight: weight,
        opacity: 0.5,
        dashArray: '10, 10'
    }).addTo(map);
    return polyline;
}

/**
 * Add order pickup + delivery markers and route to a map.
 * @param {L.Map} map
 * @param {object} order - { pickup_latitude, pickup_longitude, delivery_latitude, delivery_longitude, ... }
 * @returns {Promise<{pickupMarker, deliveryMarker, route}>}
 */
async function addOrderToMap(map, order) {
    const result = { pickupMarker: null, deliveryMarker: null, route: null };

    if (order.pickup_latitude && order.pickup_longitude) {
        result.pickupMarker = L.marker(
            [order.pickup_latitude, order.pickup_longitude],
            { icon: ICONS.pickup }
        ).addTo(map);
        result.pickupMarker.bindPopup(`<b>Vyzvednuti</b><br>${order.pickup_address || order.restaurant_name || ''}`);
    }

    if (order.delivery_latitude && order.delivery_longitude) {
        result.deliveryMarker = L.marker(
            [order.delivery_latitude, order.delivery_longitude],
            { icon: ICONS.delivery }
        ).addTo(map);
        result.deliveryMarker.bindPopup(`<b>Doruceni</b><br>${order.delivery_address || ''}<br>${order.customer_name || ''}`);
    }

    if (result.pickupMarker && result.deliveryMarker) {
        result.route = await drawRoute(
            map,
            [order.pickup_latitude, order.pickup_longitude],
            [order.delivery_latitude, order.delivery_longitude]
        );

        // Fit map to show both markers
        const bounds = L.latLngBounds(
            [order.pickup_latitude, order.pickup_longitude],
            [order.delivery_latitude, order.delivery_longitude]
        );
        map.fitBounds(bounds.pad(0.2));
    }

    return result;
}

/**
 * Fit map bounds to include all given markers.
 * @param {L.Map} map
 * @param {Array<L.Marker>} markers
 */
function fitMapToMarkers(map, markers) {
    const validMarkers = markers.filter(m => m !== null);
    if (validMarkers.length === 0) return;

    if (validMarkers.length === 1) {
        map.setView(validMarkers[0].getLatLng(), 15);
        return;
    }

    const group = L.featureGroup(validMarkers);
    map.fitBounds(group.getBounds().pad(0.15));
}
```

- [ ] **Step 2: Commit**

```bash
git add static/js/map_utils.js
git commit -m "feat: add Leaflet map utilities with OSRM routing"
```

---

## Task 10: Update base.html — CDN Scripts, Notification Bell, Connection Status

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 1: Add CDN scripts in `<head>`**

After line 7 (`<script src="https://cdn.tailwindcss.com"></script>`), add:

```html
    <!-- SocketIO client -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.4/socket.io.js"></script>
    <!-- Leaflet CSS + JS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

- [ ] **Step 2: Add toast animation CSS**

Inside the existing `<style>` block (after the `fadeIn` keyframes, around line 40), add:

```css
        /* Toast slide in */
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        .animate-slide-in {
            animation: slideIn 0.3s ease-out;
        }
```

- [ ] **Step 3: Add notification bell and connection indicator in the nav bar**

Replace the existing user info section (lines 108-119) which currently contains the user name, availability badge, and logout button. The current code:

```html
                    <div class="flex items-center">
                        <div class="flex-shrink-0 text-sm text-gray-700 mr-4">
                            <span class="font-medium">{{ current_user.full_name }}</span>
                            {% if current_user.role == 'courier' %}
                                <span class="ml-2 inline-flex items-center rounded-full px-2 py-1 text-xs font-medium {% if current_user.is_available %}bg-green-100 text-green-700{% else %}bg-gray-100 text-gray-700{% endif %}">
                                    {% if current_user.is_available %}Available{% else %}Unavailable{% endif %}
                                </span>
                            {% endif %}
                        </div>
                        <a href="{{ url_for('logout') }}" class="rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50">
                            Logout
                        </a>
                    </div>
```

Replace with:

```html
                    <div class="flex items-center space-x-4">
                        <!-- Connection status indicator -->
                        <div id="connection-status" class="hidden flex items-center text-xs text-red-500">
                            <span class="w-2 h-2 bg-red-500 rounded-full mr-1"></span>
                            Odpojeno
                        </div>

                        <!-- Notification bell -->
                        <div id="notification-bell" class="relative cursor-pointer p-1">
                            <svg class="h-6 w-6 text-gray-500 hover:text-gray-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                            </svg>
                            <span id="notification-badge" class="hidden absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">0</span>
                        </div>

                        <!-- Notification dropdown -->
                        <div id="notification-dropdown" class="hidden absolute right-16 top-14 w-80 bg-white rounded-lg shadow-xl border border-gray-200 max-h-96 overflow-y-auto z-50">
                            <div class="p-3 border-b flex justify-between items-center sticky top-0 bg-white">
                                <span class="font-semibold text-sm">Notifikace</span>
                                <div class="flex items-center space-x-3">
                                    <button id="mark-all-read" class="text-xs text-blue-600 hover:underline">Oznacit vse</button>
                                    <a href="{{ url_for('notifications_page') }}" class="text-xs text-gray-500 hover:underline">Vsechny</a>
                                </div>
                            </div>
                            <div id="notification-list"></div>
                            <div id="notification-empty" class="p-4 text-center text-gray-500 text-sm hidden">
                                Zadne notifikace
                            </div>
                        </div>

                        <!-- User info -->
                        <div class="flex-shrink-0 text-sm text-gray-700">
                            <span class="font-medium">{{ current_user.full_name }}</span>
                            {% if current_user.role == 'courier' %}
                                <span class="ml-2 inline-flex items-center rounded-full px-2 py-1 text-xs font-medium {% if current_user.is_available %}bg-green-100 text-green-700{% else %}bg-gray-100 text-gray-700{% endif %}">
                                    {% if current_user.is_available %}Available{% else %}Unavailable{% endif %}
                                </span>
                            {% endif %}
                        </div>
                        <a href="{{ url_for('logout') }}" class="rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50">
                            Logout
                        </a>
                    </div>
```

- [ ] **Step 4: Add toast container before closing `</body>`**

Before the footer (before line 148 `<footer>`), add:

```html
    <!-- Toast notifications container -->
    <div id="toast-container" class="fixed top-20 right-4 z-50 space-y-2"></div>
```

- [ ] **Step 5: Replace old JS includes with new ones**

Replace lines 156-159:

```html
    <!-- Auto-refresh system -->
    <script src="{{ url_for('static', filename='js/auto-refresh.js') }}"></script>
    <script src="{{ url_for('static', filename='js/dashboard-updater.js') }}"></script>
    <script src="{{ url_for('static', filename='js/order-detail-updater.js') }}"></script>
```

with:

```html
    <!-- SocketIO and map utilities -->
    {% if current_user.is_authenticated %}
    <script src="{{ url_for('static', filename='js/socket_base.js') }}"></script>
    <script src="{{ url_for('static', filename='js/map_utils.js') }}"></script>
    {% endif %}
```

- [ ] **Step 6: Commit**

```bash
git add templates/base.html
git commit -m "feat: update base template with SocketIO, Leaflet CDN, notification bell"
```

---

## Task 11: Admin Dashboard — SocketIO Handlers + Overview Map

**Files:**
- Modify: `templates/admin/dashboard.html`

- [ ] **Step 1: Add map container and SocketIO handlers**

At the end of the `admin/dashboard.html` template, inside a `{% block extra_js %}` block (create one if it doesn't exist), replace any existing polling JS and add:

First, add a map container div in the HTML body. After the statistics grid and before the orders table, add:

```html
        <!-- Live Map -->
        <div class="mt-8">
            <h2 class="text-lg font-medium text-gray-900 mb-4">Mapa - Kurýři a objednávky</h2>
            <div class="bg-white rounded-lg shadow overflow-hidden">
                <div id="admin-map" style="height: 450px; width: 100%;"></div>
                <div class="p-3 border-t flex space-x-4 text-sm">
                    <label class="flex items-center">
                        <input type="checkbox" id="show-couriers" checked class="mr-2"> Kurýři
                    </label>
                    <label class="flex items-center">
                        <input type="checkbox" id="show-orders" checked class="mr-2"> Objednávky
                    </label>
                    <span class="flex items-center"><span class="w-3 h-3 bg-green-500 rounded-full mr-1"></span> Dostupný</span>
                    <span class="flex items-center"><span class="w-3 h-3 bg-yellow-500 rounded-full mr-1"></span> Na cestě</span>
                    <span class="flex items-center"><span class="w-3 h-3 bg-gray-400 rounded-full mr-1"></span> Nedostupný</span>
                </div>
            </div>
        </div>
```

- [ ] **Step 2: Add the extra_js block with SocketIO handlers and map logic**

At the end of the template, add:

```html
{% block extra_js %}
<script>
(function() {
    // --- Map Setup ---
    const map = initMap('admin-map');
    const courierMarkers = {};  // courier_id -> L.Marker
    const orderLayers = {};     // order_id -> { pickupMarker, deliveryMarker, route }

    // Load initial courier positions
    const couriers = {{ couriers_json | safe }};
    couriers.forEach(c => {
        if (c.latitude && c.longitude) {
            const marker = L.marker([c.latitude, c.longitude], {
                icon: getCourierIcon(c)
            }).addTo(map);
            marker.bindPopup(`<b>${c.name}</b><br>${c.vehicle_type}<br>Aktivní: ${c.active_orders_count}`);
            courierMarkers[c.id] = marker;
        }
    });

    // Load initial active orders
    const orders = {{ active_orders_json | safe }};
    orders.forEach(async (order) => {
        orderLayers[order.id] = await addOrderToMap(map, order);
    });

    // Fit all markers
    const allMarkers = Object.values(courierMarkers);
    if (allMarkers.length > 0) fitMapToMarkers(map, allMarkers);

    // Filter checkboxes
    document.getElementById('show-couriers').addEventListener('change', function() {
        Object.values(courierMarkers).forEach(m => {
            if (this.checked) m.addTo(map); else map.removeLayer(m);
        });
    });
    document.getElementById('show-orders').addEventListener('change', function() {
        Object.values(orderLayers).forEach(layers => {
            ['pickupMarker', 'deliveryMarker', 'route'].forEach(key => {
                if (layers[key]) {
                    if (this.checked) layers[key].addTo(map); else map.removeLayer(layers[key]);
                }
            });
        });
    });

    // --- SocketIO Events ---
    socket.on('order:created', (data) => {
        // Update stats
        const totalEl = document.querySelector('[data-metric="total_orders"]');
        if (totalEl) totalEl.textContent = parseInt(totalEl.textContent) + 1;
        const pendingEl = document.querySelector('[data-metric="pending_orders"]');
        if (pendingEl) pendingEl.textContent = parseInt(pendingEl.textContent) + 1;

        // Add to map
        if (data.pickup_latitude && data.delivery_latitude) {
            addOrderToMap(map, data).then(layers => {
                orderLayers[data.order_id] = layers;
            });
        }
    });

    socket.on('order:status_changed', (data) => {
        // Update metric displays
        if (data.new_status === 'delivered' || data.new_status === 'cancelled') {
            // Remove from map
            const layers = orderLayers[data.order_id];
            if (layers) {
                ['pickupMarker', 'deliveryMarker', 'route'].forEach(key => {
                    if (layers[key]) map.removeLayer(layers[key]);
                });
                delete orderLayers[data.order_id];
            }
        }
    });

    socket.on('courier:location_updated', (data) => {
        if (courierMarkers[data.courier_id]) {
            courierMarkers[data.courier_id].setLatLng([data.latitude, data.longitude]);
        } else if (data.latitude && data.longitude) {
            const marker = L.marker([data.latitude, data.longitude], {
                icon: ICONS.courierBusy
            }).addTo(map);
            marker.bindPopup(`<b>${data.courier_name}</b>`);
            courierMarkers[data.courier_id] = marker;
        }
    });

    socket.on('courier:availability_changed', (data) => {
        if (courierMarkers[data.courier_id]) {
            courierMarkers[data.courier_id].setIcon(
                data.is_available ? ICONS.courierAvailable : ICONS.courierUnavailable
            );
        }
        // Update available couriers stat
        const availEl = document.querySelector('[data-metric="available_couriers"]');
        if (availEl) {
            const current = parseInt(availEl.textContent);
            availEl.textContent = data.is_available ? current + 1 : Math.max(0, current - 1);
        }
    });
})();
</script>
{% endblock %}
```

- [ ] **Step 3: Update admin_dashboard route to pass map data**

In `app.py`, in the `admin_dashboard()` function, before the `return render_template(...)`, add the map data. After the `logs_pagination` query (around line 289), add:

```python
    import json

    # Courier data for map
    all_couriers = User.query.filter_by(role='courier', is_active=True).all()
    couriers_json = json.dumps([{
        'id': c.id,
        'name': c.full_name,
        'latitude': c.last_known_latitude,
        'longitude': c.last_known_longitude,
        'is_available': c.is_available,
        'vehicle_type': c.vehicle_type or 'bike',
        'active_orders_count': Order.query.filter_by(courier_id=c.id).filter(
            Order.status.in_(['assigned', 'picked_up', 'in_transit'])
        ).count()
    } for c in all_couriers])

    # Active orders for map
    active_orders_list = Order.query.filter(
        Order.status.in_(['pending', 'assigned', 'picked_up', 'in_transit'])
    ).all()
    active_orders_json = json.dumps([{
        'id': o.id,
        'order_number': o.order_number,
        'restaurant_name': o.restaurant_name,
        'customer_name': o.customer_name,
        'status': o.status,
        'pickup_address': o.pickup_address,
        'delivery_address': o.delivery_address,
        'pickup_latitude': o.pickup_latitude,
        'pickup_longitude': o.pickup_longitude,
        'delivery_latitude': o.delivery_latitude,
        'delivery_longitude': o.delivery_longitude
    } for o in active_orders_list])
```

And add `couriers_json=couriers_json, active_orders_json=active_orders_json` to the `render_template` call.

- [ ] **Step 4: Remove any inline polling JS from admin dashboard template**

Search the admin/dashboard.html for any `setInterval`, `fetch('/api/`, or polling-related inline scripts and remove them.

- [ ] **Step 5: Commit**

```bash
git add templates/admin/dashboard.html app.py
git commit -m "feat: admin dashboard with live map and SocketIO event handlers"
```

---

## Task 12: Courier Dashboard — Map + SocketIO Handlers

**Files:**
- Modify: `templates/courier/dashboard.html`
- Modify: `app.py` (courier_dashboard route)

- [ ] **Step 1: Add map container to courier dashboard**

After the statistics grid in `courier/dashboard.html` (after the 3 stat cards), add:

```html
        <!-- Delivery Map -->
        <div class="mt-8">
            <h2 class="text-lg font-medium text-gray-900 mb-4">Mapa doručení</h2>
            <div class="bg-white rounded-lg shadow overflow-hidden">
                <div id="courier-map" style="height: 400px; width: 100%;"></div>
            </div>
            {% if not current_user.last_known_latitude %}
            <p class="mt-2 text-sm text-yellow-600">
                <a href="{{ url_for('courier_update_location') }}" class="underline">Aktualizujte svou polohu</a> pro zobrazení tras.
            </p>
            {% endif %}
        </div>
```

- [ ] **Step 2: Add extra_js block with map and SocketIO logic**

At the end of the template:

```html
{% block extra_js %}
<script>
(function() {
    const map = initMap('courier-map');
    const orderLayers = {};

    // Courier's own position
    const myLat = {{ current_user.last_known_latitude or 'null' }};
    const myLng = {{ current_user.last_known_longitude or 'null' }};
    let myMarker = null;

    if (myLat && myLng) {
        myMarker = L.marker([myLat, myLng], { icon: ICONS.courierPosition }).addTo(map);
        myMarker.bindPopup('<b>Vaše pozice</b>');
    }

    // Load active orders on map
    const orders = {{ active_orders_json | safe }};
    const allMarkers = myMarker ? [myMarker] : [];

    orders.forEach(async (order) => {
        const layers = await addOrderToMap(map, order);
        orderLayers[order.id] = layers;
        if (layers.pickupMarker) allMarkers.push(layers.pickupMarker);
        if (layers.deliveryMarker) allMarkers.push(layers.deliveryMarker);

        // Draw route from courier to pickup if courier has location
        if (myLat && myLng && order.pickup_latitude && order.pickup_longitude) {
            await drawRoute(map, [myLat, myLng], [order.pickup_latitude, order.pickup_longitude], {
                color: '#6366f1',
                dashArray: '8, 8'
            });
        }

        fitMapToMarkers(map, allMarkers);
    });

    if (allMarkers.length > 0) fitMapToMarkers(map, allMarkers);

    // SocketIO events
    socket.on('order:assigned', (data) => {
        // Reload page to pick up new order (simplest approach)
        window.location.reload();
    });

    socket.on('order:status_changed', (data) => {
        if (data.new_status === 'delivered' || data.new_status === 'cancelled') {
            const layers = orderLayers[data.order_id];
            if (layers) {
                ['pickupMarker', 'deliveryMarker', 'route'].forEach(key => {
                    if (layers[key]) map.removeLayer(layers[key]);
                });
                delete orderLayers[data.order_id];
            }
        }
    });

    socket.on('order:cancelled', (data) => {
        const layers = orderLayers[data.order_id];
        if (layers) {
            ['pickupMarker', 'deliveryMarker', 'route'].forEach(key => {
                if (layers[key]) map.removeLayer(layers[key]);
            });
            delete orderLayers[data.order_id];
        }
    });
})();
</script>
{% endblock %}
```

- [ ] **Step 3: Update courier_dashboard route to pass map data**

In `app.py`, in `courier_dashboard()`, before `return render_template(...)`, add:

```python
    import json
    active_orders_json = json.dumps([{
        'id': o.id,
        'order_number': o.order_number,
        'restaurant_name': o.restaurant_name,
        'customer_name': o.customer_name,
        'pickup_address': o.pickup_address,
        'delivery_address': o.delivery_address,
        'pickup_latitude': o.pickup_latitude,
        'pickup_longitude': o.pickup_longitude,
        'delivery_latitude': o.delivery_latitude,
        'delivery_longitude': o.delivery_longitude,
        'status': o.status
    } for o in active_orders])
```

And add `active_orders_json=active_orders_json` to the `render_template` call.

- [ ] **Step 4: Remove any inline polling JS from courier dashboard**

Remove any `setInterval`, `fetch('/api/`, or polling code from the template.

- [ ] **Step 5: Commit**

```bash
git add templates/courier/dashboard.html app.py
git commit -m "feat: courier dashboard with delivery map and SocketIO handlers"
```

---

## Task 13: Restaurant Dashboard — SocketIO Handlers

**Files:**
- Modify: `templates/restaurant/dashboard.html`

- [ ] **Step 1: Add extra_js block with SocketIO handlers**

At the end of the template, replace any polling JS with:

```html
{% block extra_js %}
<script>
(function() {
    socket.on('order:created', (data) => {
        window.location.reload();
    });

    socket.on('order:assigned', (data) => {
        // Update order row in the active orders list if visible
        window.location.reload();
    });

    socket.on('order:status_changed', (data) => {
        window.location.reload();
    });

    socket.on('order:cancelled', (data) => {
        window.location.reload();
    });

    socket.on('order:rejected', (data) => {
        window.location.reload();
    });
})();
</script>
{% endblock %}
```

Note: The restaurant dashboard uses server-rendered HTML with complex order cards. A full page reload on changes is the simplest approach. The WebSocket advantage here is that changes are **instant** (triggered by event) instead of delayed (polling every few seconds).

- [ ] **Step 2: Remove any existing polling JS from the template**

Remove any `setInterval`, `fetch('/api/`, or polling references.

- [ ] **Step 3: Commit**

```bash
git add templates/restaurant/dashboard.html
git commit -m "feat: restaurant dashboard SocketIO handlers"
```

---

## Task 14: Order Detail Pages — Maps + SocketIO Handlers

**Files:**
- Modify: `templates/admin/view_order.html`
- Modify: `templates/courier/view_order.html`
- Modify: `templates/restaurant/view_order.html`

- [ ] **Step 1: Add map and SocketIO to admin/view_order.html**

Add a map container in the order detail page (after the order info section):

```html
<!-- Delivery Map -->
<div class="mt-6">
    <h3 class="text-lg font-medium text-gray-900 mb-3">Mapa doručení</h3>
    <div class="bg-white rounded-lg shadow overflow-hidden">
        <div id="order-map" style="height: 350px; width: 100%;"></div>
    </div>
</div>
```

And add `{% block extra_js %}`:

```html
{% block extra_js %}
<script>
(function() {
    const ORDER_ID = {{ order.id }};

    // Join order room
    socket.emit('order:join', { order_id: ORDER_ID });

    // Map
    {% if order.pickup_latitude and order.delivery_latitude %}
    const map = initMap('order-map');

    const order = {
        pickup_latitude: {{ order.pickup_latitude }},
        pickup_longitude: {{ order.pickup_longitude }},
        delivery_latitude: {{ order.delivery_latitude }},
        delivery_longitude: {{ order.delivery_longitude }},
        pickup_address: '{{ order.pickup_address|e }}',
        delivery_address: '{{ order.delivery_address|e }}',
        restaurant_name: '{{ order.restaurant_name|e }}',
        customer_name: '{{ order.customer_name|e }}'
    };

    addOrderToMap(map, order);

    {% if order.courier_user and order.courier_user.last_known_latitude %}
    let courierMarker = L.marker(
        [{{ order.courier_user.last_known_latitude }}, {{ order.courier_user.last_known_longitude }}],
        { icon: ICONS.courierPosition }
    ).addTo(map);
    courierMarker.bindPopup('<b>{{ order.courier_user.full_name|e }}</b>');
    {% endif %}
    {% endif %}

    // SocketIO events
    socket.on('order:status_changed', (data) => {
        if (data.order_id === ORDER_ID) {
            window.location.reload();
        }
    });

    socket.on('courier:location_updated', (data) => {
        {% if order.courier_id %}
        if (data.courier_id === {{ order.courier_id }}) {
            if (typeof courierMarker !== 'undefined') {
                courierMarker.setLatLng([data.latitude, data.longitude]);
            } else if (typeof map !== 'undefined') {
                courierMarker = L.marker([data.latitude, data.longitude], { icon: ICONS.courierPosition }).addTo(map);
            }
        }
        {% endif %}
    });

    socket.on('ai:description_ready', (data) => {
        if (data.order_id === ORDER_ID) {
            window.location.reload();
        }
    });

    // Leave room on page exit
    window.addEventListener('beforeunload', () => {
        socket.emit('order:leave', { order_id: ORDER_ID });
    });
})();
</script>
{% endblock %}
```

- [ ] **Step 2: Add the same map + SocketIO pattern to courier/view_order.html**

Same structure as admin version but adapted for courier context. Same map setup, same event handlers. Copy the pattern from Step 1.

- [ ] **Step 3: Add the same map + SocketIO pattern to restaurant/view_order.html**

Same structure as admin version but adapted for restaurant context. Same map setup, same event handlers. Copy the pattern from Step 1.

- [ ] **Step 4: Remove any inline polling JS from all three view_order templates**

Remove `setInterval`, `fetch('/api/`, order-detail-polling references from all three files.

- [ ] **Step 5: Commit**

```bash
git add templates/admin/view_order.html templates/courier/view_order.html templates/restaurant/view_order.html
git commit -m "feat: order detail pages with delivery maps and SocketIO handlers"
```

---

## Task 15: Reverse Geocoding in geocoding_service.py

**Files:**
- Modify: `services/geocoding_service.py`

- [ ] **Step 1: Add reverse_geocode method**

After the `geocode_order` method in `geocoding_service.py`, add:

```python
    def reverse_geocode(self, latitude, longitude):
        """
        Convert GPS coordinates to address string

        Args:
            latitude (float): GPS latitude
            longitude (float): GPS longitude

        Returns:
            str: Address string or None if reverse geocoding fails
        """
        try:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)

            self.last_request = time.time()

            location = self.geolocator.reverse((latitude, longitude), timeout=5)

            if location:
                return location.address

        except GeocoderTimedOut:
            print(f"Reverse geocoding timeout for ({latitude}, {longitude})")
        except Exception as e:
            print(f"Reverse geocoding failed for ({latitude}, {longitude}): {e}")

        return None
```

- [ ] **Step 2: Commit**

```bash
git add services/geocoding_service.py
git commit -m "feat: add reverse geocoding to geocoding service"
```

---

## Task 16: Update setup.py Server Startup

**Files:**
- Modify: `setup.py`

- [ ] **Step 1: Update setup.py to use socketio.run**

The `setup.py` starts the server via `subprocess.run(f'"{sys.executable}" app.py', shell=True)` (line 210). This still works because `app.py`'s `__main__` block now calls `socketio.run()` instead of `app.run()`. No changes needed to `setup.py` itself.

However, verify that `app.py` no longer calls `app.run()` directly. Already changed in Task 3, Step 4.

- [ ] **Step 2: Commit (skip if no changes)**

---

## Task 17: Database Migration (Create notifications table)

- [ ] **Step 1: Run flask init-db to create the notifications table**

The project uses `db.create_all()` which creates any missing tables without affecting existing ones.

```bash
cd C:/Users/lixci/webs/courier-system
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Notifications table created')"
```

Or simply restart the app — the `__main__` block with `socketio.run()` will trigger model loading.

- [ ] **Step 2: Verify**

```bash
python -c "
from app import app, db
from models import Notification
with app.app_context():
    count = Notification.query.count()
    print(f'Notifications table exists, {count} rows')
"
```

Expected: `Notifications table exists, 0 rows`

---

## Task 18: Final Verification

- [ ] **Step 1: Start the server**

```bash
cd C:/Users/lixci/webs/courier-system
python app.py
```

Expected: Server starts on `http://0.0.0.0:5000` with gevent/WebSocket support.

- [ ] **Step 2: Test multi-user WebSocket flow**

1. Open browser tab 1: Login as `admin` / `admin123` → Dashboard shows map with couriers
2. Open browser tab 2: Login as `pizza_palace` / `rest123` → Create an order
3. Verify: Admin tab instantly shows new order on map + notification bell shows count
4. If courier auto-assigned: courier gets notification

- [ ] **Step 3: Test notification bell**

1. Click bell icon → dropdown appears with notifications
2. Click a notification → redirects to order detail
3. Click "Oznacit vse" → all notifications marked as read, badge disappears

- [ ] **Step 4: Test order detail map**

1. Open any order detail → map shows pickup (blue P) and delivery (red D) markers with route
2. If courier assigned with GPS → courier marker (indigo C) visible

- [ ] **Step 5: Test courier dashboard map**

1. Login as courier → map shows assigned orders
2. If courier has GPS position → route drawn from position to pickup

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete WebSocket, maps, and notifications integration"
```
