"""Smoke tests for authentication flows."""


def test_index_redirects_to_login(client):
    resp = client.get('/', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_login_page_renders(client):
    resp = client.get('/login')
    assert resp.status_code == 200
    assert b'Sign in' in resp.data or b'Login' in resp.data


def test_login_with_valid_credentials(client):
    resp = client.post('/login',
                       data={'username': 'admin', 'password': 'admin123'},
                       follow_redirects=True)
    assert resp.status_code == 200


def test_login_with_invalid_credentials(client):
    # Ensure starting from a clean (logged-out) session
    client.get('/logout')
    client.post('/login', data={'username': 'admin', 'password': 'wrong'})
    # After wrong password, hitting a protected page should redirect to /login
    resp = client.get('/admin/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location'] or '/dashboard' in resp.headers['Location']


def test_logout_redirects(logged_in_admin):
    resp = logged_in_admin.get('/logout', follow_redirects=False)
    assert resp.status_code == 302


def test_dashboard_requires_login(client):
    resp = client.get('/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
