from datetime import timedelta

import pytest

from app.modules.events.models import OfficerEvent


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
