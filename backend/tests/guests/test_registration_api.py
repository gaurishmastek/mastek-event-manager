from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.crypto import token_hash
from app.db.mixins import utcnow
from app.modules.guests.models import Registration
from app.modules.otp.models import OtpChallenge

BASE = "/api/v1/public"


def verify(client, registration_id: str, code: str):
    return client.post(f"{BASE}/registrations/{registration_id}/verify", json={"code": code})


def resend(client, registration_id: str):
    return client.post(f"{BASE}/registrations/{registration_id}/otp")


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


# --- happy path ------------------------------------------------------------


def test_public_event_info_needs_no_login(client, make_event):
    event = make_event(capacity=50)

    response = client.get(f"{BASE}/events/{event.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Navratri Garba Night"
    assert body["registration_open"] is True
    assert body["seats_left"] == 50
    assert "created_by" not in body


def test_register_sends_otp_and_masks_mobile(client, sms, register, make_event):
    event = make_event()

    response = register(event.id, mobile="+91 98765-43210")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["mobile"] == "98•••••210"
    assert "code" not in response.text and sms.last_code not in response.text
    assert sms.sent == [("+919876543210", sms.last_code)]
    assert response.headers["cache-control"] == "no-store"


def test_verify_issues_a_random_pass_stored_only_as_hash(client, sms, register, make_event, db_session):
    event = make_event()
    registration_id = register(event.id).json()["registration_id"]

    response = verify(client, registration_id, sms.last_code)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "VERIFIED"
    assert body["event"]["id"] == event.id
    assert len(body["qr_token"]) >= 43
    assert body["qr_svg"].startswith("data:image/svg+xml")
    row = db_session.scalars(select(Registration)).one()
    assert row.qr_token_hash == token_hash(body["qr_token"])
    assert body["qr_token"] not in (row.qr_token_hash, row.mobile_encrypted)
    assert "9876543210" not in row.mobile_encrypted and row.mobile_hash != "+919876543210"


def test_otp_is_stored_only_as_hmac(client, sms, register, make_event, db_session):
    register(make_event().id)

    challenge = db_session.scalars(select(OtpChallenge)).one()
    assert sms.last_code not in challenge.code_hmac
    assert len(challenge.code_hmac) == 64


def test_reverifying_reissues_pass_and_voids_the_old_one(client, sms, register, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    registration_id = register(event.id).json()["registration_id"]
    first = verify(client, registration_id, sms.last_code).json()["qr_token"]

    assert register(event.id).json()["registration_id"] == registration_id
    second = verify(client, registration_id, sms.last_code).json()["qr_token"]

    assert first != second
    row = db_session.scalars(select(Registration)).one()
    db_session.refresh(row)
    assert row.qr_token_hash == token_hash(second)


def test_same_mobile_reuses_registration_and_pending_name_is_updated(client, sms, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    first = register(event.id, name="Asha").json()["registration_id"]

    second = register(event.id, name="Asha Patil").json()["registration_id"]
    body = verify(client, second, sms.last_code).json()

    assert first == second
    assert body["guest_name"] == "Asha Patil"


# --- input validation ------------------------------------------------------


@pytest.mark.parametrize("mobile", ["12345", "5876543210", "+1 415 555 0100", "98765432101", "98765abcde"])
def test_rejects_non_indian_or_malformed_mobiles(register, sms, make_event, mobile):
    response = register(make_event().id, mobile=mobile)

    assert response.status_code == 422
    assert sms.sent == []


def test_requires_consent(client, sms, make_event):
    body = {"guest_name": "Asha", "mobile": "9876543210", "consent": False}

    response = client.post(f"{BASE}/events/{make_event().id}/registrations", json=body)

    assert response.status_code == 422


def test_rejects_unknown_fields_and_control_characters(register, sms, make_event):
    event = make_event()

    assert register(event.id, status="VERIFIED").status_code == 422
    assert register(event.id, name="Asha\x00").status_code == 422
    assert register(event.id, name="x" * 101).status_code == 422


def test_verify_rejects_non_numeric_code(client, sms, register, make_event):
    registration_id = register(make_event().id).json()["registration_id"]

    assert verify(client, registration_id, "12a456").status_code == 422
    assert verify(client, registration_id, "1234567").status_code == 422


def test_unknown_or_malformed_registration_id(client, sms):
    assert verify(client, "00000000-0000-0000-0000-000000000000", "123456").status_code == 404
    assert verify(client, "1", "123456").status_code == 422


# --- event state -------------------------------------------------------------


def test_unknown_or_deleted_event_is_404(register, sms, make_event, db_session):
    event = make_event()
    event.deleted_at = utcnow()
    db_session.commit()

    assert register(event.id).status_code == 404
    assert register(999).status_code == 404


def test_registration_closes_when_event_ends(register, sms, make_event):
    event = make_event(starts_in=timedelta(hours=-6), duration=timedelta(hours=5))

    response = register(event.id)

    assert response.status_code == 409
    assert sms.sent == []


def test_full_event_rejects_new_guests_before_sending_sms(register, sms, issue_pass, make_event):
    event = make_event(capacity=1)
    issue_pass(event.id, mobile="9876543210")
    sent_before = len(sms.sent)

    response = register(event.id, mobile="9123456789")

    assert response.status_code == 409
    assert response.json()["detail"] == "This event is full"
    assert len(sms.sent) == sent_before


def test_unverified_registrations_do_not_take_seats(client, sms, register, make_event):
    event = make_event(capacity=1)
    register(event.id, mobile="9876543210")

    assert client.get(f"{BASE}/events/{event.id}").json()["seats_left"] == 1
    assert register(event.id, mobile="9123456789").status_code == 202


def test_capacity_is_checked_at_verification(client, sms, register, make_event):
    event = make_event(capacity=1)
    first = register(event.id, mobile="9876543210").json()["registration_id"]
    first_code = sms.last_code
    second = register(event.id, mobile="9123456789").json()["registration_id"]
    assert verify(client, second, sms.last_code).status_code == 200

    response = verify(client, first, first_code)

    assert response.status_code == 409
    assert response.json()["detail"] == "This event is full"


# --- OTP abuse limits --------------------------------------------------------


def test_wrong_code_is_rejected_and_attempts_are_limited(client, sms, register, make_event, otp_limits):
    otp_limits(otp_max_attempts=3)
    registration_id = register(make_event().id).json()["registration_id"]
    code = sms.last_code

    for _ in range(3):
        response = verify(client, registration_id, wrong(code))
        assert response.status_code == 400
        assert response.json()["detail"] == "The code is incorrect or has expired"

    # The right code no longer works once the attempts are used up.
    assert verify(client, registration_id, code).status_code == 400


def test_code_is_single_use(client, sms, register, make_event):
    registration_id = register(make_event().id).json()["registration_id"]
    code = sms.last_code

    assert verify(client, registration_id, code).status_code == 200
    assert verify(client, registration_id, code).status_code == 400


def test_expired_code_is_rejected(client, sms, register, make_event, db_session):
    registration_id = register(make_event().id).json()["registration_id"]
    challenge = db_session.scalars(select(OtpChallenge)).one()
    challenge.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    assert verify(client, registration_id, sms.last_code).status_code == 400


def test_new_code_invalidates_the_previous_one(client, sms, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    registration_id = register(make_event().id).json()["registration_id"]
    old_code = sms.last_code
    assert resend(client, registration_id).status_code == 202
    if sms.last_code == old_code:
        pytest.skip("random codes collided")

    assert verify(client, registration_id, old_code).status_code == 400
    assert verify(client, registration_id, sms.last_code).status_code == 200


def test_resend_has_a_cooldown(client, sms, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=60)
    registration_id = register(make_event().id).json()["registration_id"]

    response = resend(client, registration_id)

    assert response.status_code == 429
    assert 0 < int(response.headers["retry-after"]) <= 60
    assert len(sms.sent) == 1


def test_per_mobile_hourly_cap(client, sms, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0, otp_max_per_mobile_per_hour=2)
    events = [make_event() for _ in range(3)]

    assert register(events[0].id).status_code == 202
    assert register(events[1].id).status_code == 202
    response = register(events[2].id)

    assert response.status_code == 429
    assert len(sms.sent) == 2


def test_per_ip_hourly_cap(client, sms, register, make_event, otp_limits):
    otp_limits(otp_max_per_ip_per_hour=2)
    event = make_event()

    assert register(event.id, mobile="9000000001").status_code == 202
    assert register(event.id, mobile="9000000002").status_code == 202
    response = register(event.id, mobile="9000000003")

    assert response.status_code == 429
    assert len(sms.sent) == 2


def test_rate_limited_registration_is_not_saved(client, sms, register, make_event, otp_limits, db_session):
    otp_limits(otp_max_per_ip_per_hour=1)
    event = make_event()
    register(event.id, mobile="9000000001")

    register(event.id, mobile="9000000002")

    assert len(db_session.scalars(select(Registration)).all()) == 1


def test_daily_sms_budget_pauses_sending(client, sms, register, make_event, otp_limits):
    otp_limits(sms_daily_budget=1)
    event = make_event()
    assert register(event.id, mobile="9000000001").status_code == 202

    response = register(event.id, mobile="9000000002")

    assert response.status_code == 503
    assert len(sms.sent) == 1


def test_failed_sms_does_not_use_up_quota(client, sms, register, make_event, otp_limits, db_session):
    otp_limits(otp_max_per_mobile_per_hour=1)
    event = make_event()
    sms.fail = True
    assert register(event.id).status_code == 503
    assert db_session.scalars(select(OtpChallenge)).all() == []

    sms.fail = False
    assert register(event.id).status_code == 202


def test_disabled_sms_provider_fails_closed(client, make_event):
    body = {"guest_name": "Asha", "mobile": "9876543210", "consent": True}

    response = client.post(f"{BASE}/events/{make_event().id}/registrations", json=body)

    assert response.status_code == 503
