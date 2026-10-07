import re
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.events.models import Event, OfficerEvent

IST = timezone(timedelta(hours=5, minutes=30))


def future(days: int = 30, hours: int = 0) -> str:
    return (datetime.now(IST) + timedelta(days=days, hours=hours)).replace(microsecond=0).isoformat()


def payload(**overrides):
    body = {
        "title": "Navratri Garba Night",
        "description": "Dandiya and garba on the lawn.",
        "location": "Mastek campus, Mumbai",
        "starts_at": future(30),
        "ends_at": future(30, hours=4),
        "capacity": 500,
    }
    body.update(overrides)
    return body


@pytest.fixture()
def admin(login_as):
    return login_as("admin", user_id=7)


def create(client, **overrides):
    response = client.post("/api/v1/events", json=payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# --- CRUD happy path -------------------------------------------------------


def test_create_event_returns_it_with_audit_fields(client, admin):
    event = create(client)

    assert event["id"] > 0
    assert event["title"] == "Navratri Garba Night"
    assert event["capacity"] == 500
    assert event["created_by"] == 7
    assert event["updated_by"] == 7
    assert event["created_at"] and event["updated_at"]


def test_create_stores_times_as_utc(client, admin):
    event = create(client, starts_at="2030-10-20T18:00:00+05:30", ends_at="2030-10-20T22:00:00+05:30")

    assert event["starts_at"] == "2030-10-20T12:30:00"
    assert event["ends_at"] == "2030-10-20T16:30:00"


def test_get_event(client, admin):
    created = create(client)

    response = client.get(f"/api/v1/events/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_list_events_orders_by_start_and_paginates(client, admin):
    create(client, title="Diwali Mela", starts_at=future(60), ends_at=None)
    create(client, title="Navratri Night", starts_at=future(10), ends_at=None)
    create(client, title="Holi Party", starts_at=future(90), ends_at=None)

    response = client.get("/api/v1/events", params={"limit": 2})

    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 3
    assert [e["title"] for e in body["items"]] == ["Navratri Night", "Diwali Mela"]

    second_page = client.get("/api/v1/events", params={"limit": 2, "offset": 2}).json()
    assert [e["title"] for e in second_page["items"]] == ["Holi Party"]


def test_list_search_matches_title_and_treats_wildcards_literally(client, admin):
    create(client, title="Diwali Mela")
    create(client, title="100% Garba")

    assert [e["title"] for e in client.get("/api/v1/events", params={"search": "diwali"}).json()["items"]] == [
        "Diwali Mela"
    ]
    assert [e["title"] for e in client.get("/api/v1/events", params={"search": "%"}).json()["items"]] == ["100% Garba"]


def test_list_upcoming_hides_past_events(client, admin, db_session):
    create(client, title="Future Event")
    past = Event(title="Old Event", location="Mumbai", starts_at=datetime(2020, 1, 1), capacity=10)
    db_session.add(past)
    db_session.commit()

    all_titles = {e["title"] for e in client.get("/api/v1/events").json()["items"]}
    upcoming = [e["title"] for e in client.get("/api/v1/events", params={"upcoming": True}).json()["items"]]

    assert all_titles == {"Future Event", "Old Event"}
    assert upcoming == ["Future Event"]


def test_update_event_changes_only_sent_fields(client, login_as):
    login_as("admin", user_id=7)
    created = create(client)
    login_as("admin", user_id=9)

    response = client.patch(f"/api/v1/events/{created['id']}", json={"capacity": 750, "location": "Hall B"})

    updated = response.json()
    assert response.status_code == 200
    assert updated["capacity"] == 750
    assert updated["location"] == "Hall B"
    assert updated["title"] == created["title"]
    assert updated["created_by"] == 7
    assert updated["updated_by"] == 9


def test_update_can_clear_optional_fields(client, admin):
    created = create(client)

    updated = client.patch(f"/api/v1/events/{created['id']}", json={"description": None, "ends_at": None}).json()

    assert updated["description"] is None
    assert updated["ends_at"] is None


def test_delete_is_soft(client, admin, db_session):
    created = create(client)

    response = client.delete(f"/api/v1/events/{created['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/events/{created['id']}").status_code == 404
    assert client.get("/api/v1/events").json()["total"] == 0
    assert client.patch(f"/api/v1/events/{created['id']}", json={"capacity": 5}).status_code == 404
    assert client.delete(f"/api/v1/events/{created['id']}").status_code == 404

    row = db_session.get(Event, created["id"])
    assert row is not None
    assert row.deleted_at is not None
    assert row.deleted_by == 7


def test_missing_event_returns_404(client, admin):
    assert client.get("/api/v1/events/999").status_code == 404
    assert client.get("/api/v1/events/0").status_code == 422
    assert client.get("/api/v1/events/99999999999").status_code == 422


# --- Validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "ab"},
        {"title": "x" * 201},
        {"title": "Bad\nTitle"},
        {"title": "Null\x00byte"},
        {"location": ""},
        {"location": "y" * 256},
        {"description": "z" * 5001},
        {"description": "bell\x07"},
        {"capacity": 0},
        {"capacity": -5},
        {"capacity": 100_001},
        {"capacity": "50"},
        {"capacity": 12.5},
        {"capacity": True},
        {"starts_at": "not-a-date"},
        {"starts_at": "2030-10-20T18:00:00"},  # no timezone
        {"starts_at": "2020-01-01T10:00:00+05:30"},  # in the past
        {"starts_at": future(10), "ends_at": future(9)},  # ends before starts
        {"is_admin": True},  # unknown field
    ],
)
def test_create_rejects_invalid_input(client, admin, overrides):
    response = client.post("/api/v1/events", json=payload(**overrides))

    assert response.status_code == 422, overrides
    assert client.get("/api/v1/events").json()["total"] == 0


@pytest.mark.parametrize("field", ["title", "location", "starts_at", "capacity"])
def test_create_requires_fields(client, admin, field):
    body = payload()
    del body[field]

    assert client.post("/api/v1/events", json=body).status_code == 422


def test_create_trims_whitespace(client, admin):
    event = create(client, title="  Diwali Mela  ", location="  Mumbai ")

    assert event["title"] == "Diwali Mela"
    assert event["location"] == "Mumbai"


def test_create_stores_markup_as_plain_text(client, admin):
    event = create(client, title="<script>alert(1)</script>")

    # Stored verbatim and returned as JSON; escaping is the renderer's job, never string surgery here.
    assert event["title"] == "<script>alert(1)</script>"


@pytest.mark.parametrize(
    "body",
    [
        {"title": None},
        {"capacity": None},
        {"capacity": 0},
        {"title": "  "},
        {"ends_at": "2020-01-01T00:00:00+00:00"},  # before existing start
        {"starts_at": "2020-01-01T00:00:00+00:00"},  # in the past
        {"created_by": 1},  # audit fields are not writable
        {"deleted_at": None},
    ],
)
def test_update_rejects_invalid_input(client, admin, body):
    created = create(client)

    response = client.patch(f"/api/v1/events/{created['id']}", json=body)

    assert response.status_code == 422, body
    assert client.get(f"/api/v1/events/{created['id']}").json() == created


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"search": ""}, {"search": "s" * 101}]
)
def test_list_rejects_bad_query_params(client, admin, params):
    assert client.get("/api/v1/events", params=params).status_code == 422


# --- Access control --------------------------------------------------------


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/v1/events").status_code == 401
    assert client.get("/api/v1/events/1").status_code == 401
    assert client.post("/api/v1/events", json=payload()).status_code == 401
    assert client.patch("/api/v1/events/1", json={"capacity": 5}).status_code == 401
    assert client.delete("/api/v1/events/1").status_code == 401


def assign(db_session, officer_id: int, event_id: int, *, deleted: bool = False) -> None:
    link = OfficerEvent(officer_id=officer_id, event_id=event_id)
    if deleted:
        link.deleted_at = datetime(2026, 1, 1)
    db_session.add(link)
    db_session.commit()


def test_officer_sees_only_assigned_events(client, login_as, db_session):
    login_as("admin")
    navratri = create(client, title="Navratri Night")
    diwali = create(client, title="Diwali Mela")
    holi = create(client, title="Holi Party")
    assign(db_session, officer_id=50, event_id=navratri["id"])
    assign(db_session, officer_id=51, event_id=diwali["id"])  # someone else's event
    assign(db_session, officer_id=50, event_id=holi["id"], deleted=True)  # assignment removed
    login_as("security_officer", user_id=50)

    body = client.get("/api/v1/events").json()

    assert body["total"] == 1
    assert [e["title"] for e in body["items"]] == ["Navratri Night"]
    assert client.get(f"/api/v1/events/{navratri['id']}").status_code == 200
    # Unassigned events look like they don't exist, so IDs can't be probed.
    assert client.get(f"/api/v1/events/{diwali['id']}").status_code == 404
    assert client.get(f"/api/v1/events/{holi['id']}").status_code == 404


def test_officer_with_no_assignments_sees_nothing(client, login_as):
    login_as("admin")
    create(client)
    login_as("security_officer", user_id=50)

    assert client.get("/api/v1/events").json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_admin_sees_all_events_regardless_of_assignment(client, admin, db_session):
    first = create(client, title="Navratri Night")
    create(client, title="Diwali Mela")
    assign(db_session, officer_id=50, event_id=first["id"])

    assert client.get("/api/v1/events").json()["total"] == 2


def test_officer_cannot_write_even_on_assigned_event(client, login_as, db_session):
    login_as("admin")
    created = create(client)
    assign(db_session, officer_id=50, event_id=created["id"])
    login_as("security_officer", user_id=50)

    assert client.post("/api/v1/events", json=payload()).status_code == 403
    assert client.patch(f"/api/v1/events/{created['id']}", json={"capacity": 5}).status_code == 403
    assert client.delete(f"/api/v1/events/{created['id']}").status_code == 403

    login_as("admin")
    assert client.get(f"/api/v1/events/{created['id']}").json() == created


@pytest.mark.parametrize("role", ["guest", "event_manager", "security", ""])
def test_other_roles_are_denied(client, login_as, role):
    login_as(role)

    assert client.get("/api/v1/events").status_code == 403
    assert client.get("/api/v1/events/1").status_code == 403
    assert client.post("/api/v1/events", json=payload()).status_code == 403


# --- public registration link ----------------------------------------------

UUID4 = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


def test_new_events_get_a_unique_random_public_id(client, admin):
    events = [create(client) for _ in range(3)]

    public_ids = [event["public_id"] for event in events]
    assert all(re.fullmatch(UUID4, public_id) for public_id in public_ids)
    assert len(set(public_ids)) == 3
    assert all(str(event["id"]) not in event["public_id"].split("-") for event in events)


def test_public_id_cannot_be_set_or_changed_by_the_client(client, admin):
    forged = client.post("/api/v1/events", json=payload(public_id="00000000-0000-4000-8000-000000000000"))
    assert forged.status_code == 422
    event = create(client)

    response = client.patch(f"/api/v1/events/{event['id']}", json={"public_id": "x"})

    assert response.status_code == 422
    assert client.get(f"/api/v1/events/{event['id']}").json()["public_id"] == event["public_id"]


def test_public_id_links_to_the_public_registration_page(client, admin):
    event = create(client)

    response = client.get(f"/api/v1/public/events/{event['public_id']}")

    assert response.status_code == 200
    assert response.json()["title"] == event["title"]
    # The internal numeric id is not a valid public link.
    assert client.get(f"/api/v1/public/events/{event['id']}").status_code == 422


def test_max_guests_defaults_to_five_and_can_be_edited(client, admin):
    event = create(client)
    assert event["max_guests_per_registration"] == 5

    updated = client.patch(f"/api/v1/events/{event['id']}", json={"max_guests_per_registration": 0})

    assert updated.status_code == 200
    assert updated.json()["max_guests_per_registration"] == 0
    assert create(client, max_guests_per_registration=10)["max_guests_per_registration"] == 10


@pytest.mark.parametrize("value", [-1, 11, 2.5, "3", True, None])
def test_max_guests_must_be_a_small_whole_number(client, admin, value):
    assert client.post("/api/v1/events", json=payload(max_guests_per_registration=value)).status_code == 422
    event = create(client)
    patch = client.patch(f"/api/v1/events/{event['id']}", json={"max_guests_per_registration": value})
    assert patch.status_code == 422


def test_event_read_includes_the_gate_window(client, admin):
    starts = datetime(2031, 10, 20, 18, 0, tzinfo=IST)
    with_end = create(client, starts_at=starts.isoformat(), ends_at=(starts + timedelta(hours=4)).isoformat())
    without_end = create(client, starts_at=starts.isoformat(), ends_at=None)

    # Defaults: opens 3 hours before the start; closes at the end, or 12 hours after the start.
    assert with_end["gate_opens_at"] == "2031-10-20T09:30:00"
    assert with_end["gate_closes_at"] == "2031-10-20T16:30:00"
    assert without_end["gate_closes_at"] == "2031-10-21T00:30:00"


def test_registration_is_open_by_default_and_admin_can_close_and_reopen(client, admin):
    event = create(client)
    assert event["registration_open"] is True

    closed = client.patch(f"/api/v1/events/{event['id']}", json={"registration_open": False})
    assert closed.status_code == 200
    assert closed.json()["registration_open"] is False

    reopened = client.patch(f"/api/v1/events/{event['id']}", json={"registration_open": True})
    assert reopened.json()["registration_open"] is True


@pytest.mark.parametrize("value", ["false", 0, None])
def test_registration_open_must_be_a_boolean(client, admin, value):
    event = create(client)
    assert client.patch(f"/api/v1/events/{event['id']}", json={"registration_open": value}).status_code == 422


def test_officer_cannot_close_registration(client, login_as):
    login_as("admin", user_id=7)
    event = create(client)
    login_as("security_officer", user_id=8)

    assert client.patch(f"/api/v1/events/{event['id']}", json={"registration_open": False}).status_code == 403
