import logging
import smtplib
import socket
import ssl

import pytest

from app.core.config import Settings
from app.modules.notifications import email as email_module
from app.modules.notifications.email import (
    ConsoleEmailSender,
    DisabledEmailSender,
    EmailDeliveryError,
    SmtpEmailSender,
    email_config_summary,
    get_email_sender,
    redact_smtp_reply,
)

SMTP = {"email_provider": "smtp", "smtp_host": "smtp.example.com", "email_from": "Mastek Events <events@example.com>"}


class FakeSmtp:
    instances: list["FakeSmtp"] = []
    # step name -> exception raised at that step ("connect", "starttls", "login", "send")
    failures: dict[str, BaseException] = {}

    def __init__(self, host, port, timeout=None, context=None):
        if "connect" in FakeSmtp.failures:
            raise FakeSmtp.failures["connect"]
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[str] = []
        self.message = None
        self.starttls_context = None
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _step(self, name):
        self.calls.append(name)
        if name in FakeSmtp.failures:
            raise FakeSmtp.failures[name]

    def starttls(self, context=None):
        self.starttls_context = context
        self._step("starttls")

    def login(self, username, password):
        self._step(f"login:{username}")
        if "login" in FakeSmtp.failures:
            raise FakeSmtp.failures["login"]

    def send_message(self, message):
        self.message = message
        self._step("send")


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    FakeSmtp.failures = {}
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
    # STARTTLS verifies the server certificate and host name; there is no unverified fallback.
    assert server.starttls_context.verify_mode == ssl.CERT_REQUIRED
    assert server.starttls_context.check_hostname


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


def test_smtp_ssl_uses_implicit_tls_with_verification_then_login(fake_smtp):
    SmtpEmailSender(
        Settings(**SMTP, smtp_security="ssl", smtp_port=465, smtp_username="mailer", smtp_password="pw")
    ).send("a@example.com", "s", "b")

    server = fake_smtp[0]
    assert server.port == 465
    assert server.calls == ["login:mailer", "send"]
    assert server.context.verify_mode == ssl.CERT_REQUIRED


PASSWORD = "Pa55-never-logged"
LOGIN = {"smtp_username": "mailer@example.com", "smtp_password": PASSWORD}


@pytest.mark.parametrize(
    ("step", "exc", "kind", "stage", "code"),
    [
        ("connect", socket.gaierror(11001, "getaddrinfo failed"), "dns", "connect", None),
        ("connect", ConnectionRefusedError(10061, "refused"), "connect", "connect", None),
        ("connect", TimeoutError("timed out"), "timeout", "connect", None),
        ("connect", smtplib.SMTPConnectError(421, b"Service not available"), "connect", "connect", 421),
        ("starttls", ssl.SSLCertVerificationError(1, "certificate verify failed"), "tls", "starttls", None),
        (
            "starttls",
            smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server."),
            "tls",
            "starttls",
            None,
        ),
        ("login", smtplib.SMTPAuthenticationError(535, b"5.7.8 Incorrect authentication data"), "auth", "login", 535),
        ("login", smtplib.SMTPException("No suitable authentication method found."), "auth", "login", None),
        ("login", TimeoutError("timed out"), "timeout", "login", None),
        (
            "send",
            smtplib.SMTPSenderRefused(553, b"5.7.1 <events@example.com> not owned by user", "events@example.com"),
            "sender_rejected",
            "send",
            553,
        ),
        (
            "send",
            smtplib.SMTPRecipientsRefused({"asha@example.com": (550, b"5.1.1 <asha@example.com> unknown")}),
            "recipient_rejected",
            "send",
            550,
        ),
        (
            "send",
            smtplib.SMTPDataError(554, b"5.7.1 Relay access denied for asha@example.com"),
            "data_rejected",
            "send",
            554,
        ),
        ("send", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "connect", "send", None),
    ],
)
def test_smtp_failures_are_classified_and_logged_safely(fake_smtp, caplog, step, exc, kind, stage, code):
    FakeSmtp.failures = {step: exc}
    caplog.set_level(logging.WARNING, logger="app.modules.notifications.email")

    with pytest.raises(EmailDeliveryError) as raised:
        SmtpEmailSender(Settings(**SMTP, **LOGIN)).send("asha.patil@example.com", "Your code", "Your code is 482913.")

    error = raised.value
    assert (error.kind, error.stage, error.smtp_code) == (kind, stage, code)
    logged = caplog.text + str(error)
    assert f"kind={kind}" in caplog.text and f"stage={stage}" in caplog.text
    for secret in (
        PASSWORD,
        "482913",
        "Your code is",
        "asha.patil@example.com",
        "asha@example.com",
        "events@example.com",
        "mailer@example.com",
    ):
        assert secret not in logged
    assert "as•••@example.com" in caplog.text  # the recipient, masked


def test_redact_smtp_reply_strips_addresses_and_newlines():
    reply = b"5.1.1 <asha.patil@example.com>: Recipient address rejected\r\nsee https://x.test/help"
    redacted = redact_smtp_reply(reply)
    assert "asha.patil" not in redacted and "<address>" in redacted
    assert "\r" not in redacted and "\n" not in redacted
    assert len(redact_smtp_reply("x" * 1000)) == 160


def test_disabled_sender_explains_itself(caplog):
    caplog.set_level(logging.WARNING, logger="app.modules.notifications.email")
    with pytest.raises(EmailDeliveryError) as raised:
        DisabledEmailSender().send("a@example.com", "s", "b")
    assert raised.value.kind == "not_configured"
    assert "EMAIL_PROVIDER is disabled" in caplog.text


def test_config_summary_hides_the_password_and_masks_addresses():
    settings = Settings(**SMTP, **LOGIN)
    summary = email_config_summary(settings)
    text = repr(summary)
    assert PASSWORD not in text and "mailer@example.com" not in text and "events@example.com" not in text
    assert summary["smtp_password_configured"] is True
    assert summary["email_from"] == "ev•••@example.com"
    assert summary["smtp_username"] == "ma•••@example.com"
    assert (summary["email_provider"], summary["smtp_host"], summary["smtp_port"]) == ("smtp", "smtp.example.com", 587)
