"""Employee registration from an event's public link: party details, validation, duplicates and party capacity."""

import pytest
from sqlalchemy import select

from app.modules.guests.models import Registration, RegistrationGuest
from tests.guest_fixtures import registration_body

BASE = "/api/v1/public"


def verify(client, registration_id: str, code: str):
    return client.post(f"{BASE}/registrations/{registration_id}/verify", json={"code": code})


def active_guests(db_session) -> list[tuple[int, str]]:
    rows = db_session.scalars(
        select(RegistrationGuest).where(RegistrationGuest.deleted_at.is_(None)).order_by(RegistrationGuest.position)
    )
    return [(row.position, row.name) for row in rows]


# --- happy path ---------------------------------------------------------------


def test_employee_registers_with_guests_and_gets_one_pass_for_the_party(
    client, mailbox, register, make_event, db_session
):
    event = make_event()

    started = register(event.id, guests=["Ravi Patil", "Meera Patil"], employee_id="mt-104")
    assert started.status_code == 202, started.text
    body = verify(client, started.json()["registration_id"], mailbox.last_code).json()

    assert body["employee_id"] == "mt-104"
    assert body["employee_name"] == "Asha Patil"
    assert body["guest_names"] == ["Ravi Patil", "Meera Patil"]
    assert body["party_size"] == 3
    row = db_session.scalars(select(Registration)).one()
    assert (row.employee_id_normalized, row.number_of_guests) == ("MT-104", 2)
    assert active_guests(db_session) == [(0, "Ravi Patil"), (1, "Meera Patil")]
    assert mailbox.sent[0][0] == "asha.patil@example.com"  # the OTP goes to the email, never the mobile


def test_mobile_is_normalized_hashed_encrypted_and_masked(client, mailbox, register, make_event, db_session):
    register(make_event().id, mobile="+91 98765-43210")

    row = db_session.scalars(select(Registration)).one()
    assert row.mobile_masked == "98•••••210"
    assert "9876543210" not in row.mobile_hash and "9876543210" not in row.mobile_encrypted
    assert len(row.mobile_hash) == 64


@pytest.mark.parametrize("mobile", ["omitted", None, "", "   "])
def test_mobile_is_optional_and_email_verification_still_works(client, mailbox, make_event, db_session, mobile):
    event = make_event()
    body = registration_body()
    if mobile == "omitted":
        del body["mobile"]
    else:
        body["mobile"] = mobile

    started = client.post(f"{BASE}/events/{event.public_id}/registrations", json=body)

    assert started.status_code == 202, started.text
    row = db_session.scalars(select(Registration)).one()
    assert (row.mobile_hash, row.mobile_encrypted, row.mobile_masked) == (None, None, None)
    assert mailbox.sent[0][0] == body["email"]
    assert verify(client, started.json()["registration_id"], mailbox.last_code).status_code == 200


def test_pending_resubmission_can_clear_mobile(register, mailbox, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    first = register(event.id)
    second = register(event.id, mobile="")

    assert second.status_code == 202, second.text
    assert second.json()["registration_id"] == first.json()["registration_id"]
    row = db_session.scalars(select(Registration)).one()
    assert (row.mobile_hash, row.mobile_encrypted, row.mobile_masked) == (None, None, None)


def test_pass_details_are_opaque(client, issue_pass, make_event):
    guest_pass = issue_pass(make_event().id, guests=["Ravi Patil"])

    token = guest_pass["qr_token"]
    for secret in ("asha", "Ravi", "98765", "example"):
        assert secret.lower() not in token.lower()


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "employee_id", ["", " ", "MT 104", "MT/104", "-MT104", "MT<104>", "x" * 31, "MT\n104", "MT\x00104"]
)
def test_rejects_bad_employee_ids(register, mailbox, make_event, employee_id):
    assert register(make_event().id, employee_id=employee_id).status_code == 422
    assert mailbox.sent == []


@pytest.mark.parametrize("employee_id", ["MT-104", "mt_104.a", "7", " 10423 "])
def test_accepts_employee_ids_with_safe_characters(register, mailbox, make_event, employee_id):
    assert register(make_event().id, employee_id=employee_id).status_code == 202


@pytest.mark.parametrize("mobile", ["12345", "5876543210", "+1 415 555 0100", "98765432101", "98765abcde"])
def test_rejects_non_indian_or_malformed_mobiles(register, mailbox, make_event, mobile):
    assert register(make_event().id, mobile=mobile).status_code == 422
    assert mailbox.sent == []


@pytest.mark.parametrize("field", ["employee_id", "employee_name", "email", "attending", "consent"])
def test_required_fields(client, mailbox, make_event, field):
    body = registration_body()
    del body[field]

    response = client.post(f"{BASE}/events/{make_event().public_id}/registrations", json=body)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [{"number_of_guests": 1}, {"guest_names": ["Ravi Patil"]}],
)
def test_guest_count_fields_are_replaced_by_the_family_questions(register, mailbox, make_event, extra):
    # The party is described only by the family answers now; the old free-form guest fields are unknown.
    assert register(make_event().id, **extra).status_code == 422
    assert mailbox.sent == []


@pytest.mark.parametrize("name", ["R", "x" * 101, "Ravi\nPatil", "Ravi\x07", "   "])
def test_guest_names_are_validated_like_employee_names(register, mailbox, make_event, name):
    assert register(make_event().id, guests=[name]).status_code == 422
    assert register(make_event().id, name=name).status_code == 422


def test_guest_count_cannot_exceed_the_event_limit(register, mailbox, make_event):
    event = make_event(max_guests=1)

    response = register(event.id, guests=["Ravi Patil", "Meera Patil"])

    assert response.status_code == 422
    assert response.json()["detail"] == "You can bring at most 1 guests to this event"
    assert mailbox.sent == []


def test_event_can_allow_no_guests(register, mailbox, make_event):
    event = make_event(max_guests=0)

    assert register(event.id, guests=["Ravi Patil"]).status_code == 422
    assert register(event.id).status_code == 202


# --- duplicates and resubmission ----------------------------------------------


def test_one_registration_per_employee_per_event(client, mailbox, register, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    first = register(event.id, email="asha@example.com", employee_id="MT-104")
    assert verify(client, first.json()["registration_id"], mailbox.last_code).status_code == 200

    # Same employee id, any case, with another email: refused without mailing anyone.
    sent_before = len(mailbox.sent)
    response = register(event.id, email="someone.else@example.com", employee_id="mt-104")

    assert response.status_code == 409
    assert response.json()["detail"] == "This employee ID or email address is already registered for this event"
    assert "as•••" not in response.text
    assert len(mailbox.sent) == sent_before
    assert len(db_session.scalars(select(Registration)).all()) == 1


def test_one_registration_per_email_per_event(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    first = register(event.id, email="asha@example.com", employee_id="MT-104")
    assert verify(client, first.json()["registration_id"], mailbox.last_code).status_code == 200

    response = register(event.id, email="ASHA@example.com", employee_id="MT-999")

    assert response.status_code == 409


def test_employee_id_and_email_of_two_different_registrations_conflict(register, mailbox, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    register(event.id, email="asha@example.com", employee_id="MT-104")
    register(event.id, email="ravi@example.com", employee_id="MT-105")

    response = register(event.id, email="asha@example.com", employee_id="MT-105")

    assert response.status_code == 409


def test_same_employee_can_register_for_different_events(register, mailbox, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)

    assert register(make_event().id, employee_id="MT-104").status_code == 202
    assert register(make_event().id, employee_id="MT-104").status_code == 202


def test_pending_resubmission_updates_details_and_guests(client, mailbox, register, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    first = register(event.id, name="Asha", guests=["Ravi Patil", "Meera Patil", "Kiran Patil"])
    first_code = mailbox.last_code

    second = register(event.id, name="Asha Patil", guests=["Ravi P", "Meera Patil"], mobile="9123456789")

    assert second.json()["registration_id"] == first.json()["registration_id"]
    assert len(mailbox.sent) == 2  # a fresh OTP for the resubmission
    row = db_session.scalars(select(Registration)).one()
    assert (row.employee_name, row.number_of_guests, row.mobile_masked) == ("Asha Patil", 2, "91•••••789")
    assert active_guests(db_session) == [(0, "Ravi P"), (1, "Meera Patil")]
    # The dropped guest is soft-deleted, never hard-deleted.
    assert len(db_session.scalars(select(RegistrationGuest)).all()) == 3
    if first_code != mailbox.last_code:
        assert verify(client, row.public_id, first_code).status_code == 400
    assert verify(client, row.public_id, mailbox.last_code).json()["party_size"] == 3


def test_pending_resubmission_can_add_back_a_dropped_guest(register, mailbox, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    register(event.id, guests=["Ravi Patil", "Meera Patil"])
    register(event.id, guests=[])

    register(event.id, guests=["Kiran Patil", "Meera Patil"])

    assert active_guests(db_session) == [(0, "Kiran Patil"), (1, "Meera Patil")]
    assert len(db_session.scalars(select(RegistrationGuest)).all()) == 2


def test_pending_resubmission_can_correct_the_email(client, mailbox, register, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    first = register(event.id, email="asha@exmaple.com", employee_id="MT-104").json()["registration_id"]

    second = register(event.id, email="asha@example.com", employee_id="MT-104")

    assert second.json()["registration_id"] == first
    assert mailbox.sent[-1][0] == "asha@example.com"
    assert len(db_session.scalars(select(Registration)).all()) == 1


def test_verified_registration_is_not_changed_by_resubmitting(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    started = register(event.id, name="Asha Patil", guests=["Ravi Patil"])
    registration_id = started.json()["registration_id"]
    verify(client, registration_id, mailbox.last_code)

    again = register(event.id, name="Someone Else", guests=["A Stranger", "Another One"], mobile="9123456789")
    reissued = verify(client, registration_id, mailbox.last_code).json()

    assert again.status_code == 202  # the same employee and email may ask for their pass again
    assert again.json()["registration_id"] == registration_id
    assert (reissued["employee_name"], reissued["guest_names"]) == ("Asha Patil", ["Ravi Patil"])


# --- party capacity -------------------------------------------------------------


def test_seats_left_counts_people_not_registrations(client, issue_pass, make_event):
    event = make_event(capacity=10)
    issue_pass(event.id, email="asha@example.com", guests=["Ravi Patil", "Meera Patil"])
    issue_pass(event.id, email="kiran@example.com")

    assert client.get(f"{BASE}/events/{event.public_id}").json()["seats_left"] == 6


def test_pending_parties_do_not_take_seats(client, mailbox, register, make_event):
    event = make_event(capacity=3)
    register(event.id, email="asha@example.com", guests=["Ravi Patil", "Meera Patil"])

    assert client.get(f"{BASE}/events/{event.public_id}").json()["seats_left"] == 3
    assert register(event.id, email="kiran@example.com", guests=["Tara Shah", "Dev Shah"]).status_code == 202


def test_last_seats_go_to_a_party_that_fits_exactly(client, issue_pass, make_event):
    event = make_event(capacity=4)
    issue_pass(event.id, email="asha@example.com")

    guest_pass = issue_pass(event.id, email="kiran@example.com", guests=["Tara Shah", "Dev Shah"])

    assert guest_pass["party_size"] == 3
    assert client.get(f"{BASE}/events/{event.public_id}").json()["seats_left"] == 0


def test_party_larger_than_remaining_seats_is_refused_before_sending_a_code(register, mailbox, issue_pass, make_event):
    event = make_event(capacity=3)
    issue_pass(event.id, email="asha@example.com", guests=["Ravi Patil"])
    sent_before = len(mailbox.sent)

    response = register(event.id, email="kiran@example.com", guests=["Tara Shah"])

    assert response.status_code == 409
    assert len(mailbox.sent) == sent_before
    assert register(event.id, email="kiran@example.com").status_code == 202  # alone, they still fit


def test_party_that_no_longer_fits_at_verification_is_refused_whole(client, mailbox, register, make_event, db_session):
    event = make_event(capacity=3)
    party = register(event.id, email="asha@example.com", guests=["Ravi Patil", "Meera Patil"])
    party_code = mailbox.last_code
    solo = register(event.id, email="kiran@example.com")
    assert verify(client, solo.json()["registration_id"], mailbox.last_code).status_code == 200

    response = verify(client, party.json()["registration_id"], party_code)

    assert response.status_code == 409
    assert response.json()["detail"] == "This event does not have enough seats left for your party"
    row = db_session.scalars(select(Registration).where(Registration.number_of_guests == 2)).one()
    db_session.refresh(row)
    assert (row.status, row.qr_token_hash) == ("PENDING_OTP", None)
    assert client.get(f"{BASE}/events/{event.public_id}").json()["seats_left"] == 2


def test_lowered_guest_limit_is_rechecked_at_verification(client, mailbox, register, make_event, db_session):
    event = make_event(max_guests=3)
    started = register(event.id, guests=["Ravi Patil", "Meera Patil"])
    event.max_guests_per_registration = 1
    db_session.commit()

    response = verify(client, started.json()["registration_id"], mailbox.last_code)

    assert response.status_code == 422
