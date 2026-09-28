from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.mixins import utcnow
from app.modules.events.models import OfficerEvent
from app.modules.gate.models import CheckIn, ScanAttempt
from app.modules.guests.models import Registration


def scan(client, event_id: int, token: str, gate: str | None = "Gate 1"):
    body = {"token": token} if gate is None else {"token": token, "gate": gate}
    return client.post(f"/api/v1/gate/events/{event_id}/scan", json=body)


@pytest.fixture()
def assign_officer(db_session):
    def _assign(*event_ids: int, officer_id: int = 42) -> list[OfficerEvent]:
        rows = [OfficerEvent(officer_id=officer_id, event_id=event_id) for event_id in event_ids]
        db_session.add_all(rows)
        db_session.commit()
        return rows

    return _assign


@pytest.fixture()
def live_event(make_event):
    """An event whose gate is open now."""
    return make_event(starts_in=timedelta(minutes=30))


@pytest.fixture()
def officer(login_as, assign_officer, live_event):
    assign_officer(live_event.id)
    return login_as("security_officer", user_id=42)


# --- admitting guests ------------------------------------------------------


def test_valid_pass_admits_guest_and_records_entry(client, issue_pass, live_event, officer, db_session):
    guest_pass = issue_pass(live_event.id)

    response = scan(client, live_event.id, guest_pass["qr_token"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "admitted"
    assert body["guest"] == {
        "name": "Asha Patil",
        "contact": "as•••@example.com",
        "employee_id": "asha.patil",
        "guest_names": [],
        "party_size": 1,
        "email_masked": "as•••@example.com",
        "mobile_masked": "98•••••210",
    }
    assert body["gate"] == "Gate 1"
    check_in = db_session.scalars(select(CheckIn)).one()
    assert (check_in.officer_id, check_in.event_id, check_in.method) == (42, live_event.id, "QR")
    registration = db_session.scalars(select(Registration)).one()
    db_session.refresh(registration)
    assert registration.status == "CHECKED_IN"
    assert registration.updated_by == 42


def test_pass_is_single_use(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id)["qr_token"]
    scan(client, live_event.id, token, gate="Gate 1")

    response = scan(client, live_event.id, token, gate="Gate 2")

    body = response.json()
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
    assert scan(client, live_event.id, new).json()["result"] == "admitted"


def test_checked_in_guest_cannot_get_a_new_pass(client, mailbox, issue_pass, register, live_event, officer):
    token = issue_pass(live_event.id)["qr_token"]
    scan(client, live_event.id, token)

    response = register(live_event.id)

    assert response.status_code == 409


def test_unknown_token_is_invalid(client, live_event, officer):
    response = scan(client, live_event.id, "A" * 43)

    assert response.json() == {
        "result": "invalid",
        "message": "This pass is not valid",
        "guest": None,
        "checked_in_at": None,
        "gate": None,
    }


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
    # The pass still works at its own event.
    assert scan(client, other.id, token).json()["result"] == "admitted"


@pytest.mark.parametrize(
    "token", ["", "short", "has spaces in it and is long enough", "x" * 129, "abc/def+ghi=jkl==mnop"]
)
def test_malformed_token_is_rejected_before_lookup(client, live_event, officer, token):
    assert scan(client, live_event.id, token).status_code == 422


def test_scanning_outside_the_gate_window(client, issue_pass, make_event, login_as, assign_officer):
    event = make_event(starts_in=timedelta(days=2))
    token = issue_pass(event.id)["qr_token"]
    assign_officer(event.id)
    login_as("security_officer", user_id=42)

    body = scan(client, event.id, token).json()

    assert body["result"] == "gate_closed"


def test_every_scan_is_logged_without_the_token(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id)["qr_token"]
    scan(client, live_event.id, token)
    scan(client, live_event.id, token)
    scan(client, live_event.id, "B" * 43)

    attempts = db_session.scalars(select(ScanAttempt).order_by(ScanAttempt.id)).all()

    assert [a.result for a in attempts] == ["admitted", "already_checked_in", "invalid"]
    assert all(a.officer_id == 42 and a.gate == "Gate 1" for a in attempts)
    assert attempts[2].registration_id is None


# --- access control ----------------------------------------------------------


def test_scan_requires_login(client, live_event):
    assert scan(client, live_event.id, "A" * 43).status_code == 401


@pytest.mark.parametrize("role", ["guest", "event_manager", "security"])
def test_other_roles_cannot_scan(client, login_as, live_event, role):
    login_as(role)

    assert scan(client, live_event.id, "A" * 43).status_code == 403


def test_officer_cannot_scan_for_unassigned_event(client, issue_pass, make_event, officer, db_session):
    other = make_event(starts_in=timedelta(minutes=10))
    token = issue_pass(other.id)["qr_token"]

    response = scan(client, other.id, token)

    assert response.status_code == 404
    assert db_session.scalars(select(CheckIn)).all() == []


def test_removed_assignment_revokes_gate_access(client, login_as, assign_officer, live_event, db_session):
    (assignment,) = assign_officer(live_event.id, officer_id=7)
    assignment.deleted_at = utcnow()
    db_session.commit()
    login_as("security_officer", user_id=7)

    assert scan(client, live_event.id, "A" * 43).status_code == 404


def test_assignment_is_per_officer(client, login_as, live_event, officer):
    login_as("security_officer", user_id=43)

    assert scan(client, live_event.id, "A" * 43).status_code == 404


def test_admin_can_scan_any_event(client, issue_pass, login_as, live_event):
    token = issue_pass(live_event.id)["qr_token"]
    login_as("admin", user_id=1)

    assert scan(client, live_event.id, token).json()["result"] == "admitted"


def test_deleted_event_is_404(client, live_event, officer, db_session):
    live_event.deleted_at = utcnow()
    db_session.commit()

    assert scan(client, live_event.id, "A" * 43).status_code == 404


# --- entry list ----------------------------------------------------------------


def test_entries_lists_checked_in_guests(client, issue_pass, live_event, officer):
    scan(client, live_event.id, issue_pass(live_event.id, email="guest01@example.com", name="Ravi")["qr_token"])
    scan(client, live_event.id, issue_pass(live_event.id, email="guest02@example.com", name="Meera")["qr_token"])
    issue_pass(live_event.id, email="guest03@example.com", name="Not arrived")

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


def test_one_scan_admits_the_whole_party_and_shows_its_details(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id, guests=["Ravi Patil", "Meera Patil"], employee_id="MT-104")["qr_token"]

    body = scan(client, live_event.id, token).json()

    assert body["result"] == "admitted"
    guest = body["guest"]
    assert (guest["employee_id"], guest["name"], guest["party_size"]) == ("MT-104", "Asha Patil", 3)
    assert guest["guest_names"] == ["Ravi Patil", "Meera Patil"]
    assert (guest["email_masked"], guest["mobile_masked"]) == ("as•••@example.com", "98•••••210")
    assert "asha.patil@example.com" not in str(body) and "9876543210" not in str(body)
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_used_party_pass_shows_details_and_original_entry(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id, guests=["Ravi Patil"])["qr_token"]
    scan(client, live_event.id, token, gate="North gate")

    body = scan(client, live_event.id, token, gate="South gate").json()

    assert body["result"] == "already_checked_in"
    assert (body["guest"]["party_size"], body["guest"]["guest_names"]) == (2, ["Ravi Patil"])
    assert body["gate"] == "North gate" and body["checked_in_at"]
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_wrong_event_and_invalid_scans_leak_no_party_details(
    client, issue_pass, make_event, live_event, login_as, assign_officer
):
    other = make_event(starts_in=timedelta(minutes=10))
    token = issue_pass(other.id, guests=["Ravi Patil"], employee_id="MT-104")["qr_token"]
    assign_officer(live_event.id)
    login_as("security_officer", user_id=42)

    for response in (scan(client, live_event.id, token), scan(client, live_event.id, "B" * 43)):
        assert response.json()["guest"] is None
        for detail in ("MT-104", "Asha", "Ravi", "•••"):
            assert detail not in response.text


def test_unassigned_officer_learns_nothing_about_the_party(client, issue_pass, make_event, login_as, assign_officer):
    event = make_event(starts_in=timedelta(minutes=10))
    token = issue_pass(event.id, guests=["Ravi Patil"])["qr_token"]
    login_as("security_officer", user_id=43)  # assigned to nothing

    response = scan(client, event.id, token)

    assert response.status_code == 404
    assert "Ravi" not in response.text and "Asha" not in response.text


def test_pending_registration_has_no_pass_to_scan(client, mailbox, register, live_event, officer, db_session):
    register(live_event.id)

    registration = db_session.scalars(select(Registration)).one()
    assert registration.qr_token_hash is None


# --- server-side check-in time, races, token handling ---------------------------------


def test_check_in_time_comes_from_the_server(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id)["qr_token"]
    forged = client.post(
        f"/api/v1/gate/events/{live_event.id}/scan",
        json={"token": token, "checked_in_at": "2000-01-01T00:00:00Z"},
    )
    assert forged.status_code == 422

    before = utcnow()
    body = scan(client, live_event.id, token).json()
    after = utcnow()

    check_in = db_session.scalars(select(CheckIn)).one()
    assert before <= check_in.checked_in_at <= after
    assert body["checked_in_at"] == check_in.checked_in_at.isoformat()


def test_losing_a_concurrent_scan_reports_the_winners_entry(
    client, issue_pass, live_event, officer, db_session, monkeypatch
):
    """Two gates scan one pass at once: the atomic UPDATE lets one win; the other sees the winner's entry."""
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
    body = scan(client, live_event.id, token, gate="West gate").json()

    assert body["result"] == "already_checked_in"
    assert body["gate"] == "East gate"
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_unique_index_is_the_last_guard_against_double_entry(client, issue_pass, live_event, officer, db_session):
    """Even if the status guard were bypassed, the unique registration_id stops a second check-in row."""
    token = issue_pass(live_event.id)["qr_token"]
    scan(client, live_event.id, token)
    registration = db_session.scalars(select(Registration)).one()
    registration.status = "VERIFIED"
    db_session.commit()

    body = scan(client, live_event.id, token).json()

    assert body["result"] != "admitted"
    assert body["guest"] is None
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_gate_closed_scan_admits_nobody_and_shows_nothing(
    client, issue_pass, make_event, login_as, assign_officer, db_session
):
    event = make_event(starts_in=timedelta(days=2))
    token = issue_pass(event.id)["qr_token"]
    assign_officer(event.id)
    login_as("security_officer", user_id=42)

    body = scan(client, event.id, token).json()

    assert (body["result"], body["guest"], body["checked_in_at"]) == ("gate_closed", None, None)
    assert db_session.scalars(select(CheckIn)).all() == []
    assert db_session.scalars(select(Registration)).one().status == "VERIFIED"


def test_scan_attempts_never_store_the_raw_token(client, issue_pass, live_event, officer, db_session):
    token = issue_pass(live_event.id)["qr_token"]
    scan(client, live_event.id, token)
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
    assert scan(client, live_event.id, token).json()["result"] == "admitted"
    assert client.get(f"/api/v1/gate/events/{live_event.id}/entries").status_code == 200

    assignment.deleted_at = utcnow()
    db_session.commit()

    assert client.get(f"/api/v1/gate/events/{live_event.id}/entries").status_code == 404
    assert client.get(f"/api/v1/events/{live_event.id}").status_code == 404
