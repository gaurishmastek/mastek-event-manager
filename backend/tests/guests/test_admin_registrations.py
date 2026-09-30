"""GET /events/{id}/registrations: admins only, masked contact details, no secrets."""

import pytest

from tests.conftest import auth_headers


def url(event_id: int) -> str:
    return f"/api/v1/events/{event_id}/registrations"


@pytest.fixture()
def admin(login_as):
    return login_as("admin", user_id=7)


def test_admin_sees_registrations_with_masked_contacts(client, issue_pass, register, make_event, admin, db_session):
    event = make_event()
    guest_pass = issue_pass(event.id, email="asha.patil@example.com", guests=["Ravi Patil"], employee_id="MT-104")
    register(event.id, email="kiran@example.com", name="Kiran Shah", employee_id="MT-200")

    response = client.get(url(event.id))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["total"] == 2
    pending, verified = body["items"]  # newest first
    assert verified == {
        "registration_id": guest_pass["registration_id"],
        "employee_id": "MT-104",
        "employee_name": "Asha Patil",
        "email_masked": "as•••@example.com",
        "mobile_masked": "98•••••210",
        "attending": True,
        "family_attending": True,
        "guest_names": ["Ravi Patil"],
        "adult_name": "Ravi Patil",
        "kid_names": [],
        "kid_ages": [],
        "food_preference": "VEG",
        "number_of_guests": 1,
        "party_size": 2,
        "status": "VERIFIED",
        "verified_at": verified["verified_at"],
        "qr_issued": True,
        "qr_issued_at": verified["qr_issued_at"],
        "checked_in_at": None,
        "created_at": verified["created_at"],
    }
    assert verified["verified_at"] and verified["qr_issued_at"]
    assert (pending["status"], pending["qr_issued"], pending["verified_at"]) == ("PENDING_OTP", False, None)


def test_admin_list_never_returns_secrets_or_full_contacts(client, issue_pass, make_event, admin, db_session):
    from sqlalchemy import select

    from app.modules.guests.models import Registration

    event = make_event()
    token = issue_pass(event.id)["qr_token"]
    row = db_session.scalars(select(Registration)).one()

    text = client.get(url(event.id)).text

    for secret in (
        token,
        row.qr_token_hash,
        row.email_hash,
        row.email_encrypted,
        row.mobile_hash,
        row.mobile_encrypted,
    ):
        assert secret not in text
    for full in ("asha.patil@example.com", "9876543210", "+919876543210"):
        assert full not in text
    assert "code" not in text


def test_search_by_employee_id_or_name_and_filter_by_status(client, issue_pass, register, make_event, admin):
    event = make_event()
    issue_pass(event.id, email="asha@example.com", name="Asha Patil", employee_id="MT-104")
    register(event.id, email="kiran@example.com", name="Kiran Shah", employee_id="MT-200")
    register(event.id, email="tara@example.com", name="Tara_Shah", employee_id="XY-1")

    def names(**params) -> list[str]:
        return [item["employee_name"] for item in client.get(url(event.id), params=params).json()["items"]]

    assert names(search="mt-104") == ["Asha Patil"]
    assert names(search="shah") == ["Tara_Shah", "Kiran Shah"]
    assert names(search="_") == ["Tara_Shah"]  # wildcards are literal
    assert names(status="PENDING_OTP") == ["Tara_Shah", "Kiran Shah"]
    assert names(status="VERIFIED") == ["Asha Patil"]
    assert names(status="CHECKED_IN") == []


def test_pagination(client, mailbox, register, make_event, admin):
    event = make_event()
    for n in range(5):
        register(event.id, email=f"guest{n}@example.com")

    page = client.get(url(event.id), params={"limit": 2, "offset": 4}).json()

    assert (page["total"], page["limit"], page["offset"], len(page["items"])) == (5, 2, 4, 1)


def test_only_lists_the_requested_event(client, mailbox, register, make_event, admin):
    event, other = make_event(), make_event()
    assert register(other.id).status_code == 202

    assert client.get(url(event.id)).json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "DELETED"}, {"search": ""}]
)
def test_rejects_bad_query_params(client, make_event, admin, params):
    assert client.get(url(make_event().id), params=params).status_code == 422


def test_missing_or_deleted_event_is_404(client, make_event, admin, db_session):
    from app.db.mixins import utcnow

    event = make_event()
    event.deleted_at = utcnow()
    db_session.commit()

    assert client.get(url(event.id)).status_code == 404
    assert client.get(url(999)).status_code == 404


# --- access control -------------------------------------------------------------


def test_unauthenticated_callers_are_rejected(client, make_event):
    assert client.get(url(make_event().id)).status_code == 401


def test_security_officers_cannot_list_registrations_even_for_their_event(client, login_as, make_event, db_session):
    from app.modules.events.models import OfficerEvent

    event = make_event()
    db_session.add(OfficerEvent(officer_id=42, event_id=event.id))
    db_session.commit()
    login_as("security_officer", user_id=42)

    assert client.get(url(event.id)).status_code == 403


def test_real_officer_token_is_rejected(client, officer, make_event):
    headers = auth_headers(client, officer)

    assert client.get(url(make_event().id), headers=headers).status_code == 403


def test_real_admin_token_is_accepted(client, admin_headers, make_event):
    assert client.get(url(make_event().id), headers=admin_headers).status_code == 200
