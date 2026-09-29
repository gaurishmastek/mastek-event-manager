"""SMTP failures on each OTP delivery path: guest registration, admin 2FA and officer sign-in.

The real `SmtpEmailSender` runs against a fake `smtplib`, so these cover everything up to the network: the API answers
a generic 503, nothing from the failed attempt is saved (no challenge, no registration), the attempt does not use up a
rate limit, and nothing secret reaches the logs.
"""

import logging
import smtplib

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.main import app
from app.modules.guests.models import Registration
from app.modules.notifications.email import SmtpEmailSender, get_email_sender
from app.modules.otp.models import OtpChallenge
from tests.conftest import PASSWORD as ADMIN_PASSWORD
from tests.guest_fixtures import FakeMailbox

SMTP_PASSWORD = "Smtp-pa55-never-logged"
SMTP_SETTINGS = Settings(
    email_provider="smtp",
    smtp_host="smtp.example.com",
    email_from="Mastek Events <events@example.com>",
    smtp_username="mailer@example.com",
    smtp_password=SMTP_PASSWORD,
)


class RejectingSmtp:
    """Accepts the connection and STARTTLS, then rejects the login like a provider with a wrong password."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, username, password):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Incorrect authentication data for mailer@example.com")

    def send_message(self, message):  # pragma: no cover - never reached
        raise AssertionError("sent after a failed login")


@pytest.fixture()
def failing_smtp(monkeypatch, caplog):
    monkeypatch.setattr(smtplib, "SMTP", RejectingSmtp)
    app.dependency_overrides[get_email_sender] = lambda: SmtpEmailSender(SMTP_SETTINGS)
    caplog.set_level(logging.WARNING)
    return caplog


def use_working_mailbox() -> FakeMailbox:
    mailbox = FakeMailbox()
    app.dependency_overrides[get_email_sender] = lambda: mailbox
    return mailbox


def assert_logs_are_safe(caplog, *also_secret: str) -> None:
    text = caplog.text
    assert "kind=auth" in text and "code=535" in text
    for secret in (SMTP_PASSWORD, "mailer@example.com", "events@example.com", "verification code is", *also_secret):
        assert secret not in text


def test_guest_registration_rolls_back_and_answers_503(
    client, failing_smtp, register, make_event, db_session, otp_limits
):
    otp_limits(otp_max_per_email_per_hour=1)
    event = make_event()

    response = register(event.id, email="asha.patil@example.com")

    assert response.status_code == 503
    assert response.json() == {"detail": "OTP could not be sent. Please try again later."}
    assert db_session.scalars(select(OtpChallenge)).all() == []
    assert db_session.scalars(select(Registration)).all() == []
    assert_logs_are_safe(failing_smtp, "asha.patil@example.com")

    # The failure did not use up the one-per-hour allowance.
    mailbox = use_working_mailbox()
    assert register(event.id, email="asha.patil@example.com").status_code == 202
    assert len(mailbox.sent) == 1


def test_admin_second_factor_rolls_back_and_answers_503(client, failing_smtp, admin, db, otp_limits):
    otp_limits(otp_max_per_email_per_hour=1)

    response = client.post("/api/v1/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD})

    assert response.status_code == 503
    assert response.json() == {"detail": "The code could not be sent. Please try again later."}
    db.rollback()
    assert db.scalars(select(OtpChallenge)).all() == []
    assert_logs_are_safe(failing_smtp, admin.email)

    use_working_mailbox()
    assert client.post("/api/v1/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD}).status_code == 200


def test_officer_code_rolls_back_and_answers_503(client, failing_smtp, officer, db, otp_limits):
    otp_limits(otp_max_per_email_per_hour=1)

    response = client.post("/api/v1/auth/officer/otp", json={"email": officer.email})

    assert response.status_code == 503
    assert response.json() == {"detail": "The code could not be sent. Please try again later."}
    db.rollback()
    assert db.scalars(select(OtpChallenge)).all() == []
    assert_logs_are_safe(failing_smtp, officer.email)

    mailbox = use_working_mailbox()
    assert client.post("/api/v1/auth/officer/otp", json={"email": officer.email}).status_code == 202
    assert len(mailbox.sent) == 1


def test_disabled_provider_answers_503_on_every_path(client, admin, officer, register, make_event, monkeypatch):
    from app.modules.notifications import email as email_module

    monkeypatch.setattr(email_module, "get_settings", lambda: Settings(email_provider="disabled"))
    app.dependency_overrides.pop(get_email_sender, None)

    assert register(make_event().id).status_code == 503
    assert client.post("/api/v1/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD}).status_code == 503
    assert client.post("/api/v1/auth/officer/otp", json={"email": officer.email}).status_code == 503
