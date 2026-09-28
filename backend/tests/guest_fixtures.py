from datetime import timedelta

import pytest

from app.core.config import settings
from app.db.mixins import utcnow
from app.main import app
from app.modules.events.models import Event
from app.modules.otp.sms import SmsDeliveryError, get_sms_sender


class FakeSms:
    """Captures OTPs instead of sending them."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False

    def send_otp(self, mobile: str, code: str) -> None:
        if self.fail:
            raise SmsDeliveryError("provider down")
        self.sent.append((mobile, code))

    @property
    def last_code(self) -> str:
        return self.sent[-1][1]


@pytest.fixture()
def sms():
    fake = FakeSms()
    app.dependency_overrides[get_sms_sender] = lambda: fake
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
        capacity: int = 100, starts_in: timedelta = timedelta(days=5), duration: timedelta | None = None
    ) -> Event:
        starts_at = utcnow() + starts_in
        event = Event(
            title="Navratri Garba Night",
            location="Mastek campus, Mumbai",
            starts_at=starts_at,
            ends_at=starts_at + (duration if duration is not None else timedelta(hours=5)),
            capacity=capacity,
            created_by=1,
            updated_by=1,
        )
        db_session.add(event)
        db_session.commit()
        return event

    return _make


@pytest.fixture()
def register(client):
    def _register(event_id: int, mobile: str = "98765 43210", name: str = "Asha Patil", **extra):
        body = {"guest_name": name, "mobile": mobile, "consent": True, **extra}
        return client.post(f"/api/v1/public/events/{event_id}/registrations", json=body)

    return _register


@pytest.fixture()
def issue_pass(client, sms, register, otp_limits):
    """Register and verify a guest; returns the pass JSON."""
    otp_limits(otp_resend_cooldown_seconds=0)

    def _issue(event_id: int, mobile: str = "98765 43210", name: str = "Asha Patil") -> dict:
        started = register(event_id, mobile=mobile, name=name)
        assert started.status_code == 202, started.text
        verified = client.post(
            f"/api/v1/public/registrations/{started.json()['registration_id']}/verify", json={"code": sms.last_code}
        )
        assert verified.status_code == 200, verified.text
        return verified.json()

    return _issue
