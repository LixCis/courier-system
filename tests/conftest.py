"""Pytest fixtures for the courier system app."""
import os
import sys

# In-memory SQLite + disable CSRF for test simplicity
os.environ.setdefault('DATABASE_URI', 'sqlite:///:memory:')
os.environ.setdefault('WTF_CSRF_ENABLED', 'false')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')

# Add project root to import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import app as flask_app
from models import db, User


@pytest.fixture(scope='session')
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
    )
    with flask_app.app_context():
        db.create_all()
        _seed_minimal_users()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _seed_minimal_users():
    """Create one user per role for auth tests."""
    if User.query.first():
        return
    admin = User(username='admin', email='admin@test.local', full_name='Admin', role='admin')
    admin.set_password('admin123')
    rest = User(username='rest', email='rest@test.local', full_name='Restaurant', role='restaurant',
                last_known_latitude=49.8, last_known_longitude=18.28)
    rest.set_password('rest123')
    cour = User(username='cour', email='cour@test.local', full_name='Courier', role='courier',
                is_available=True, last_known_latitude=49.82, last_known_longitude=18.26)
    cour.set_password('cour123')
    db.session.add_all([admin, rest, cour])
    db.session.commit()


@pytest.fixture()
def logged_in_admin(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    yield client
    client.get('/logout')


@pytest.fixture()
def logged_in_restaurant(client):
    client.post('/login', data={'username': 'rest', 'password': 'rest123'}, follow_redirects=True)
    yield client
    client.get('/logout')


@pytest.fixture()
def logged_in_courier(client):
    client.post('/login', data={'username': 'cour', 'password': 'cour123'}, follow_redirects=True)
    yield client
    client.get('/logout')
