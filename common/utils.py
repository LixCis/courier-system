"""Generic helpers used across blueprints."""
from datetime import datetime, timezone
from flask import current_app


def utcnow():
    """Naive UTC datetime (DB-compatible with existing records)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def allowed_file(filename):
    """Check file extension against configured ALLOWED_EXTENSIONS."""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config['ALLOWED_EXTENSIONS']
