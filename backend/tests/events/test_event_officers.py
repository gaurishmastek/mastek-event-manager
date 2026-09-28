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


def test_one_officer_can_be_assigned_to_several_events(client, login_as, setup):
    assigned, other = setup
    assert client.put(f"/api/v1/events/{other['id']}/officers/5").status_code == 204
    assert client.get(f"/api/v1/events/{other['id']}/officers").json() == [5]

    login_as("security_officer", user_id=5)
    assert sorted(e["id"] for e in client.get("/api/v1/events").json()["items"]) == sorted(
        [assigned["id"], other["id"]]
    )


def test_assigning_twice_keeps_one_assignment(client, setup, db_session):
    from app.modules.events.models import OfficerEvent

    assigned, _ = setup
    assert client.put(f"/api/v1/events/{assigned['id']}/officers/5").status_code == 204
    assert client.get(f"/api/v1/events/{assigned['id']}/officers").json() == [5]
    assert db_session.query(OfficerEvent).filter_by(event_id=assigned["id"], officer_id=5).count() == 1


def test_concurrent_duplicate_assignment_is_not_an_error(client, setup, db_session, monkeypatch):
    """Two admins assigning the same officer at once: the loser hits the unique pair and still gets 204."""
    from app.modules.events.models import OfficerEvent
    from app.modules.events.repository import EventRepository

    _, other = setup
    real_get = EventRepository.get_assignment
    calls = {"n": 0}

    def racing_get(self, event_id, officer_id):
        calls["n"] += 1
        if calls["n"] == 1:
            # The other request inserts between our lookup and our insert.
            db_session.add(OfficerEvent(event_id=event_id, officer_id=officer_id, created_by=1, updated_by=1))
            db_session.commit()
            return None
        return real_get(self, event_id, officer_id)

    monkeypatch.setattr(EventRepository, "get_assignment", racing_get)
    assert client.put(f"/api/v1/events/{other['id']}/officers/6").status_code == 204
    monkeypatch.setattr(EventRepository, "get_assignment", real_get)
    assert client.get(f"/api/v1/events/{other['id']}/officers").json() == [6]


def test_inactive_or_deleted_officers_cannot_be_assigned(client, login_as, setup, db_session):
    from app.db.mixins import utcnow
    from app.modules.users.models import User

    _, other = setup
    officer_6 = db_session.get(User, 6)
    officer_6.is_active = False
    officer_7 = login_as("security_officer", user_id=7)
    officer_7.deleted_at = utcnow()
    db_session.commit()
    login_as("admin", user_id=1)

    assert client.put(f"/api/v1/events/{other['id']}/officers/6").status_code == 404
    assert client.put(f"/api/v1/events/{other['id']}/officers/7").status_code == 404
    assert client.get(f"/api/v1/events/{other['id']}/officers").json() == []


def test_unassigning_one_event_keeps_the_others(client, login_as, setup):
    assigned, other = setup
    client.put(f"/api/v1/events/{other['id']}/officers/5")
    assert client.delete(f"/api/v1/events/{assigned['id']}/officers/5").status_code == 204

    login_as("security_officer", user_id=5)
    assert [e["id"] for e in client.get("/api/v1/events").json()["items"]] == [other["id"]]
    assert client.get(f"/api/v1/events/{assigned['id']}").status_code == 404


def test_admin_lists_security_officers_only(client, login_as, setup):
    body = client.get("/api/v1/users", params={"role": "security_officer"}).json()
    assert [u["id"] for u in body] == [5, 6]
    assert {u["role"] for u in body} == {"security_officer"}
    # Nothing secret or encrypted in the listing.
    assert set(body[0]) == {"id", "email", "full_name", "role", "is_active", "created_at", "last_login_at"}
    assert client.get("/api/v1/users", params={"role": "security"}).status_code == 422


def test_officer_cannot_create_users_or_list_them(client, login_as, setup):
    login_as("security_officer", user_id=5)
    assert client.get("/api/v1/users", params={"role": "security_officer"}).status_code == 403
    body = {"email": "new@example.com", "full_name": "New", "role": "security_officer"}
    assert client.post("/api/v1/users", json=body).status_code == 403
