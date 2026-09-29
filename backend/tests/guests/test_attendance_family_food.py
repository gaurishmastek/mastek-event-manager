"""Registration form answers: event attendance, accompanying family (one adult, up to four kids) and food preference."""

import pytest
from sqlalchemy import select

from app.modules.guests import schemas
from app.modules.guests.models import Registration, RegistrationGuest
from tests.guest_fixtures import registration_body

BASE = "/api/v1/public"


def verify(client, registration_id: str, code: str):
    return client.post(f"{BASE}/registrations/{registration_id}/verify", json={"code": code})


def body(**answers) -> dict:
    """A valid submission with the attendance, family and food answers replaced by `answers`."""
    base = registration_body()
    for key in (
        "attending",
        "family_attending",
        "accompanying_adult",
        "accompanying_kids",
        "adult_name",
        "kid_names",
        "food_preference",
    ):
        base.pop(key, None)
    return {**base, **answers}


def post(client, event, data: dict):
    return client.post(f"{BASE}/events/{event.public_id}/registrations", json=data)


def with_family(adult: str | None = None, kids: list[str] | None = None, food: str = "VEG") -> dict:
    return body(
        attending=True,
        family_attending=True,
        accompanying_adult=adult is not None,
        adult_name=adult,
        accompanying_kids=bool(kids),
        kid_names=kids or [],
        food_preference=food,
    )


# --- not attending ------------------------------------------------------------


def test_not_attending_needs_no_further_answers_and_is_recorded_without_a_seat_or_pass(
    client, mailbox, make_event, db_session
):
    event = make_event(capacity=1)

    started = post(client, event, body(attending=False))
    assert started.status_code == 202, started.text
    response = verify(client, started.json()["registration_id"], mailbox.last_code)

    assert response.status_code == 200, response.text
    declined = response.json()
    assert (declined["status"], declined["attending"], declined["employee_name"]) == ("DECLINED", False, "Asha Patil")
    assert "qr_token" not in declined and "qr_svg" not in declined
    row = db_session.scalars(select(Registration)).one()
    assert (row.attending, row.family_attending, row.food_preference, row.number_of_guests) == (False, None, None, 0)
    assert (row.status, row.qr_token_hash) == ("DECLINED", None)
    assert row.verified_at is not None
    assert client.get(f"{BASE}/events/{event.public_id}").json()["seats_left"] == 1


def test_not_attending_can_answer_even_when_the_event_is_full(client, mailbox, make_event, issue_pass):
    event = make_event(capacity=1)
    issue_pass(event.id, email="kiran@example.com")

    started = post(client, event, body(attending=False))

    assert started.status_code == 202
    assert verify(client, started.json()["registration_id"], mailbox.last_code).json()["status"] == "DECLINED"


@pytest.mark.parametrize(
    "stray",
    [
        {"family_attending": False},
        {"family_attending": True},
        {"accompanying_adult": True},
        {"accompanying_kids": True},
        {"adult_name": "Ravi Patil"},
        {"kid_names": ["Meera Patil"]},
        {"food_preference": "VEG"},
    ],
)
def test_not_attending_rejects_family_or_food_details(client, mailbox, make_event, stray):
    response = post(client, make_event(), body(attending=False, **stray))

    assert response.status_code == 422
    assert mailbox.sent == []


def test_declined_employee_can_change_their_mind(client, mailbox, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    declined = post(client, event, body(attending=False)).json()["registration_id"]
    verify(client, declined, mailbox.last_code)

    again = post(client, event, with_family(adult="Ravi Patil"))
    assert again.json()["registration_id"] == declined
    guest_pass = verify(client, declined, mailbox.last_code).json()

    assert (guest_pass["status"], guest_pass["party_size"], guest_pass["adult_name"]) == ("VERIFIED", 2, "Ravi Patil")


def test_attending_registration_can_switch_to_not_attending_before_verification(
    client, mailbox, make_event, otp_limits, db_session
):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    post(client, event, with_family(adult="Ravi Patil", kids=["Meera Patil"], food="JAIN"))

    registration_id = post(client, event, body(attending=False)).json()["registration_id"]

    row = db_session.scalars(select(Registration)).one()
    assert (row.attending, row.family_attending, row.food_preference, row.number_of_guests) == (False, None, None, 0)
    # The family entered earlier is cleared (soft-deleted, never hard-deleted).
    guests = db_session.scalars(select(RegistrationGuest)).all()
    assert len(guests) == 2 and all(guest.deleted_at is not None for guest in guests)
    assert verify(client, registration_id, mailbox.last_code).json()["status"] == "DECLINED"


# --- attending alone and with family --------------------------------------------


def test_attends_alone(client, mailbox, make_event, db_session):
    started = post(client, make_event(), body(attending=True, family_attending=False, food_preference="VEG"))
    guest_pass = verify(client, started.json()["registration_id"], mailbox.last_code).json()

    assert (guest_pass["party_size"], guest_pass["guest_names"], guest_pass["adult_name"]) == (1, [], None)
    assert (guest_pass["kid_names"], guest_pass["food_preference"]) == ([], "VEG")
    row = db_session.scalars(select(Registration)).one()
    assert (row.attending, row.family_attending) == (True, False)


def test_attends_with_one_adult_only(client, mailbox, make_event, db_session):
    started = post(client, make_event(), with_family(adult="Ravi Patil"))
    guest_pass = verify(client, started.json()["registration_id"], mailbox.last_code).json()

    assert (guest_pass["party_size"], guest_pass["adult_name"], guest_pass["kid_names"]) == (2, "Ravi Patil", [])
    guest = db_session.scalars(select(RegistrationGuest)).one()
    assert (guest.name, guest.guest_type) == ("Ravi Patil", "ADULT")


def test_attends_with_kids_only(client, mailbox, make_event):
    started = post(client, make_event(), with_family(kids=["Meera Patil", "Kiran Patil"]))
    guest_pass = verify(client, started.json()["registration_id"], mailbox.last_code).json()

    assert (guest_pass["party_size"], guest_pass["adult_name"]) == (3, None)
    assert guest_pass["kid_names"] == ["Meera Patil", "Kiran Patil"]


@pytest.mark.parametrize("kid_count", [1, 2, 3, 4])
def test_attends_with_one_adult_and_up_to_four_kids(client, mailbox, make_event, db_session, kid_count):
    kids = ["Meera Patil", "Kiran Patil", "Tara Patil", "Dev Patil"][:kid_count]

    started = post(client, make_event(), with_family(adult="Ravi Patil", kids=kids))
    guest_pass = verify(client, started.json()["registration_id"], mailbox.last_code).json()

    assert guest_pass["party_size"] == 2 + kid_count
    assert guest_pass["guest_names"] == ["Ravi Patil", *kids]
    assert (guest_pass["adult_name"], guest_pass["kid_names"]) == ("Ravi Patil", kids)
    types = [g.guest_type for g in db_session.scalars(select(RegistrationGuest).order_by(RegistrationGuest.position))]
    assert types == ["ADULT"] + ["KID"] * kid_count


def test_family_counts_toward_capacity(client, issue_pass, make_event):
    event = make_event(capacity=10)
    issue_pass(event.id, guests=["Ravi Patil", "Meera Patil", "Kiran Patil"])  # 1 adult, 2 kids

    assert client.get(f"{BASE}/events/{event.public_id}").json()["seats_left"] == 6


def test_family_still_respects_the_event_guest_limit(client, mailbox, make_event):
    response = post(client, make_event(max_guests=2), with_family(adult="Ravi Patil", kids=["Meera Patil", "Dev"]))

    assert response.status_code == 422
    assert response.json()["detail"] == "You can bring at most 2 guests to this event"


# --- conditional validation -----------------------------------------------------


def test_more_than_four_kids_is_rejected(client, mailbox, make_event):
    kids = ["Meera Patil", "Kiran Patil", "Tara Patil", "Dev Patil", "Ria Patil"]

    response = post(client, make_event(), with_family(kids=kids))

    assert response.status_code == 422
    assert "at most 4 kids" in response.text
    assert mailbox.sent == []


@pytest.mark.parametrize(
    "extra",
    [
        {"adult_name": ["Ravi Patil", "Meera Patil"]},  # a list of adults
        {"adult_names": ["Ravi Patil", "Meera Patil"]},  # an unknown field
        {"accompanying_adult": 2},  # a count instead of a yes/no
    ],
)
def test_more_than_one_adult_is_rejected(client, mailbox, make_event, extra):
    data = {**with_family(adult="Ravi Patil"), **extra}

    assert post(client, make_event(), data).status_code == 422
    assert mailbox.sent == []


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({"attending": True, "food_preference": "VEG"}, "family_attending is required"),
        ({"attending": True, "family_attending": None, "food_preference": "VEG"}, "family_attending is required"),
        (
            {"attending": True, "family_attending": True, "food_preference": "VEG"},
            "select Adult, Kids or both",
        ),
        (
            {"attending": True, "family_attending": True, "accompanying_adult": True, "food_preference": "VEG"},
            "adult_name is required",
        ),
        (
            {"attending": True, "family_attending": True, "accompanying_kids": True, "food_preference": "VEG"},
            "at least one kid's name",
        ),
        (
            {
                "attending": True,
                "family_attending": True,
                "accompanying_kids": True,
                "kid_names": [],
                "food_preference": "VEG",
            },
            "at least one kid's name",
        ),
        ({"attending": True, "family_attending": True, "accompanying_adult": True, "adult_name": "Ravi Patil"}, "food"),
    ],
)
def test_required_conditional_fields_are_enforced(client, mailbox, make_event, answers, message):
    response = post(client, make_event(), body(**answers))

    assert response.status_code == 422
    assert message in response.text
    assert mailbox.sent == []


@pytest.mark.parametrize(
    "stray",
    [
        {"accompanying_adult": True, "adult_name": "Ravi Patil"},
        {"adult_name": "Ravi Patil"},
        {"accompanying_kids": True, "kid_names": ["Meera Patil"]},
        {"kid_names": ["Meera Patil"]},
        {"accompanying_adult": True},
    ],
)
def test_family_member_details_are_rejected_when_attending_alone(client, mailbox, make_event, stray):
    data = body(attending=True, family_attending=False, food_preference="VEG", **stray)

    response = post(client, make_event(), data)

    assert response.status_code == 422
    assert "family member details must not be sent" in response.text


def test_adult_name_without_adult_selected_is_rejected(client, mailbox, make_event):
    data = {**with_family(kids=["Meera Patil"]), "adult_name": "Ravi Patil"}

    response = post(client, make_event(), data)

    assert response.status_code == 422
    assert "adult_name must not be sent" in response.text


def test_kid_names_without_kids_selected_are_rejected(client, mailbox, make_event):
    data = {**with_family(adult="Ravi Patil"), "kid_names": ["Meera Patil"]}

    response = post(client, make_event(), data)

    assert response.status_code == 422
    assert "kid_names must not be sent" in response.text


@pytest.mark.parametrize("name", ["R", "x" * 101, "Meera\nPatil", "   "])
def test_family_names_are_validated_like_employee_names(client, mailbox, make_event, name):
    event = make_event()

    assert post(client, event, with_family(adult=name)).status_code == 422
    assert post(client, event, with_family(kids=["Meera Patil", name])).status_code == 422


@pytest.mark.parametrize("value", ["yes", "true", 1, None])
def test_attending_must_be_a_strict_yes_or_no(client, mailbox, make_event, value):
    data = {**registration_body(), "attending": value}

    assert post(client, make_event(), data).status_code == 422


def test_reducing_the_family_clears_dropped_members(client, mailbox, make_event, otp_limits, db_session):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    post(client, event, with_family(adult="Ravi Patil", kids=["Meera Patil", "Kiran Patil"]))

    post(client, event, body(attending=True, family_attending=False, food_preference="JAIN"))

    row = db_session.scalars(select(Registration)).one()
    db_session.refresh(row)
    assert (row.family_attending, row.number_of_guests, row.guest_names) == (False, 0, [])
    assert (row.adult_name, row.kid_names, row.food_preference) == (None, [], "JAIN")


# --- food preference --------------------------------------------------------------


@pytest.mark.parametrize("food", ["VEG", "JAIN", "FAST_FOOD"])
def test_each_food_preference_is_accepted(client, mailbox, make_event, db_session, food):
    started = post(client, make_event(), with_family(adult="Ravi Patil", food=food))
    guest_pass = verify(client, started.json()["registration_id"], mailbox.last_code).json()

    assert guest_pass["food_preference"] == food
    assert db_session.scalars(select(Registration)).one().food_preference == food


@pytest.mark.parametrize("food", ["NON_VEG", "veg", "Veg", "Fast Food", "", 1, ["VEG", "JAIN"]])
def test_unsupported_food_preferences_are_rejected(client, mailbox, make_event, food):
    response = post(client, make_event(), with_family(adult="Ravi Patil", food=food))

    assert response.status_code == 422
    assert mailbox.sent == []


def test_solo_attendee_food_preference_follows_the_setting(client, mailbox, make_event, monkeypatch):
    event = make_event()
    solo_without_food = body(attending=True, family_attending=False)

    monkeypatch.setattr(schemas, "FOOD_PREFERENCE_REQUIRED_WHEN_ALONE", True)
    assert post(client, event, solo_without_food).status_code == 422

    monkeypatch.setattr(schemas, "FOOD_PREFERENCE_REQUIRED_WHEN_ALONE", False)
    assert post(client, event, solo_without_food).status_code == 202
    # A family party must always choose.
    assert post(client, event, {**with_family(adult="Ravi Patil"), "food_preference": None}).status_code == 422


# --- admin view -----------------------------------------------------------------------


def test_admin_list_shows_attendance_family_and_food(client, mailbox, make_event, login_as, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    declined = post(client, event, body(attending=False, employee_id="MT-1", email="a@example.com"))
    verify(client, declined.json()["registration_id"], mailbox.last_code)
    post(client, event, {**with_family(kids=["Meera Patil"], food="FAST_FOOD"), "employee_id": "MT-2"})
    login_as("admin")

    items = client.get(f"/api/v1/events/{event.id}/registrations").json()["items"]
    declined_rows = client.get(f"/api/v1/events/{event.id}/registrations?status=DECLINED").json()["items"]

    family, decline = items  # newest first
    assert (decline["status"], decline["attending"], decline["food_preference"]) == ("DECLINED", False, None)
    assert (family["family_attending"], family["kid_names"], family["food_preference"]) == (
        True,
        ["Meera Patil"],
        "FAST_FOOD",
    )
    assert [row["employee_id"] for row in declined_rows] == ["MT-1"]
