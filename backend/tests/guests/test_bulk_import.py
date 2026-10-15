"""The operator import bypasses guest OTP while preserving capacity and pass delivery rules."""

import json

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.core.crypto import decrypt_pii
from app.modules.guests import bulk_import
from app.modules.guests.bulk_import import import_verified, load_batch
from app.modules.guests.models import Registration, RegistrationStatus
from tests.guest_fixtures import FakeMailbox


def _row(employee_id: str, *, guests: bool = False) -> dict:
    return {
        "employee_id": employee_id,
        "employee_name": f"Employee {employee_id}",
        "email_id": f"employee{employee_id}@example.com",
        "location": "mahape",
        "attending": "yes",
        "family_attending": "yes" if guests else "no",
        "guest_names": "Adult Guest, Kid Guest" if guests else None,
        "adult_name": "Adult Guest" if guests else None,
        "kid_names": "Kid Guest" if guests else None,
        "kid_ages_1": 12 if guests else None,
        "kids_ages_2": None,
        "kids_ages_3": None,
        "food_preference": "veg",
        "number_of_guests": 2 if guests else 0,
        "party_size": 3 if guests else 1,
    }


def _load(tmp_path, rows, overrides=None):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(rows), encoding="utf-8")
    if overrides is None:
        return load_batch(source)
    corrections = tmp_path / "corrections.json"
    corrections.write_text(json.dumps(overrides), encoding="utf-8")
    return load_batch(source, corrections)


def test_import_creates_verified_parties_and_emails_passes(tmp_path, db_session, make_event):
    event = make_event(capacity=4)
    batch = _load(tmp_path, [_row("100", guests=True), _row("101")])
    mailbox = FakeMailbox()

    result = import_verified(db_session, mailbox, event_id=event.id, expected_title=event.title, batch=batch)

    assert result.seats_added == 4
    assert result.emails_accepted == ("100", "101")
    assert not result.emails_failed
    assert not mailbox.messages  # No OTP was issued.
    assert len(mailbox.passes) == 2
    assert all(message[3][0].content.startswith(b"\x89PNG") for message in mailbox.passes)
    rows = list(db_session.scalars(select(Registration).order_by(Registration.employee_id)))
    assert [row.status for row in rows] == [RegistrationStatus.VERIFIED.value] * 2
    assert [row.party_size for row in rows] == [3, 1]
    assert rows[0].guest_names == ["Adult Guest", "Kid Guest"]
    assert [row.age for row in rows[0].guests] == [None, 12]
    assert rows[0].verified_at and rows[0].qr_issued_at and rows[0].qr_token_hash
    assert decrypt_pii(rows[0].email_encrypted) == "employee100@example.com"


def test_import_rejects_full_batch_if_capacity_insufficient(tmp_path, db_session, make_event):
    event = make_event(capacity=3)
    batch = _load(tmp_path, [_row("100", guests=True), _row("101")])
    mailbox = FakeMailbox()

    with pytest.raises(ValueError, match="capacity"):
        import_verified(db_session, mailbox, event_id=event.id, expected_title=event.title, batch=batch)

    assert list(db_session.scalars(select(Registration))) == []
    assert mailbox.passes == []


def test_import_rejects_existing_employee_without_sending(tmp_path, db_session, make_event):
    event = make_event()
    batch = _load(tmp_path, [_row("100")])
    mailbox = FakeMailbox()
    import_verified(db_session, mailbox, event_id=event.id, expected_title=event.title, batch=batch)

    with pytest.raises(ValueError, match="already registered"):
        import_verified(db_session, mailbox, event_id=event.id, expected_title=event.title, batch=batch)

    assert len(list(db_session.scalars(select(Registration)))) == 1
    assert len(mailbox.passes) == 1


def test_import_rejects_wrong_encryption_key_before_writing(tmp_path, db_session, make_event, monkeypatch):
    event = make_event()
    mailbox = FakeMailbox()
    import_verified(
        db_session,
        mailbox,
        event_id=event.id,
        expected_title=event.title,
        batch=_load(tmp_path, [_row("100")]),
    )

    def wrong_key(_value):
        raise InvalidToken

    monkeypatch.setattr(bulk_import, "decrypt_pii", wrong_key)
    with pytest.raises(ValueError, match="PII_ENCRYPTION_KEY"):
        import_verified(
            db_session,
            mailbox,
            event_id=event.id,
            expected_title=event.title,
            batch=_load(tmp_path, [_row("101")]),
        )
    assert len(list(db_session.scalars(select(Registration)))) == 1
    assert len(mailbox.passes) == 1


def test_load_batch_requires_explicit_corrections_for_ambiguous_values(tmp_path):
    row = _row("100", guests=True)
    row["adult_name"] = "Adult Guest, Kid Guest"
    row["kid_names"] = None
    row["kid_ages_1"] = None

    with pytest.raises(ValueError, match="multiple names"):
        _load(tmp_path, [row])

    batch = _load(
        tmp_path,
        [row],
        {"100": {"adult_name": "Adult Guest", "kid_names": "Kid Guest", "kid_ages_1": 12}},
    )
    assert len(batch[0].accompanying_guests) == 2
