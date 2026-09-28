from app.core.config import get_settings
from app.modules.users.models import Role
from tests.conftest import PASSWORD, auth_headers, login, make_user


def test_login_returns_bearer_token(client, admin):
    response = login(client, admin.email)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_email_is_case_insensitive(client, admin):
    assert login(client, "ADMIN@Example.com").status_code == 200


def test_wrong_password_and_unknown_email_look_the_same(client, admin):
    wrong_password = login(client, admin.email, "Wrong-password-1")
    unknown_email = login(client, "nobody@example.com")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_account_locks_after_repeated_failures(client, db, admin):
    for _ in range(get_settings().max_failed_login_attempts):
        assert login(client, admin.email, "Wrong-password-1").status_code == 401
    # Even the right password is refused while the lock is active.
    response = login(client, admin.email)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"
    db.refresh(admin)
    assert admin.locked_until is not None


def test_successful_login_resets_failure_count(client, db, admin):
    login(client, admin.email, "Wrong-password-1")
    assert login(client, admin.email).status_code == 200
    db.refresh(admin)
    assert admin.failed_login_attempts == 0
    assert admin.last_login_at is not None


def test_inactive_user_cannot_log_in(client, db, admin):
    admin.is_active = False
    db.commit()
    assert login(client, admin.email).status_code == 401


def test_me_returns_current_user_without_password_hash(client, admin_headers):
    response = client.get("/api/v1/auth/me", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@example.com"
    assert body["role"] == "admin"
    assert "password_hash" not in body


def test_me_rejects_missing_and_bad_tokens(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    bad = {"Authorization": "Bearer not.a.token"}
    assert client.get("/api/v1/auth/me", headers=bad).status_code == 401


def test_token_stops_working_once_user_is_deactivated(client, db, admin_headers, admin):
    admin.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=admin_headers).status_code == 401


def test_role_change_takes_effect_immediately(client, db):
    user = make_user(db, "demoted@example.com", Role.ADMIN)
    headers = auth_headers(client, user.email)
    user.role = Role.SECURITY_OFFICER
    db.commit()
    assert client.get("/api/v1/users", headers=headers).status_code == 403


def test_admin_creates_staff_users(client, admin_headers):
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": "New.Officer@Example.com",
            "full_name": "New Officer",
            "password": PASSWORD,
            "role": "security_officer",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new.officer@example.com"
    assert login(client, "new.officer@example.com").status_code == 200


def test_duplicate_email_is_rejected(client, admin_headers, admin):
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": admin.email, "full_name": "Dup", "password": PASSWORD, "role": "admin"},
    )
    assert response.status_code == 409


def test_weak_passwords_are_rejected(client, admin_headers):
    for password in ("short-1", "onlylettersinhere", "123456789012345"):
        response = client.post(
            "/api/v1/users",
            headers=admin_headers,
            json={
                "email": "x@example.com",
                "full_name": "X",
                "password": password,
                "role": "admin",
            },
        )
        assert response.status_code == 422, password


def test_unknown_role_is_rejected(client, admin_headers):
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": "x@example.com", "full_name": "X", "password": PASSWORD, "role": "root"},
    )
    assert response.status_code == 422


def test_officer_cannot_manage_users(client, officer_headers):
    assert client.get("/api/v1/users", headers=officer_headers).status_code == 403
    response = client.post(
        "/api/v1/users",
        headers=officer_headers,
        json={"email": "x@example.com", "full_name": "X", "password": PASSWORD, "role": "admin"},
    )
    assert response.status_code == 403


def test_real_token_reaches_event_routes(client, admin_headers, officer_headers):
    """End to end through login, without overriding the current-user dependency."""
    body = {
        "title": "Navratri Garba Night",
        "location": "Mastek campus, Mumbai",
        "starts_at": "2030-10-20T18:00:00+05:30",
        "capacity": 500,
    }
    assert client.post("/api/v1/events", headers=admin_headers, json=body).status_code == 201
    assert client.post("/api/v1/events", headers=officer_headers, json=body).status_code == 403
    assert client.get("/api/v1/events", headers=officer_headers).json()["total"] == 0
