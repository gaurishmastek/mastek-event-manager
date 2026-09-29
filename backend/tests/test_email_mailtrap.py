import logging

import mailtrap as mt
import pytest
import requests
from pydantic import ValidationError

from app import cli
from app.core.config import Settings
from app.modules.notifications import email as email_module
from app.modules.notifications.email import (
    EmailDeliveryError,
    MailtrapEmailSender,
    classify_mailtrap_failure,
    email_config_summary,
    get_email_sender,
)

TOKEN = "mt-test-token-5f1e9c"  # noqa: S105 - fake
MAILTRAP = {
    "email_provider": "mailtrap",
    "mailtrap_api_token": TOKEN,
    "email_from": "Mastek Events <events@mastek.test>",
}


class FakeClient:
    instances: list["FakeClient"] = []
    failure: BaseException | None = None

    def __init__(self, token, **kwargs):
        self.token = token
        self.mail = None
        FakeClient.instances.append(self)

    def send(self, mail):
        self.mail = mail
        if FakeClient.failure is not None:
            raise FakeClient.failure
        return {"success": True, "message_ids": ["abc"]}


@pytest.fixture
def fake_mailtrap(monkeypatch):
    FakeClient.instances = []
    FakeClient.failure = None
    monkeypatch.setattr(mt, "MailtrapClient", FakeClient)
    return FakeClient


def test_sends_plain_text_mail_with_the_configured_token_sender_and_category(fake_mailtrap):
    MailtrapEmailSender(Settings(**MAILTRAP)).send("asha@example.com", "Your code", "Your code is 123456.")
    (client,) = fake_mailtrap.instances
    assert client.token == TOKEN
    mail = client.mail
    assert (mail.sender.email, mail.sender.name) == ("events@mastek.test", "Mastek Events")
    assert [address.email for address in mail.to] == ["asha@example.com"]
    assert (mail.subject, mail.text, mail.category) == ("Your code", "Your code is 123456.", "Mastek Event Manager")


def test_bare_sender_address_has_no_display_name(fake_mailtrap):
    MailtrapEmailSender(Settings(**{**MAILTRAP, "email_from": "events@mastek.test"})).send("a@example.com", "s", "b")
    assert fake_mailtrap.instances[0].mail.sender.name is None


def test_provider_selects_the_mailtrap_sender(monkeypatch):
    monkeypatch.setattr(email_module, "get_settings", lambda: Settings(**MAILTRAP))
    assert isinstance(get_email_sender(), MailtrapEmailSender)


@pytest.mark.parametrize("missing", ["mailtrap_api_token", "email_from"])
def test_mailtrap_needs_a_token_and_a_sender(missing):
    with pytest.raises(ValidationError, match="MAILTRAP_API_TOKEN and EMAIL_FROM"):
        Settings(**{**MAILTRAP, missing: ""})


def test_token_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "mailtrap")
    monkeypatch.setenv("MAILTRAP_API_TOKEN", TOKEN)
    monkeypatch.setenv("EMAIL_FROM", "events@mastek.test")
    settings = Settings(_env_file=None)
    assert (settings.email_provider, settings.mailtrap_api_token) == ("mailtrap", TOKEN)


def test_mailtrap_is_allowed_in_production():
    safe = {"secret_key": "s" * 40, "pii_encryption_key": "Zm9vYmFyYmF6cXV4cXV1eGZvb2JhcmJhenF1eHF1dXg="}
    assert Settings(environment="production", **MAILTRAP, **safe).email_provider == "mailtrap"


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (mt.AuthorizationError(["Unauthorized"]), "auth"),
        (mt.APIError(403, ["Forbidden"]), "sender_rejected"),
        (mt.APIError(429, ["Too many requests"]), "rate_limited"),
        (mt.APIError(400, ["'to' address is invalid"]), "data_rejected"),
        (mt.APIError(500, ["Internal error"]), "unknown"),
        (requests.exceptions.SSLError("bad cert"), "tls"),
        (requests.exceptions.ConnectTimeout("slow"), "timeout"),
        (requests.exceptions.ReadTimeout("slow"), "timeout"),
        (requests.exceptions.ConnectionError("refused"), "connect"),
    ],
)
def test_failures_are_classified(exc, kind):
    assert classify_mailtrap_failure(exc) == kind


def test_failure_raises_delivery_error_and_logs_without_secrets(fake_mailtrap, caplog):
    caplog.set_level(logging.WARNING, logger="app.modules.notifications.email")
    fake_mailtrap.failure = mt.APIError(400, ["Invalid recipient asha.patil@example.com"])
    with pytest.raises(EmailDeliveryError) as raised:
        MailtrapEmailSender(Settings(**MAILTRAP)).send("asha.patil@example.com", "Your code", "Your code is 482913.")
    assert raised.value.kind == "data_rejected"
    logged = caplog.text + str(raised.value)
    for secret in (TOKEN, "482913", "asha.patil@example.com", "events@mastek.test"):
        assert secret not in logged
    assert "status=400" in caplog.text and "<address>" in caplog.text


def test_config_summary_reports_the_token_only_as_configured():
    summary = email_config_summary(Settings(**MAILTRAP))
    assert TOKEN not in repr(summary)
    assert summary["mailtrap_api_token_configured"] is True
    assert summary["email_provider"] == "mailtrap"


def test_cli_send_test_email(monkeypatch, capsys):
    sent = []

    class Recorder:
        def send(self, to, subject, body):
            sent.append((to, subject))

    monkeypatch.setattr(cli, "get_email_sender", lambda: Recorder())
    assert cli.main(["send-test-email", "--to", "gaurish@example.com"]) == 0
    assert sent == [("gaurish@example.com", "Mastek Event Manager test email")]
    assert "Accepted" in capsys.readouterr().out


def test_cli_send_test_email_reports_failure(monkeypatch, capsys):
    class Failing:
        def send(self, to, subject, body):
            raise EmailDeliveryError("Mailtrap delivery failed: auth", kind="auth")

    monkeypatch.setattr(cli, "get_email_sender", lambda: Failing())
    assert cli.main(["send-test-email", "--to", "gaurish@example.com"]) == 1
    assert "Not sent" in capsys.readouterr().err
