"""Admin corrections and replacement QR passes never expose OTPs or raw contact data."""

from sqlalchemy import select

from app.core.crypto import keyed_hash
from app.db.mixins import utcnow
from app.modules.guests.models import Registration, RegistrationStatus
from app.modules.otp.models import OtpChallenge


def registrations_url(event_id: int, registration_id: str = "") -> str:
    suffix = f"/{registration_id}" if registration_id else ""
    return f"/api/v1/events/{event_id}/registrations{suffix}"


def update_body(**overrides):
    body = {
        "employee_id": "MT-999",
        "employee_name": "Asha Rao",
        "adult_name": "Ravi Rao",
        "kid_names": ["Mira Rao"],
        "kid_ages": [9],
    }
    body.update(overrides)
    return body


def test_admin_can_correct_registration_and_replace_email_without_sending_otp(
    client, db_session, issue_pass, login_as, mailbox, make_event
):
    event = make_event(capacity=10)
    issued = issue_pass(event.id, guests=["Ravi Patil", "Mira Patil"], employee_id="MT-104")
    login_as("admin", user_id=7)
    sent_before = len(mailbox.sent)

    response = client.patch(
        registrations_url(event.id, issued["registration_id"]),
        json=update_body(email="asha.rao@example.com"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["employee_id"] == "MT-999"
    assert body["employee_name"] == "Asha Rao"
    assert body["email_masked"] == "as•••@example.com"
    assert body["adult_name"] == "Ravi Rao"
    assert body["kid_names"] == ["Mira Rao"]
    assert body["kid_ages"] == [9]
    assert "asha.rao@example.com" not in response.text
    assert len(mailbox.sent) == sent_before

    registration = db_session.scalar(select(Registration).where(Registration.public_id == issued["registration_id"]))
    assert registration is not None
    assert registration.email_hash == keyed_hash("asha.rao@example.com", purpose="email")
    assert registration.updated_by == 7


def test_email_correction_invalidates_only_the_existing_pending_otp(
    client, db_session, login_as, mailbox, make_event, register
):
    event = make_event()
    started = register(event.id, employee_id="MT-104")
    registration_id = started.json()["registration_id"]
    challenge = db_session.scalar(select(OtpChallenge).where(OtpChallenge.subject_ref == registration_id))
    assert challenge is not None and challenge.invalidated_at is None
    login_as("admin")

    response = client.patch(
        registrations_url(event.id, registration_id), json=update_body(email="new.address@example.com")
    )

    assert response.status_code == 200, response.text
    db_session.refresh(challenge)
    assert challenge.invalidated_at is not None


def test_update_rejects_duplicate_identity_or_capacity_overflow(client, issue_pass, login_as, make_event):
    event = make_event(capacity=2)
    first = issue_pass(event.id, email="first@example.com", employee_id="MT-1")
    issue_pass(event.id, email="second@example.com", employee_id="MT-2")
    login_as("admin")

    duplicate = client.patch(
        registrations_url(event.id, first["registration_id"]), json=update_body(employee_id="MT-2")
    )
    full = client.patch(
        registrations_url(event.id, first["registration_id"]),
        json=update_body(employee_id="MT-10", adult_name="Ravi Rao"),
    )

    assert duplicate.status_code == 409
    assert full.status_code == 409


def test_checked_in_guest_details_are_locked_but_identity_correction_is_allowed(
    client, db_session, issue_pass, login_as, make_event
):
    event = make_event()
    issued = issue_pass(event.id, guests=["Ravi Patil"], employee_id="MT-104")
    registration = db_session.scalar(select(Registration).where(Registration.public_id == issued["registration_id"]))
    assert registration is not None
    registration.status = RegistrationStatus.CHECKED_IN.value
    registration.checked_in_at = utcnow()
    db_session.commit()
    login_as("admin")

    identity = client.patch(
        registrations_url(event.id, issued["registration_id"]),
        json=update_body(adult_name="Ravi Patil", kid_names=[], kid_ages=[]),
    )
    guest_change = client.patch(
        registrations_url(event.id, issued["registration_id"]),
        json=update_body(adult_name="Changed Guest", kid_names=[], kid_ages=[]),
    )

    assert identity.status_code == 200, identity.text
    assert guest_change.status_code == 409


def test_admin_can_download_replacement_qr_only_for_verified_registration(
    client, db_session, issue_pass, login_as, make_event
):
    event = make_event()
    issued = issue_pass(event.id)
    registration = db_session.scalar(select(Registration).where(Registration.public_id == issued["registration_id"]))
    assert registration is not None
    old_hash = registration.qr_token_hash
    login_as("admin")

    response = client.post(f"{registrations_url(event.id, issued['registration_id'])}/qr", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registration_id"] == issued["registration_id"]
    assert body["qr_svg"].startswith("data:image/svg+xml")
    assert issued["qr_token"] not in response.text
    db_session.refresh(registration)
    assert registration.qr_token_hash != old_hash
    assert registration.updated_by == 1

    registration.status = RegistrationStatus.CHECKED_IN.value
    db_session.commit()
    unavailable = client.post(f"{registrations_url(event.id, issued['registration_id'])}/qr", json={})
    assert unavailable.status_code == 409


def test_registration_edit_and_qr_are_admin_only(client, issue_pass, login_as, make_event):
    event = make_event()
    issued = issue_pass(event.id)
    endpoint = registrations_url(event.id, issued["registration_id"])

    assert client.patch(endpoint, json=update_body()).status_code == 401
    assert client.post(f"{endpoint}/qr", json={}).status_code == 401
    login_as("security_officer", user_id=44)
    assert client.patch(endpoint, json=update_body()).status_code == 403
    assert client.post(f"{endpoint}/qr", json={}).status_code == 403
