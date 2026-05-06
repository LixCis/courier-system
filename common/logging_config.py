"""Central logging configuration."""
import logging
import sys


def configure_logging(level=logging.INFO):
    """Configure root logger with a consistent format."""
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
