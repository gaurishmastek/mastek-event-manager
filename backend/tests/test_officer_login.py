"""Officer email-and-password sign-in: default password, account discovery, lockout and session length."""

import logging

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import verify_password
from app.db.mixins import utcnow
from app.modules.otp.models import OtpChallenge
from app.modules.users.models import Role, User
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from tests.conftest import OFFICER_PASSWORD, make_user, sent_codes

LOGIN_URL = "/api/v1/auth/officer/login"


def officer_login(client, email: str, password: str = OFFICER_PASSWORD):
    return client.post(LOGIN_URL, json={"email": email, "password": password})


@pytest.fixture()
def other_accounts(db, admin):
    inactive = make_user(db, "inactive.officer@example.com", Role.SECURITY_OFFICER)
    inactive.is_active = False
    deleted = make_user(db, "deleted.officer@example.com", Role.SECURITY_OFFICER)
    deleted.deleted_at = utcnow()
    db.commit()
    return {"inactive": inactive.email, "deleted": deleted.email, "admin": admin.email}


def test_new_officer_gets_the_default_password_stored_only_as_a_hash(db, officer):
    assert get_settings().default_officer_password == OFFICER_PASSWORD
    assert OFFICER_PASSWORD not in officer.password_hash
    assert verify_password(OFFICER_PASSWORD, officer.password_hash)


def test_officer_created_with_own_password_uses_it(client, db):
    data = UserCreate(email="own@example.com", full_name="Own", password="Gate-shift-2026", role=Role.SECURITY_OFFICER)
    create_user(db, data)
    assert officer_login(client, "own@example.com", "Gate-shift-2026").status_code == 200
    assert officer_login(client, "own@example.com").status_code == 401


def test_correct_password_starts_a_shift_length_officer_session_without_any_email(client, officer):
    sent_codes()
    body = officer_login(client, officer.email).json()

    assert body["user"] == {"id": officer.id, "role": "security_officer", "name": officer.full_name}
    assert body["expires_in"] == 8 * 60 * 60
    assert sent_codes() == []
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["role"] == "security_officer"


def test_email_is_case_insensitive(client, officer):
    assert officer_login(client, "OFFICER@Example.com").status_code == 200


def test_every_failure_gets_the_same_answer(client, officer, other_accounts):
    responses = {
        "wrong_password": officer_login(client, officer.email, "wrong-password"),
        "unknown": officer_login(client, "never.registered@example.com"),
        **{name: officer_login(client, email) for name, email in other_accounts.items()},
    }
    assert {name: r.status_code for name, r in responses.items()} == dict.fromkeys(responses, 401)
    assert {r.json()["detail"] for r in responses.values()} == {"Invalid email or password"}


def test_repeated_wrong_passwords_lock_the_account(client, officer):
    for _ in range(get_settings().max_failed_login_attempts):
        assert officer_login(client, officer.email, "wrong-password").status_code == 401
    # Locked: even the right password is refused, with the same answer.
    locked = officer_login(client, officer.email)
    assert locked.status_code == 401
    assert locked.json()["detail"] == "Invalid email or password"


def test_successful_login_resets_the_failure_count(client, db, officer):
    for _ in range(get_settings().max_failed_login_attempts - 1):
        officer_login(client, officer.email, "wrong-password")
    assert officer_login(client, officer.email).status_code == 200
    db.refresh(officer)
    assert officer.failed_login_attempts == 0


@pytest.mark.parametrize("change", ["deactivate", "delete", "make_admin"])
def test_session_stops_working_when_the_account_changes(client, db, officer, change):
    token = officer_login(client, officer.email).json()["access_token"]
    if change == "deactivate":
        officer.is_active = False
    elif change == "delete":
        officer.deleted_at = utcnow()
    else:
        officer.role = Role.ADMIN
    db.commit()
    assert officer_login(client, officer.email).status_code == 401
    if change != "make_admin":
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_password_is_never_returned_or_logged(client, officer, caplog):
    caplog.set_level(logging.DEBUG)
    response = officer_login(client, officer.email)
    assert response.status_code == 200
    assert OFFICER_PASSWORD not in response.text
    assert OFFICER_PASSWORD not in caplog.text


def test_officer_login_issues_no_code(client, db, officer):
    officer_login(client, officer.email)
    assert db.scalars(select(OtpChallenge)).all() == []


def test_old_code_endpoints_are_gone(client, officer):
    assert client.post("/api/v1/auth/officer/otp", json={"email": officer.email}).status_code in (401, 404, 405)
    body = {"email": officer.email, "code": "123456"}
    assert client.post("/api/v1/auth/officer/verify", json=body).status_code in (401, 404, 405)


def test_malformed_input_is_rejected(client, officer):
    injected = {"email": "officer@example.com\r\nBcc: x@evil.test", "password": "x"}
    assert client.post(LOGIN_URL, json=injected).status_code == 422
    assert client.post(LOGIN_URL, json={"email": officer.email, "password": ""}).status_code == 422
    assert client.post(LOGIN_URL, json={"email": officer.email, "password": "x", "code": "123456"}).status_code == 422


def test_logout_revokes_the_officer_session(client, officer):
    token = officer_login(client, officer.email).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/events", headers=headers).status_code == 401


def test_default_password_can_be_overridden(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "default_officer_password", "Other-default-9")
    user = make_user(db, "custom@example.com", Role.SECURITY_OFFICER)
    assert isinstance(user, User)
    assert officer_login(client, "custom@example.com", "Other-default-9").status_code == 200
    assert officer_login(client, "custom@example.com").status_code == 401
