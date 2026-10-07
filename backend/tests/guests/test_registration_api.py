from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.crypto import token_hash
from app.db.mixins import utcnow
from app.modules.guests.models import Registration
from app.modules.otp.models import OtpChallenge
from tests.guest_fixtures import registration_body

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

    response = client.get(f"{BASE}/events/{event.public_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Navratri Garba Night"
    assert body["public_id"] == event.public_id
    assert body["registration_open"] is True
    assert body["seats_left"] == 50
    assert body["max_guests_per_registration"] == 5
    assert "created_by" not in body and "id" not in body


def test_register_emails_otp_and_masks_address(client, mailbox, register, make_event):
    event = make_event()

    response = register(event.id, email=" Asha.Patil@Example.com ")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["email"] == "as•••@example.com"
    assert "code" not in response.text and mailbox.last_code not in response.text
    assert mailbox.sent == [("asha.patil@example.com", mailbox.last_code)]
    _, subject, text = mailbox.messages[0]
    assert subject == "Your event registration code"
    assert "expires in 5 minutes" in text
    assert response.headers["cache-control"] == "no-store"


def test_verify_issues_a_random_pass_stored_only_as_hash(client, mailbox, register, make_event, db_session):
    event = make_event()
    registration_id = register(event.id).json()["registration_id"]

    response = verify(client, registration_id, mailbox.last_code)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "VERIFIED"
    assert body["event"]["public_id"] == event.public_id and "id" not in body["event"]
    assert len(body["qr_token"]) >= 43
    assert body["qr_svg"].startswith("data:image/svg+xml")
    row = db_session.scalars(select(Registration)).one()
    assert row.qr_token_hash == token_hash(body["qr_token"])
    assert body["qr_token"] not in (row.qr_token_hash, row.email_encrypted)
    assert "asha" not in row.email_encrypted and "asha" not in row.email_hash
    assert "9876543210" not in (row.mobile_hash, row.mobile_encrypted) and row.mobile_masked == "98•••••210"


def test_otp_is_stored_only_as_hmac(client, mailbox, register, make_event, db_session):
    register(make_event().id)

    challenge = db_session.scalars(select(OtpChallenge)).one()
    assert mailbox.last_code not in challenge.code_hmac
    assert len(challenge.code_hmac) == 64


def test_reverifying_reissues_pass_and_voids_the_old_one(client, mailbox, register, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    registration_id = register(event.id).json()["registration_id"]
    first = verify(client, registration_id, mailbox.last_code).json()["qr_token"]

    assert register(event.id).json()["registration_id"] == registration_id
    second = verify(client, registration_id, mailbox.last_code).json()["qr_token"]

    assert first != second
    row = db_session.scalars(select(Registration)).one()
    db_session.refresh(row)
    assert row.qr_token_hash == token_hash(second)


def test_same_email_reuses_registration_and_pending_name_is_updated(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    first = register(event.id, name="Asha").json()["registration_id"]

    second = register(event.id, name="Asha Patil").json()["registration_id"]
    body = verify(client, second, mailbox.last_code).json()

    assert first == second
    assert body["employee_name"] == "Asha Patil"


# --- input validation ------------------------------------------------------


def test_email_is_case_insensitive_for_the_same_registration(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()

    first = register(event.id, email="asha@example.com").json()["registration_id"]
    second = register(event.id, email="ASHA@Example.com").json()["registration_id"]

    assert first == second


@pytest.mark.parametrize(
    "email", ["asha", "asha@", "@example.com", "asha@example", "a b@example.com", "asha@example.com\r\nBcc: x@y.z"]
)
def test_rejects_malformed_emails(register, mailbox, make_event, email):
    response = register(make_event().id, email=email)

    assert response.status_code == 422
    assert mailbox.sent == []


def test_requires_consent(register, mailbox, make_event):
    response = register(make_event().id, consent=False)

    assert response.status_code == 422


def test_rejects_unknown_fields_and_control_characters(register, mailbox, make_event):
    event = make_event()

    assert register(event.id, status="VERIFIED").status_code == 422
    assert register(event.id, guest_name="Asha").status_code == 422
    assert register(event.id, name="Asha\x00").status_code == 422
    assert register(event.id, name="x" * 101).status_code == 422


def test_verify_rejects_non_numeric_code(client, mailbox, register, make_event):
    registration_id = register(make_event().id).json()["registration_id"]

    assert verify(client, registration_id, "12a456").status_code == 422
    assert verify(client, registration_id, "1234567").status_code == 422


def test_unknown_or_malformed_registration_id(client, mailbox):
    assert verify(client, "00000000-0000-0000-0000-000000000000", "123456").status_code == 404
    assert verify(client, "1", "123456").status_code == 422


# --- event state -------------------------------------------------------------


def test_unknown_or_deleted_event_is_404(register, mailbox, make_event, db_session):
    event = make_event()
    event.deleted_at = utcnow()
    db_session.commit()

    assert register(event.id).status_code == 404
    assert register(999).status_code == 404


def test_registration_closes_when_event_ends(register, mailbox, make_event):
    event = make_event(starts_in=timedelta(hours=-6), duration=timedelta(hours=5))

    response = register(event.id)

    assert response.status_code == 409
    assert mailbox.sent == []


def test_full_event_rejects_new_guests_before_sending_sms(register, mailbox, issue_pass, make_event):
    event = make_event(capacity=1)
    issue_pass(event.id, email="asha.patil@example.com")
    sent_before = len(mailbox.sent)

    response = register(event.id, email="ravi@example.com")

    assert response.status_code == 409
    assert response.json()["detail"] == "This event does not have enough seats left for your party"
    assert len(mailbox.sent) == sent_before


def test_unverified_registrations_do_not_take_seats(client, mailbox, register, make_event):
    event = make_event(capacity=1)
    register(event.id, email="asha.patil@example.com")

    assert client.get(f"{BASE}/events/{event.public_id}").json()["seats_left"] == 1
    assert register(event.id, email="ravi@example.com").status_code == 202


def test_capacity_is_checked_at_verification(client, mailbox, register, make_event):
    event = make_event(capacity=1)
    first = register(event.id, email="asha.patil@example.com").json()["registration_id"]
    first_code = mailbox.last_code
    second = register(event.id, email="ravi@example.com").json()["registration_id"]
    assert verify(client, second, mailbox.last_code).status_code == 200

    response = verify(client, first, first_code)

    assert response.status_code == 409
    assert response.json()["detail"] == "This event does not have enough seats left for your party"


# --- OTP abuse limits --------------------------------------------------------


def test_wrong_code_is_rejected_and_attempts_are_limited(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_max_attempts=3)
    registration_id = register(make_event().id).json()["registration_id"]
    code = mailbox.last_code

    for _ in range(3):
        response = verify(client, registration_id, wrong(code))
        assert response.status_code == 400
        assert response.json()["detail"] == "The code is incorrect or has expired"

    # The right code no longer works once the attempts are used up.
    assert verify(client, registration_id, code).status_code == 400


def test_code_is_single_use(client, mailbox, register, make_event):
    registration_id = register(make_event().id).json()["registration_id"]
    code = mailbox.last_code

    assert verify(client, registration_id, code).status_code == 200
    assert verify(client, registration_id, code).status_code == 400


def test_expired_code_is_rejected(client, mailbox, register, make_event, db_session):
    registration_id = register(make_event().id).json()["registration_id"]
    challenge = db_session.scalars(select(OtpChallenge)).one()
    challenge.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    assert verify(client, registration_id, mailbox.last_code).status_code == 400


def test_new_code_invalidates_the_previous_one(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    registration_id = register(make_event().id).json()["registration_id"]
    old_code = mailbox.last_code
    assert resend(client, registration_id).status_code == 202
    if mailbox.last_code == old_code:
        pytest.skip("random codes collided")

    assert verify(client, registration_id, old_code).status_code == 400
    assert verify(client, registration_id, mailbox.last_code).status_code == 200


def test_resend_has_a_cooldown(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=60)
    registration_id = register(make_event().id).json()["registration_id"]

    response = resend(client, registration_id)

    assert response.status_code == 429
    assert 0 < int(response.headers["retry-after"]) <= 60
    assert len(mailbox.sent) == 1


def test_per_email_hourly_cap(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0, otp_max_per_email_per_hour=2)
    events = [make_event() for _ in range(3)]

    assert register(events[0].id).status_code == 202
    assert register(events[1].id).status_code == 202
    response = register(events[2].id)

    assert response.status_code == 429
    assert len(mailbox.sent) == 2


def test_per_ip_hourly_cap(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_max_per_ip_per_hour=2)
    event = make_event()

    assert register(event.id, email="guest01@example.com").status_code == 202
    assert register(event.id, email="guest02@example.com").status_code == 202
    response = register(event.id, email="guest03@example.com")

    assert response.status_code == 429
    assert len(mailbox.sent) == 2


def test_rate_limited_registration_is_not_saved(client, mailbox, register, make_event, otp_limits, db_session):
    otp_limits(otp_max_per_ip_per_hour=1)
    event = make_event()
    register(event.id, email="guest01@example.com")

    register(event.id, email="guest02@example.com")

    assert len(db_session.scalars(select(Registration)).all()) == 1


def test_daily_sms_budget_pauses_sending(client, mailbox, register, make_event, otp_limits):
    otp_limits(email_daily_budget=1)
    event = make_event()
    assert register(event.id, email="guest01@example.com").status_code == 202

    response = register(event.id, email="guest02@example.com")

    assert response.status_code == 503
    assert len(mailbox.sent) == 1


def test_failed_sms_does_not_use_up_quota(client, mailbox, register, make_event, otp_limits, db_session):
    otp_limits(otp_max_per_email_per_hour=1)
    event = make_event()
    mailbox.fail = True
    assert register(event.id).status_code == 503
    assert db_session.scalars(select(OtpChallenge)).all() == []

    mailbox.fail = False
    assert register(event.id).status_code == 202


def test_disabled_sms_provider_fails_closed(client, make_event):
    response = client.post(f"{BASE}/events/{make_event().public_id}/registrations", json=registration_body())

    assert response.status_code == 503


def test_pre_email_registration_asks_guest_to_register_again(client, mailbox, make_event, db_session):
    event = make_event()
    legacy = Registration(
        public_id="00000000-0000-4000-8000-000000000001",
        event_id=event.id,
        employee_name="Old Guest",
        mobile_hash="h" * 64,
        mobile_encrypted="encrypted",
        mobile_masked="98•••••210",
        consent_at=utcnow(),
    )
    db_session.add(legacy)
    db_session.commit()

    response = resend(client, legacy.public_id)

    assert response.status_code == 409
    assert "email" in response.json()["detail"]
    assert mailbox.sent == []


def test_closed_registration_shows_not_open_and_rejects_new_sign_ups(client, make_event, db_session):
    event = make_event()
    event.registration_open = False
    db_session.commit()

    info = client.get(f"{BASE}/events/{event.public_id}")
    assert info.status_code == 200
    assert info.json()["registration_open"] is False

    response = client.post(f"{BASE}/events/{event.public_id}/registrations", json=registration_body())
    assert response.status_code == 409
    assert "closed" in response.json()["detail"]


def test_closing_registration_blocks_unverified_sign_ups_from_verifying(client, make_event, db_session, mailbox):
    event = make_event()
    created = client.post(f"{BASE}/events/{event.public_id}/registrations", json=registration_body())
    assert created.status_code == 202
    registration_id = created.json()["registration_id"]
    code = mailbox.last_code

    event.registration_open = False
    db_session.commit()

    assert verify(client, registration_id, code).status_code == 409
