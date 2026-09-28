"""Officer email-OTP sign-in: account discovery, code lifetime and throttling."""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.db.mixins import utcnow
from app.modules.otp.models import OtpChallenge
from app.modules.users.models import Role
from tests.conftest import last_code_for, make_user, sent_codes

OTP_URL = "/api/v1/auth/officer/otp"
VERIFY_URL = "/api/v1/auth/officer/verify"


def request_code(client, email: str):
    sent_codes()  # installs the capturing mailbox if the test has none
    return client.post(OTP_URL, json={"email": email})


def verify(client, email: str, code: str):
    return client.post(VERIFY_URL, json={"email": email, "code": code})


def wrong_code(right: str) -> str:
    return "000000" if right != "000000" else "111111"


@pytest.fixture()
def other_accounts(db, admin):
    inactive = make_user(db, "inactive.officer@example.com", Role.SECURITY_OFFICER)
    inactive.is_active = False
    deleted = make_user(db, "deleted.officer@example.com", Role.SECURITY_OFFICER)
    deleted.deleted_at = utcnow()
    db.commit()
    return {"inactive": inactive.email, "deleted": deleted.email, "admin": admin.email}


def test_only_active_officers_get_a_code_and_every_address_gets_the_same_answer(client, officer, other_accounts):
    sent_codes()
    responses = {
        "officer": request_code(client, officer.email),
        "unknown": request_code(client, "never.registered@example.com"),
        **{name: request_code(client, email) for name, email in other_accounts.items()},
    }

    assert {name: r.status_code for name, r in responses.items()} == dict.fromkeys(responses, 202)
    assert {tuple(r.json()) for r in responses.values()} == {("resend_available_at",)}
    assert [address for address, _ in sent_codes()] == [officer.email]


@pytest.mark.parametrize("change", ["deactivate", "delete", "make_admin"])
def test_code_stops_working_when_the_account_changes(client, db, officer, change):
    request_code(client, officer.email)
    code = last_code_for(officer.email)
    if change == "deactivate":
        officer.is_active = False
    elif change == "delete":
        officer.deleted_at = utcnow()
    else:
        officer.role = Role.ADMIN
    db.commit()
    assert verify(client, officer.email, code).status_code == 400


def test_code_is_never_returned_or_logged(client, officer, caplog):
    caplog.set_level(logging.DEBUG)
    sent_codes()
    response = request_code(client, officer.email)
    code = last_code_for(officer.email)

    assert code not in response.text
    session = verify(client, officer.email, code)
    assert session.status_code == 200
    assert code not in session.text
    assert code not in caplog.text


def test_correct_code_starts_a_shift_length_officer_session(client, officer):
    request_code(client, officer.email)
    body = verify(client, officer.email, last_code_for(officer.email)).json()

    assert body["user"] == {"id": officer.id, "role": "security_officer", "name": officer.full_name}
    assert body["expires_in"] == 8 * 60 * 60
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["role"] == "security_officer"


def test_code_works_once(client, officer):
    request_code(client, officer.email)
    code = last_code_for(officer.email)
    assert verify(client, officer.email, code).status_code == 200
    assert verify(client, officer.email, code).status_code == 400


def test_expired_code_is_rejected(client, db, officer):
    request_code(client, officer.email)
    db.execute(update(OtpChallenge).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    assert verify(client, officer.email, last_code_for(officer.email)).status_code == 400


def test_code_is_used_up_after_too_many_wrong_guesses(client, officer):
    request_code(client, officer.email)
    code = last_code_for(officer.email)
    for _ in range(5):
        assert verify(client, officer.email, wrong_code(code)).status_code == 400
    assert verify(client, officer.email, code).status_code == 400


def test_new_code_replaces_the_old_one(client, officer, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    request_code(client, officer.email)
    first = last_code_for(officer.email)
    request_code(client, officer.email)
    second = last_code_for(officer.email)
    if first != second:
        assert verify(client, officer.email, first).status_code == 400
    assert verify(client, officer.email, second).status_code == 200


def test_hourly_cap_sends_nothing_and_pushes_out_the_resend_time(client, officer, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0, otp_max_per_email_per_hour=2)
    sent_codes()
    for _ in range(2):
        assert request_code(client, officer.email).status_code == 202
    capped = request_code(client, officer.email)

    assert capped.status_code == 202
    assert len(sent_codes()) == 2
    resend_at = capped.json()["resend_available_at"]
    assert resend_at > (utcnow() + timedelta(minutes=1)).isoformat()


def test_per_ip_cap_is_enforced(client, db, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0, otp_max_per_ip_per_hour=2)
    officers = [make_user(db, f"gate{i}@example.com", Role.SECURITY_OFFICER) for i in range(3)]
    sent_codes()
    for officer in officers:
        assert request_code(client, officer.email).status_code == 202
    assert [address for address, _ in sent_codes()] == [officers[0].email, officers[1].email]


def test_email_outage_is_reported_as_unavailable(client, officer, mailbox):
    mailbox.fail = True
    response = request_code(client, officer.email)
    assert response.status_code == 503


def test_logout_revokes_the_officer_session(client, officer):
    request_code(client, officer.email)
    token = verify(client, officer.email, last_code_for(officer.email)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/events", headers=headers).status_code == 401
