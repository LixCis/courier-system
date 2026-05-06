"""Notifications page route."""
from flask import render_template, request
from flask_login import login_required, current_user

from models import Notification


def register(app):
    @app.route('/notifications')
    @login_required
    def notifications_page():
        page = request.args.get('page', 1, type=int)
        pagination = Notification.query.filter_by(user_id=current_user.id)\
            .order_by(Notification.created_at.desc())\
            .paginate(page=page, per_page=20, error_out=False)
        return render_template('notifications.html', pagination=pagination)
