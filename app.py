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
from extensions import login_manager, socketio, migrate, csrf, init_socketio_service
from common.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.jinja_env.globals.update(min=min, max=max)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    socketio.init_app(app)
    csrf.init_app(app)
    init_socketio_service()

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
