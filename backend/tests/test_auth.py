from app.core.config import get_settings
from app.modules.users.models import Role
from tests.conftest import PASSWORD, auth_headers, last_code_for, login, make_user, sent_codes, sign_in


def test_admin_password_step_emails_a_code_and_returns_a_challenge(client, admin):
    response = login(client, admin.email)
    assert response.status_code == 200
    body = response.json()
    assert body["challenge_id"]
    assert "access_token" not in body
    assert sent_codes()[-1][0] == admin.email


def test_admin_code_step_returns_session_for_the_frontend(client, admin):
    response = sign_in(client, admin)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"] == {"id": admin.id, "role": "admin", "name": admin.full_name}


def test_challenge_id_alone_is_not_an_access_token(client, admin):
    challenge = login(client, admin.email).json()["challenge_id"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {challenge}"}).status_code == 401


def test_wrong_second_factor_code_is_rejected(client, admin):
    challenge = login(client, admin.email).json()["challenge_id"]
    wrong = "000000" if last_code_for(admin.email) != "000000" else "111111"
    response = client.post("/api/v1/auth/login/verify", json={"challenge_id": challenge, "code": wrong})
    assert response.status_code == 400


def test_second_factor_code_works_only_once(client, admin):
    challenge = login(client, admin.email).json()["challenge_id"]
    body = {"challenge_id": challenge, "code": last_code_for(admin.email)}
    assert client.post("/api/v1/auth/login/verify", json=body).status_code == 200
    assert client.post("/api/v1/auth/login/verify", json=body).status_code == 400


def test_tampered_challenge_is_rejected(client, admin):
    login(client, admin.email)
    body = {"challenge_id": "not-a-challenge", "code": last_code_for(admin.email)}
    assert client.post("/api/v1/auth/login/verify", json=body).status_code == 400


def test_officer_cannot_use_password_login(client, officer):
    assert login(client, officer.email).status_code == 401


def test_officer_signs_in_with_emailed_code(client, officer):
    response = sign_in(client, officer)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "security_officer"


def test_officer_otp_gives_same_answer_for_unknown_addresses(client, officer, admin):
    sent_codes()
    unknown = client.post("/api/v1/auth/officer/otp", json={"email": "nobody@example.com"})
    admin_address = client.post("/api/v1/auth/officer/otp", json={"email": admin.email})
    assert unknown.status_code == admin_address.status_code == 202
    assert sent_codes() == []


def test_officer_otp_resend_is_throttled_without_revealing_the_account(client, officer):
    sign_in(client, officer)
    emails_before = len(sent_codes())
    again = client.post("/api/v1/auth/officer/otp", json={"email": officer.email})
    unknown = client.post("/api/v1/auth/officer/otp", json={"email": "nobody@example.com"})
    # A 429 only real officers could get would tell a caller which addresses are officers.
    assert again.status_code == unknown.status_code == 202
    assert again.json().keys() == unknown.json().keys() == {"resend_available_at"}
    assert len(sent_codes()) == emails_before


def test_officer_wrong_code_is_rejected(client, officer):
    sent_codes()
    client.post("/api/v1/auth/officer/otp", json={"email": officer.email})
    wrong = "000000" if last_code_for(officer.email) != "000000" else "111111"
    body = {"email": officer.email, "code": wrong}
    assert client.post("/api/v1/auth/officer/verify", json=body).status_code == 400


def test_officer_email_is_case_insensitive(client, officer):
    sent_codes()
    assert client.post("/api/v1/auth/officer/otp", json={"email": "OFFICER@Example.com"}).status_code == 202
    body = {"email": "Officer@example.com", "code": last_code_for(officer.email)}
    assert client.post("/api/v1/auth/officer/verify", json=body).status_code == 200


def test_officer_otp_rejects_malformed_email(client, officer):
    sent_codes()
    response = client.post("/api/v1/auth/officer/otp", json={"email": "officer@example.com\r\nBcc: x@evil.test"})
    assert response.status_code == 422
    assert sent_codes() == []


def test_logout_revokes_the_token(client, admin_headers):
    assert client.post("/api/v1/auth/logout", headers=admin_headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=admin_headers).status_code == 401


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
    assert sign_in(client, admin).status_code == 200
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
    headers = auth_headers(client, user)
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
            "mobile": "+91 91234 56789",
            "role": "security_officer",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new.officer@example.com"
    sent = client.post("/api/v1/auth/officer/otp", json={"email": "new.officer@example.com"})
    assert sent.status_code == 202
    assert sent_codes()[-1][0] == "new.officer@example.com"
    code = sent_codes()[-1][1]
    verified = client.post("/api/v1/auth/officer/verify", json={"email": "new.officer@example.com", "code": code})
    assert verified.status_code == 200


def test_officer_accounts_have_no_password_and_admins_need_one(client, admin_headers):
    base = {"email": "x@example.com", "full_name": "X", "mobile": "9123456789"}
    officer_with_password = {**base, "password": PASSWORD, "role": "security_officer"}
    admin_without_password = {**base, "role": "admin"}
    assert client.post("/api/v1/users", headers=admin_headers, json=officer_with_password).status_code == 422
    assert client.post("/api/v1/users", headers=admin_headers, json=admin_without_password).status_code == 422


def test_mobile_is_optional_for_staff(client, admin_headers):
    body = {"email": "no.mobile@example.com", "full_name": "No Mobile", "role": "security_officer"}
    assert client.post("/api/v1/users", headers=admin_headers, json=body).status_code == 201


def test_duplicate_mobile_is_rejected(client, admin_headers):
    body = {"full_name": "Other", "mobile": "9123456789", "role": "security_officer"}
    first = client.post("/api/v1/users", headers=admin_headers, json={**body, "email": "one@example.com"})
    assert first.status_code == 201
    response = client.post("/api/v1/users", headers=admin_headers, json={**body, "email": "two@example.com"})
    assert response.status_code == 409


def test_duplicate_email_is_rejected(client, admin_headers, admin):
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": admin.email,
            "full_name": "Dup",
            "mobile": "9123456789",
            "password": PASSWORD,
            "role": "admin",
        },
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
                "mobile": "9123456789",
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
