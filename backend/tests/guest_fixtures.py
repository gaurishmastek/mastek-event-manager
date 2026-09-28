import re
import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from app.db.mixins import utcnow
from app.main import app
from app.modules.events.models import Event
from app.modules.notifications.email import EmailDeliveryError, get_email_sender


class FakeMailbox:
    """Captures emails instead of sending them. `sent` holds (address, OTP code) pairs."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.fail = False

    def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise EmailDeliveryError("provider down")
        self.messages.append((to, subject, body))

    @property
    def sent(self) -> list[tuple[str, str]]:
        return [(to, re.search(r"\b(\d{6})\b", body).group(1)) for to, _, body in self.messages]

    @property
    def last_code(self) -> str:
        return self.sent[-1][1]


@pytest.fixture()
def mailbox():
    fake = FakeMailbox()
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake


@pytest.fixture()
def otp_limits(monkeypatch):
    """Tighten or relax OTP limits for one test, e.g. otp_limits(otp_resend_cooldown_seconds=0)."""

    def _set(**values):
        for name, value in values.items():
            monkeypatch.setattr(settings, name, value)

    return _set


@pytest.fixture()
def make_event(db_session):
    def _make(
        capacity: int = 100,
        starts_in: timedelta = timedelta(days=5),
        duration: timedelta | None = None,
        max_guests: int = 5,
    ) -> Event:
        starts_at = utcnow() + starts_in
        event = Event(
            title="Navratri Garba Night",
            location="Mastek campus, Mumbai",
            starts_at=starts_at,
            ends_at=starts_at + (duration if duration is not None else timedelta(hours=5)),
            capacity=capacity,
            max_guests_per_registration=max_guests,
            created_by=1,
            updated_by=1,
        )
        db_session.add(event)
        db_session.commit()
        return event

    return _make


def public_id_of(db_session, event_id: int) -> str:
    """The event's public link id. Unknown ids get a random UUID, which the API must treat as not found."""
    event = db_session.get(Event, event_id)
    return event.public_id if event is not None else str(uuid.uuid4())


def registration_body(
    email: str = "asha.patil@example.com", name: str = "Asha Patil", guests: list[str] | None = None, **extra
) -> dict:
    """A valid form submission. The employee id defaults to the email's local part, so distinct emails
    are distinct employees."""
    guests = guests or []
    return {
        "employee_id": email.strip().split("@")[0],
        "employee_name": name,
        "email": email,
        "mobile": "98765 43210",
        "number_of_guests": len(guests),
        "guest_names": guests,
        "consent": True,
        **extra,
    }


@pytest.fixture()
def register(client, db_session):
    def _register(
        event_id: int,
        email: str = "asha.patil@example.com",
        name: str = "Asha Patil",
        guests: list[str] | None = None,
        **extra,
    ):
        body = registration_body(email, name, guests, **extra)
        return client.post(f"/api/v1/public/events/{public_id_of(db_session, event_id)}/registrations", json=body)

    return _register


@pytest.fixture()
def issue_pass(client, mailbox, register, otp_limits):
    """Register and verify a guest; returns the pass JSON."""
    otp_limits(otp_resend_cooldown_seconds=0)

    def _issue(
        event_id: int,
        email: str = "asha.patil@example.com",
        name: str = "Asha Patil",
        guests: list[str] | None = None,
        **extra,
    ) -> dict:
        started = register(event_id, email=email, name=name, guests=guests, **extra)
        assert started.status_code == 202, started.text
        verified = client.post(
            f"/api/v1/public/registrations/{started.json()['registration_id']}/verify", json={"code": mailbox.last_code}
        )
        assert verified.status_code == 200, verified.text
        return verified.json()

    return _issue
