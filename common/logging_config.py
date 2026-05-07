"""Central logging configuration."""
import logging
import sys
import uuid
from pythonjsonlogger import jsonlogger
from flask import g, has_request_context


class RequestIdFilter(logging.Filter):
    """Add request_id to log records."""
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, 'request_id', 'no-context')
        else:
            record.request_id = 'no-context'
        return True


def init_logging(app):
    """Initialize JSON logging with Flask app context."""
    root = logging.getLogger()
    if root.handlers:
        return  # Already configured

    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt='%(timestamp)s %(level)s %(name)s %(message)s %(request_id)s',
        timestamp=True
    )
    handler.setFormatter(formatter)
    request_filter = RequestIdFilter()
    handler.addFilter(request_filter)
    root.addHandler(handler)

    # Mute some noisy loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    # Register before_request hook
    @app.before_request
    def generate_request_id():
        g.request_id = str(uuid.uuid4())


def configure_logging(level=logging.INFO):
    """Configure root logger with a consistent format (legacy wrapper)."""
    root = logging.getLogger()
    if root.handlers:
        return  # Already configured

    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    root.addHandler(handler)

    # Mute some noisy loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_logger(name):
    return logging.getLogger(name)
