from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.gate.models import CheckIn, EntryRejection, GuestEntry, ScanAttempt
from tests.gate.helpers import scan


def lookup(client, event_id: int, employee_id: str, gate: str = "Gate 1"):
    return client.post(
        f"/api/v1/gate/events/{event_id}/lookup-employee", json={"employee_id": employee_id, "gate": gate}
    )


def decide_by_employee(client, event_id: int, employee_id: str, **fields):
    return client.post(
        f"/api/v1/gate/events/{event_id}/decision",
        json={"employee_id": employee_id, "decision": "approve", "gate": "Gate 1", **fields},
    )


def test_lookup_by_employee_id_shows_party_without_admitting(client, issue_pass, live_event, officer, db_session):
    issue_pass(live_event.id, employee_id="MT-104", guests=["Ravi Patil", "Meera Patil"])

    response = lookup(client, live_event.id, "mt-104")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "pending_verification"
    assert body["guest"]["employee_id"] == "MT-104"
    assert body["guest"]["guest_names"] == ["Ravi Patil", "Meera Patil"]
    assert [member["entered"] for member in body["guest"]["members"]] == [False, False]
    assert response.headers["cache-control"] == "no-store"
    assert db_session.scalars(select(CheckIn)).all() == []
    assert db_session.scalars(select(ScanAttempt)).one().registration_id is not None


def test_employee_lookup_approval_needs_id_check_and_admits_selected_people(
    client, issue_pass, live_event, officer, db_session
):
    token = issue_pass(live_event.id, employee_id="MT-104", guests=["Ravi Patil", "Meera Patil"])["qr_token"]
    first, second = [member["id"] for member in lookup(client, live_event.id, "MT-104").json()["guest"]["members"]]

    unchecked = decide_by_employee(client, live_event.id, "MT-104", guest_ids_entered=[first])
    assert unchecked.status_code == 422
    assert db_session.scalars(select(CheckIn)).all() == []

    admitted = decide_by_employee(client, live_event.id, "mt-104", employee_id_checked=True, guest_ids_entered=[first])
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["result"] == "admitted"
    assert admitted.json()["people_entered"] == 2
    check_in = db_session.scalars(select(CheckIn)).one()
    assert check_in.method == "MANUAL"
    assert [row.registration_guest_id for row in db_session.scalars(select(GuestEntry))] == [first]

    later = lookup(client, live_event.id, "MT-104").json()
    assert later["result"] == "pending_guests"
    assert [(member["id"], member["entered"]) for member in later["guest"]["members"]] == [
        (first, True),
        (second, False),
    ]
    late_admission = decide_by_employee(client, live_event.id, "MT-104", guest_ids_entered=[second]).json()
    assert late_admission["result"] == "admitted"
    assert lookup(client, live_event.id, "MT-104").json()["result"] == "already_checked_in"
    assert scan(client, live_event.id, token).json()["result"] == "already_checked_in"
    assert len(db_session.scalars(select(CheckIn)).all()) == 1


def test_employee_lookup_rejection_records_reason_without_admission(
    client, issue_pass, live_event, officer, db_session
):
    issue_pass(live_event.id, employee_id="MT-104")

    response = decide_by_employee(client, live_event.id, "MT-104", decision="reject", reason="ID_MISMATCH")

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "rejected"
    assert response.json()["guest"] is None
    assert db_session.scalars(select(EntryRejection)).one().reason == "ID_MISMATCH"
    assert db_session.scalars(select(CheckIn)).all() == []
    assert lookup(client, live_event.id, "MT-104").json()["result"] == "pending_verification"


def test_employee_lookup_is_event_scoped_and_unknown_ids_are_invalid(
    client, issue_pass, make_event, live_event, login_as, assign_officer, db_session
):
    other = make_event(starts_in=timedelta(minutes=10))
    issue_pass(other.id, employee_id="MT-104", guests=["Ravi Patil"])
    assign_officer(live_event.id, other.id)
    login_as("security_officer", user_id=42)

    for employee_id in ("MT-104", "UNKNOWN"):
        result = lookup(client, live_event.id, employee_id).json()
        assert result["result"] == "invalid" and result["guest"] is None
        decision = decide_by_employee(client, live_event.id, employee_id, employee_id_checked=True).json()
        assert decision["result"] == "invalid" and decision["guest"] is None
    assert db_session.scalars(select(CheckIn)).all() == []
    assert all(attempt.registration_id is None for attempt in db_session.scalars(select(ScanAttempt)))


def test_employee_lookup_requires_assignment_and_open_gate(
    client, issue_pass, make_event, live_event, login_as, assign_officer
):
    future = make_event(starts_in=timedelta(days=2))
    issue_pass(future.id, employee_id="MT-104")
    login_as("security_officer", user_id=42)
    assert lookup(client, future.id, "MT-104").status_code == 404
    assert decide_by_employee(client, future.id, "MT-104", employee_id_checked=True).status_code == 404

    assign_officer(future.id)
    assert lookup(client, future.id, "MT-104").json()["result"] == "gate_closed"
    assert decide_by_employee(client, future.id, "MT-104", employee_id_checked=True).json()["result"] == "gate_closed"


@pytest.mark.parametrize("employee_id", ["", "bad id", "/", "x" * 31])
def test_employee_lookup_rejects_malformed_id(client, live_event, officer, employee_id):
    assert lookup(client, live_event.id, employee_id).status_code == 422
    assert decide_by_employee(client, live_event.id, employee_id, employee_id_checked=True).status_code == 422


def test_decision_requires_exactly_one_lookup_credential(client, issue_pass, live_event, officer):
    token = issue_pass(live_event.id, employee_id="MT-104")["qr_token"]
    url = f"/api/v1/gate/events/{live_event.id}/decision"
    assert client.post(url, json={"decision": "approve", "employee_id_checked": True}).status_code == 422
    assert (
        client.post(
            url,
            json={"token": token, "employee_id": "MT-104", "decision": "approve", "employee_id_checked": True},
        ).status_code
        == 422
    )
