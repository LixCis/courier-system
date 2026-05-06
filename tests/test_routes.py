"""Role-based route smoke tests."""


# Admin ---------------------------------------------------------------------

def test_admin_dashboard_accessible(logged_in_admin):
    resp = logged_in_admin.get('/admin/dashboard')
    assert resp.status_code == 200


def test_admin_users_accessible(logged_in_admin):
    resp = logged_in_admin.get('/admin/users')
    assert resp.status_code == 200


def test_admin_orders_accessible(logged_in_admin):
    resp = logged_in_admin.get('/admin/orders')
    assert resp.status_code == 200


def test_admin_analytics_accessible(logged_in_admin):
    resp = logged_in_admin.get('/admin/analytics')
    assert resp.status_code == 200


def test_admin_api_insights_returns_json(logged_in_admin):
    resp = logged_in_admin.get('/api/admin/ai-insights')
    assert resp.status_code == 200
    assert resp.is_json


# Restaurant ----------------------------------------------------------------

def test_restaurant_dashboard_accessible(logged_in_restaurant):
    resp = logged_in_restaurant.get('/restaurant/dashboard')
    assert resp.status_code == 200


def test_restaurant_cannot_access_admin(logged_in_restaurant):
    resp = logged_in_restaurant.get('/admin/dashboard', follow_redirects=False)
    assert resp.status_code == 302  # redirected to dashboard


def test_restaurant_create_order_page(logged_in_restaurant):
    resp = logged_in_restaurant.get('/restaurant/order/create')
    assert resp.status_code == 200


def test_restaurant_history_accessible(logged_in_restaurant):
    resp = logged_in_restaurant.get('/restaurant/orders/history')
    assert resp.status_code == 200


# Courier -------------------------------------------------------------------

def test_courier_dashboard_accessible(logged_in_courier):
    resp = logged_in_courier.get('/courier/dashboard')
    assert resp.status_code == 200


def test_courier_cannot_access_admin(logged_in_courier):
    resp = logged_in_courier.get('/admin/dashboard', follow_redirects=False)
    assert resp.status_code == 302


def test_courier_profile_accessible(logged_in_courier):
    resp = logged_in_courier.get('/courier/profile')
    assert resp.status_code == 200


def test_courier_update_location_page(logged_in_courier):
    resp = logged_in_courier.get('/courier/update-location')
    assert resp.status_code == 200


def test_courier_history_accessible(logged_in_courier):
    resp = logged_in_courier.get('/courier/orders/history')
    assert resp.status_code == 200


# Cross-cutting -------------------------------------------------------------

def test_notifications_page_requires_login(client):
    resp = client.get('/notifications', follow_redirects=False)
    assert resp.status_code == 302


def test_notifications_page_when_logged_in(logged_in_admin):
    resp = logged_in_admin.get('/notifications')
    assert resp.status_code == 200
