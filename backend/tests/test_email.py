import smtplib

import pytest

from app.core.config import Settings
from app.modules.notifications import email as email_module
from app.modules.notifications.email import (
    ConsoleEmailSender,
    DisabledEmailSender,
    EmailDeliveryError,
    SmtpEmailSender,
    get_email_sender,
)

SMTP = {"email_provider": "smtp", "smtp_host": "smtp.example.com", "email_from": "Mastek Events <events@example.com>"}


class FakeSmtp:
    instances: list["FakeSmtp"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.message = None
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(f"login:{username}")

    def send_message(self, message):
        self.calls.append("send")
        self.message = message


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp.instances


def test_smtp_uses_starttls_and_login(fake_smtp):
    settings = Settings(**SMTP, smtp_username="mailer", smtp_password="secret")

    SmtpEmailSender(settings).send("asha@example.com", "Your code", "Your code is 123456.")

    server = fake_smtp[0]
    assert (server.host, server.port) == ("smtp.example.com", 587)
    assert server.calls == ["starttls", "login:mailer", "send"]
    assert server.message["To"] == "asha@example.com"
    assert server.message["From"] == "Mastek Events <events@example.com>"
    assert "123456" in server.message.get_content()


def test_smtp_ssl_skips_starttls_and_login_without_username(fake_smtp):
    SmtpEmailSender(Settings(**SMTP, smtp_security="ssl", smtp_port=465)).send("a@example.com", "s", "b")

    assert fake_smtp[0].calls == ["send"]


def test_smtp_failure_becomes_delivery_error(monkeypatch):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    with pytest.raises(EmailDeliveryError):
        SmtpEmailSender(Settings(**SMTP)).send("a@example.com", "s", "b")


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"email_provider": "disabled"}, DisabledEmailSender),
        ({"email_provider": "console"}, ConsoleEmailSender),
        (SMTP, SmtpEmailSender),
    ],
)
def test_provider_is_picked_from_settings(monkeypatch, values, expected):
    monkeypatch.setattr(email_module, "get_settings", lambda: Settings(**values))
    assert isinstance(get_email_sender(), expected)


def test_console_sender_masks_the_address(capsys):
    ConsoleEmailSender().send("asha.patil@example.com", "Your code", "Your code is 123456.")

    out = capsys.readouterr().out
    assert "as•••@example.com" in out and "asha.patil" not in out
    assert "123456" in out


def test_disabled_sender_refuses():
    with pytest.raises(EmailDeliveryError):
        DisabledEmailSender().send("a@example.com", "s", "b")
