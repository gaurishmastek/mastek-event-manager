import pytest

from tests.events.test_events_api import create

pytestmark = pytest.mark.usefixtures("client")


@pytest.fixture()
def setup(client, login_as):
    """An admin (id 1), two security officers (ids 5 and 6) and two events, one assigned to officer 5."""
    login_as("security_officer", user_id=5)
    login_as("security_officer", user_id=6)
    login_as("admin", user_id=1)
    assigned = create(client, title="Diwali Mela")
    other = create(client, title="Holi Party")
    assert client.put(f"/api/v1/events/{assigned['id']}/officers/5").status_code == 204
    return assigned, other


def test_officer_sees_only_assigned_events(client, login_as, setup):
    assigned, other = setup
    login_as("security_officer", user_id=5)

    body = client.get("/api/v1/events").json()
    assert [e["id"] for e in body["items"]] == [assigned["id"]]
    assert body["total"] == 1
    assert client.get(f"/api/v1/events/{assigned['id']}").status_code == 200
    # Unassigned events read as missing, so officers cannot probe which ids exist.
    assert client.get(f"/api/v1/events/{other['id']}").status_code == 404


def test_other_officer_sees_nothing(client, login_as, setup):
    login_as("security_officer", user_id=6)
    assert client.get("/api/v1/events").json()["total"] == 0


def test_admin_still_sees_every_event(client, login_as, setup):
    login_as("admin", user_id=1)
    assert client.get("/api/v1/events").json()["total"] == 2


def test_unassign_is_soft_and_reassign_restores_access(client, login_as, setup, db_session):
    from app.modules.events.models import OfficerEvent

    assigned, _ = setup
    url = f"/api/v1/events/{assigned['id']}/officers/5"
    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 404
    row = db_session.query(OfficerEvent).filter_by(event_id=assigned["id"], officer_id=5).one()
    assert row.deleted_at is not None and row.deleted_by == 1

    login_as("security_officer", user_id=5)
    assert client.get("/api/v1/events").json()["total"] == 0

    login_as("admin", user_id=1)
    assert client.put(url).status_code == 204
    assert client.get(f"/api/v1/events/{assigned['id']}/officers").json() == [5]
    login_as("security_officer", user_id=5)
    assert client.get("/api/v1/events").json()["total"] == 1


def test_only_security_officers_can_be_assigned(client, login_as, setup):
    assigned, _ = setup
    login_as("admin", user_id=1)
    assert client.put(f"/api/v1/events/{assigned['id']}/officers/1").status_code == 422
    assert client.put(f"/api/v1/events/{assigned['id']}/officers/999").status_code == 404
    assert client.put("/api/v1/events/999/officers/6").status_code == 404


def test_officer_cannot_manage_assignments(client, login_as, setup):
    assigned, _ = setup
    login_as("security_officer", user_id=5)
    assert client.get(f"/api/v1/events/{assigned['id']}/officers").status_code == 403
    assert client.put(f"/api/v1/events/{assigned['id']}/officers/6").status_code == 403
    assert client.delete(f"/api/v1/events/{assigned['id']}/officers/5").status_code == 403
