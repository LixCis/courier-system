"""Application entry point / factory.

Keep this file small: initialization only. All routes live in blueprints/.
"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

from gevent import monkey
monkey.patch_all()

import os

from flask import Flask

from config import Config
from models import db
from extensions import login_manager, socketio, migrate, csrf, limiter, init_socketio_service
from common.logging_config import init_logging, get_logger


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Disable rate limiting in test environment
    if app.config.get('TESTING'):
        app.config['RATELIMIT_ENABLED'] = False

    app.jinja_env.globals.update(min=min, max=max)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize JSON logging with request_id tracking
    init_logging(app)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    socketio.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    init_socketio_service()

    # Security headers via Flask-Talisman
    # TODO: Tighten 'unsafe-inline' in CSP after inline scripts are refactored
    from flask_talisman import Talisman
    Talisman(
        app,
        force_https=False,  # dev environment
        session_cookie_http_only=True,
        session_cookie_secure=False,  # dev environment
        frame_options='DENY',
        referrer_policy='strict-origin-when-cross-origin',
        content_security_policy={
            'default-src': "'self'",
            'script-src': ["'self'", "'unsafe-inline'", "'unsafe-eval'", "https://cdn.tailwindcss.com", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://unpkg.com"],
            'style-src': ["'self'", "'unsafe-inline'", "https://cdn.tailwindcss.com", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://unpkg.com", "https://fonts.googleapis.com"],
            'img-src': ["'self'", "data:", "blob:", "https:"],
            'connect-src': ["'self'", "ws:", "wss:", "https://router.project-osrm.org", "https://nominatim.openstreetmap.org", "https://cdn.tailwindcss.com", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://unpkg.com"],
            'font-src': ["'self'", "https://fonts.gstatic.com", "data:"],
            'frame-src': "'self'",
        }
    )

    # Order scheduler (background job that auto-assigns pending orders)
    from services.order_scheduler import init_scheduler
    init_scheduler(app)

    # Register blueprints (each exposes a register(app) function)
    from blueprints import auth, admin, restaurant, courier, notifications, errors, cli
    auth.register(app)
    admin.register(app)
    restaurant.register(app)
    courier.register(app)
    notifications.register(app)
    errors.register(app)
    cli.register(app)

    # Import SocketIO event handlers (they bind via @socketio.on decorators)
    from blueprints import sockets  # noqa: F401

    return app


app = create_app()


# Start AI pre-generation in background (only main process, not reloader)
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    from common.background import pregenerate_ai_insights
    socketio.start_background_task(pregenerate_ai_insights, app)


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
