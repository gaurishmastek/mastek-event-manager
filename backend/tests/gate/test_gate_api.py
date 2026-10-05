from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.mixins import utcnow
from app.modules.gate.models import CheckIn, GuestEntry, ScanAttempt
from app.modules.guests.models import Registration
from tests.gate.helpers import admit, admit_everyone, decide, scan

# --- scanning only looks the pass up; the officer's approval admits ---------------


def test_scan_shows_the_party_and_admits_nobody(client, issue_pass, live_event, officer, db_session):
    guest_pass = issue_pass(live_event.id)

    response = scan(client, live_event.id, guest_pass["qr_token"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "pending_verification"
    assert body["guest"] == {
        "name": "Asha Patil",
        "contact": "as•••@example.com",
        "employee_id": "asha.patil",
        "guest_names": [],
        "party_size": 1,
        "email_masked": "as•••@example.com",
        "mobile_masked": "98•••••210",
        "employee_entered": False,
        "members": [],
    }
    assert (body["checked_in_at"], body["gate"], body["people_entered"]) == (None, None, None)
    assert db_session.scalars(select(CheckIn)).all() == []
    registration = db_session.scalars(select(Registration)).one()
    assert registration.status == "VERIFIED"


def test_approval_admits_the_employee_and_records_the_entry(client, issue_pass, live_event, officer, db_session):
    guest_pass = issue_pass(live_event.id)

    response = admit(client, live_event.id, guest_pass["qr_token"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "admitted"
    assert body["gate"] == "Gate 1"
    assert body["people_entered"] == 1
    check_in = db_session.scalars(select(CheckIn)).one()
    assert (check_in.officer_id, check_in.event_id, check_in.method) == (42, live_event.id, "QR")
    registration = db_session.scalars(select(Registration)).one()
    db_session.refresh(registration)
    assert registration.status == "CHECKED_IN"
    assert registration.updated_by == 42


def test_used_pass_is_not_admitted_again(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id)["qr_token"]
    admit(client, live_event.id, token, gate="Gate 1")

    scanned = scan(client, live_event.id, token, gate="Gate 2").json()
    approved_again = admit(client, live_event.id, token, gate="Gate 2").json()

    for body in (scanned, approved_again):
        assert body["result"] == "already_checked_in"
        assert body["message"] == "This pass has already been used"
        assert body["gate"] == "Gate 1"
        assert body["checked_in_at"]
        assert body["guest"]["name"] == "Asha Patil"
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_old_pass_stops_working_after_reissue(client, issue_pass, live_event, officer):
    old = issue_pass(live_event.id)["qr_token"]
    new = issue_pass(live_event.id)["qr_token"]

    assert scan(client, live_event.id, old).json()["result"] == "invalid"
    assert scan(client, live_event.id, new).json()["result"] == "pending_verification"


def test_checked_in_guest_cannot_get_a_new_pass(client, mailbox, issue_pass, register, live_event, officer):
    token = issue_pass(live_event.id)["qr_token"]
    admit(client, live_event.id, token)

    response = register(live_event.id)

    assert response.status_code == 409


def test_unknown_token_is_invalid(client, live_event, officer):
    expected = {
        "result": "invalid",
        "message": "This pass is not valid",
        "guest": None,
        "checked_in_at": None,
        "gate": None,
        "people_entered": None,
    }

    assert scan(client, live_event.id, "A" * 43).json() == expected
    assert decide(client, live_event.id, "A" * 43, employee_id_checked=True).json() == expected


def test_pass_for_another_event_is_rejected_without_guest_details(
    client, issue_pass, make_event, live_event, login_as, assign_officer
):
    other = make_event(starts_in=timedelta(minutes=10))
    token = issue_pass(other.id)["qr_token"]
    assign_officer(live_event.id, other.id)
    login_as("security_officer", user_id=42)

    body = scan(client, live_event.id, token).json()

    assert body["result"] == "wrong_event"
    assert body["guest"] is None
    assert decide(client, live_event.id, token, employee_id_checked=True).json()["result"] == "wrong_event"
    # The pass still works at its own event.
    assert admit(client, other.id, token).json()["result"] == "admitted"


@pytest.mark.parametrize(
    "token", ["", "short", "has spaces in it and is long enough", "x" * 129, "abc/def+ghi=jkl==mnop"]
)
def test_malformed_token_is_rejected_before_lookup(client, live_event, officer, token):
    assert scan(client, live_event.id, token).status_code == 422
    assert decide(client, live_event.id, token, employee_id_checked=True).status_code == 422


def test_scanning_outside_the_gate_window(client, issue_pass, make_event, login_as, assign_officer):
    event = make_event(starts_in=timedelta(days=2))
    token = issue_pass(event.id)["qr_token"]
    assign_officer(event.id)
    login_as("security_officer", user_id=42)

    assert scan(client, event.id, token).json()["result"] == "gate_closed"
    assert decide(client, event.id, token, employee_id_checked=True).json()["result"] == "gate_closed"


def test_every_scan_and_decision_is_logged_without_the_token(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id)["qr_token"]
    scan(client, live_event.id, token)
    admit(client, live_event.id, token)
    scan(client, live_event.id, token)
    scan(client, live_event.id, "B" * 43)

    attempts = db_session.scalars(select(ScanAttempt).order_by(ScanAttempt.id)).all()

    # admit() scans first, so the pass is looked up twice before it is approved.
    assert [a.result for a in attempts] == [
        "pending_verification",
        "pending_verification",
        "admitted",
        "already_checked_in",
        "invalid",
    ]
    assert all(a.officer_id == 42 and a.gate == "Gate 1" for a in attempts)
    assert attempts[4].registration_id is None


# --- access control ----------------------------------------------------------


def test_scan_and_decision_require_login(client, live_event):
    assert scan(client, live_event.id, "A" * 43).status_code == 401
    assert decide(client, live_event.id, "A" * 43, employee_id_checked=True).status_code == 401


@pytest.mark.parametrize("role", ["guest", "event_manager", "security"])
def test_other_roles_cannot_scan_or_decide(client, login_as, live_event, role):
    login_as(role)

    assert scan(client, live_event.id, "A" * 43).status_code == 403
    assert decide(client, live_event.id, "A" * 43, employee_id_checked=True).status_code == 403


def test_officer_cannot_scan_or_decide_for_unassigned_event(client, issue_pass, make_event, officer, db_session):
    other = make_event(starts_in=timedelta(minutes=10))
    token = issue_pass(other.id)["qr_token"]

    assert scan(client, other.id, token).status_code == 404
    assert decide(client, other.id, token, employee_id_checked=True).status_code == 404
    assert db_session.scalars(select(CheckIn)).all() == []


def test_removed_assignment_revokes_gate_access(client, login_as, assign_officer, live_event, db_session):
    (assignment,) = assign_officer(live_event.id, officer_id=7)
    assignment.deleted_at = utcnow()
    db_session.commit()
    login_as("security_officer", user_id=7)

    assert scan(client, live_event.id, "A" * 43).status_code == 404
    assert decide(client, live_event.id, "A" * 43, employee_id_checked=True).status_code == 404


def test_assignment_is_per_officer(client, login_as, live_event, officer):
    login_as("security_officer", user_id=43)

    assert scan(client, live_event.id, "A" * 43).status_code == 404


def test_admin_can_scan_and_decide_for_any_event(client, issue_pass, login_as, live_event):
    token = issue_pass(live_event.id)["qr_token"]
    login_as("admin", user_id=1)

    assert scan(client, live_event.id, token).json()["result"] == "pending_verification"
    assert admit(client, live_event.id, token).json()["result"] == "admitted"


def test_deleted_event_is_404(client, live_event, officer, db_session):
    live_event.deleted_at = utcnow()
    db_session.commit()

    assert scan(client, live_event.id, "A" * 43).status_code == 404
    assert decide(client, live_event.id, "A" * 43, employee_id_checked=True).status_code == 404


# --- entry list ----------------------------------------------------------------


def test_entries_lists_checked_in_guests(client, issue_pass, live_event, officer):
    admit(client, live_event.id, issue_pass(live_event.id, email="guest01@example.com", name="Ravi")["qr_token"])
    admit(client, live_event.id, issue_pass(live_event.id, email="guest02@example.com", name="Meera")["qr_token"])
    scan(client, live_event.id, issue_pass(live_event.id, email="guest03@example.com", name="Scanned only")["qr_token"])
    issue_pass(live_event.id, email="guest04@example.com", name="Not arrived")

    response = client.get(f"/api/v1/gate/events/{live_event.id}/entries")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["guest"]["name"] for item in body["items"]} == {"Ravi", "Meera"}
    assert body["items"][0]["guest"]["contact"].startswith("gu•••@")


def test_entries_respect_event_scope(client, make_event, officer):
    other = make_event()

    assert client.get(f"/api/v1/gate/events/{other.id}/entries").status_code == 404


# --- employee parties ---------------------------------------------------------


def test_scan_lists_the_party_and_the_approval_admits_everyone_ticked(
    client, issue_pass, live_event, officer, db_session
):
    token = issue_pass(live_event.id, guests=["Ravi Patil", "Meera Patil"], employee_id="MT-104")["qr_token"]

    scanned = scan(client, live_event.id, token).json()

    assert scanned["result"] == "pending_verification"
    guest = scanned["guest"]
    assert (guest["employee_id"], guest["name"], guest["party_size"]) == ("MT-104", "Asha Patil", 3)
    assert guest["guest_names"] == ["Ravi Patil", "Meera Patil"]
    assert (guest["email_masked"], guest["mobile_masked"]) == ("as•••@example.com", "98•••••210")
    assert [(m["name"], m["type"], m["age"], m["entered"]) for m in guest["members"]] == [
        ("Ravi Patil", "ADULT", None, False),
        ("Meera Patil", "KID", 8, False),
    ]
    assert "asha.patil@example.com" not in str(scanned) and "9876543210" not in str(scanned)
    assert db_session.scalars(select(CheckIn)).all() == []

    admitted = admit_everyone(client, live_event.id, token).json()

    assert admitted["result"] == "admitted"
    assert admitted["people_entered"] == 3
    assert all(m["entered"] for m in admitted["guest"]["members"])
    assert len(db_session.scalars(select(CheckIn)).all()) == 1
    assert len(db_session.scalars(select(GuestEntry)).all()) == 2


def test_fully_used_party_pass_shows_details_and_original_entry(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id, guests=["Ravi Patil"])["qr_token"]
    admit_everyone(client, live_event.id, token, gate="North gate")

    body = scan(client, live_event.id, token, gate="South gate").json()

    assert body["result"] == "already_checked_in"
    assert (body["guest"]["party_size"], body["guest"]["guest_names"]) == (2, ["Ravi Patil"])
    assert body["gate"] == "North gate" and body["checked_in_at"]
    assert body["people_entered"] == 2
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_wrong_event_and_invalid_scans_leak_no_party_details(
    client, issue_pass, make_event, live_event, login_as, assign_officer
):
    other = make_event(starts_in=timedelta(minutes=10))
    token = issue_pass(other.id, guests=["Ravi Patil"], employee_id="MT-104")["qr_token"]
    assign_officer(live_event.id)
    login_as("security_officer", user_id=42)

    responses = (
        scan(client, live_event.id, token),
        scan(client, live_event.id, "B" * 43),
        decide(client, live_event.id, token, employee_id_checked=True),
        decide(client, live_event.id, "B" * 43, decision="reject", reason="ID_MISMATCH"),
    )
    for response in responses:
        assert response.json()["guest"] is None
        for detail in ("MT-104", "Asha", "Ravi", "•••"):
            assert detail not in response.text


def test_unassigned_officer_learns_nothing_about_the_party(client, issue_pass, make_event, login_as, assign_officer):
    event = make_event(starts_in=timedelta(minutes=10))
    token = issue_pass(event.id, guests=["Ravi Patil"])["qr_token"]
    login_as("security_officer", user_id=43)  # assigned to nothing

    for response in (scan(client, event.id, token), decide(client, event.id, token, employee_id_checked=True)):
        assert response.status_code == 404
        assert "Ravi" not in response.text and "Asha" not in response.text


def test_pending_registration_has_no_pass_to_scan(client, mailbox, register, live_event, officer, db_session):
    register(live_event.id)

    registration = db_session.scalars(select(Registration)).one()
    assert registration.qr_token_hash is None


# --- server-side check-in time, races, token handling ---------------------------------


def test_check_in_time_comes_from_the_server(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id, guests=["Ravi Patil"])["qr_token"]
    guest_ids = [m["id"] for m in scan(client, live_event.id, token).json()["guest"]["members"]]
    forged = client.post(
        f"/api/v1/gate/events/{live_event.id}/decision",
        json={
            "token": token,
            "decision": "approve",
            "employee_id_checked": True,
            "checked_in_at": "2000-01-01T00:00:00Z",
        },
    )
    assert forged.status_code == 422

    before = utcnow()
    body = decide(client, live_event.id, token, employee_id_checked=True, guest_ids_entered=guest_ids).json()
    after = utcnow()

    check_in = db_session.scalars(select(CheckIn)).one()
    guest_entry = db_session.scalars(select(GuestEntry)).one()
    assert before <= check_in.checked_in_at <= after
    assert before <= guest_entry.entered_at <= after
    assert body["checked_in_at"] == check_in.checked_in_at.isoformat()


def test_losing_a_concurrent_approval_reports_the_winners_entry(
    client, issue_pass, live_event, officer, db_session, monkeypatch
):
    """Two gates approve one pass at once: the atomic UPDATE lets one win; the other sees the winner's entry."""
    from app.modules.guests.repository import RegistrationRepository

    token = issue_pass(live_event.id)["qr_token"]
    real_check_in = RegistrationRepository.check_in

    def other_gate_wins(self, **kwargs):
        # The other gate's request commits first; ours then matches no VERIFIED row.
        assert real_check_in(self, **{**kwargs, "officer_id": 99})
        registration = db_session.scalars(select(Registration)).one()
        db_session.add(
            CheckIn(
                registration_id=registration.id,
                event_id=live_event.id,
                officer_id=99,
                gate="East gate",
                checked_in_at=kwargs["at"],
            )
        )
        db_session.commit()
        return real_check_in(self, **kwargs)

    monkeypatch.setattr(RegistrationRepository, "check_in", other_gate_wins)
    body = decide(client, live_event.id, token, gate="West gate", employee_id_checked=True).json()

    assert body["result"] == "already_checked_in"
    assert body["gate"] == "East gate"
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_unique_index_is_the_last_guard_against_double_entry(client, issue_pass, live_event, officer, db_session):
    """Even if the status guard were bypassed, the unique registration_id stops a second check-in row."""
    token = issue_pass(live_event.id)["qr_token"]
    admit(client, live_event.id, token)
    registration = db_session.scalars(select(Registration)).one()
    registration.status = "VERIFIED"
    db_session.commit()

    body = admit(client, live_event.id, token).json()

    assert body["result"] != "admitted"
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_gate_closed_decision_admits_nobody_and_shows_nothing(
    client, issue_pass, make_event, login_as, assign_officer, db_session
):
    event = make_event(starts_in=timedelta(days=2))
    token = issue_pass(event.id)["qr_token"]
    assign_officer(event.id)
    login_as("security_officer", user_id=42)

    body = decide(client, event.id, token, employee_id_checked=True).json()

    assert (body["result"], body["guest"], body["checked_in_at"]) == ("gate_closed", None, None)
    assert db_session.scalars(select(CheckIn)).all() == []
    assert db_session.scalars(select(Registration)).one().status == "VERIFIED"


def test_scan_attempts_never_store_the_raw_token(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id)["qr_token"]
    admit(client, live_event.id, token)
    scan(client, live_event.id, "C" * 43)

    for attempt in db_session.scalars(select(ScanAttempt)):
        assert token not in repr(vars(attempt))
        assert "C" * 43 not in repr(vars(attempt))


def test_removed_assignment_also_hides_entry_history(
    client, issue_pass, login_as, assign_officer, live_event, db_session
):
    token = issue_pass(live_event.id)["qr_token"]
    (assignment,) = assign_officer(live_event.id, officer_id=7)
    login_as("security_officer", user_id=7)
    assert admit(client, live_event.id, token).json()["result"] == "admitted"
    assert client.get(f"/api/v1/gate/events/{live_event.id}/entries").status_code == 200

    assignment.deleted_at = utcnow()
    db_session.commit()

    assert client.get(f"/api/v1/gate/events/{live_event.id}/entries").status_code == 404
    assert client.get(f"/api/v1/events/{live_event.id}").status_code == 404
