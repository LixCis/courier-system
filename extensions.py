"""Shared Flask extension instances.

Blueprint modules import from here so they don't create circular dependencies
with app.py.
"""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

socketio = SocketIO(manage_session=False, async_mode='gevent', cors_allowed_origins="*")
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")

socketio_service = None


def init_socketio_service():
    """Instantiate SocketIOService lazily (after socketio is initialized with app)."""
    global socketio_service
    if socketio_service is None:
        from services.socketio_service import SocketIOService
        socketio_service = SocketIOService(socketio)
    return socketio_service
