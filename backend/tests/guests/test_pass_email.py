"""The QR pass is emailed to the verified address as soon as it is issued."""

import base64

import mailtrap as mt
from sqlalchemy import select

from app.core.config import Settings
from app.modules.guests.models import Registration
from app.modules.notifications.email import (
    ConsoleEmailSender,
    EmailAttachment,
    MailtrapEmailSender,
    SmtpEmailSender,
)
from tests.guest_fixtures import registration_body

BASE = "/api/v1/public"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def verify(client, registration_id: str, code: str):
    return client.post(f"{BASE}/registrations/{registration_id}/verify", json={"code": code})


def test_verified_pass_is_emailed_with_the_qr_attached(client, mailbox, register, make_event):
    event = make_event()
    registration_id = register(event.id, guests=["Ravi Patil", "Anu Patil"]).json()["registration_id"]

    response = verify(client, registration_id, mailbox.last_code)

    assert response.status_code == 200, response.text
    ((to, subject, body, attachments),) = mailbox.passes
    assert to == "asha.patil@example.com"
    assert subject == "Your entry pass for Navratri Garba Night"
    assert "admits 3 people once" in body
    assert "Asha Patil (asha.patil)" in body and "Ravi Patil (adult)" in body and "Anu Patil (kid, age 8)" in body
    assert "Mastek campus, Mumbai" in body and "IST" in body
    (attachment,) = attachments
    assert (attachment.filename, attachment.mime_type) == ("entry-pass.png", "image/png")
    assert attachment.content.startswith(PNG_MAGIC)
    # The QR carries only the token, which is never written into the email text.
    assert response.json()["qr_token"] not in body


def test_reverifying_emails_the_new_pass(client, mailbox, register, make_event, otp_limits):
    otp_limits(otp_resend_cooldown_seconds=0)
    event = make_event()
    registration_id = register(event.id).json()["registration_id"]
    verify(client, registration_id, mailbox.last_code)
    register(event.id)
    verify(client, registration_id, mailbox.last_code)

    assert len(mailbox.passes) == 2
    assert mailbox.passes[0][3][0].content != mailbox.passes[1][3][0].content


def test_declined_registration_gets_no_pass_email(client, mailbox, make_event, db_session):
    event = make_event()
    started = client.post(
        f"{BASE}/events/{event.public_id}/registrations",
        json={
            k: v
            for k, v in registration_body(attending=False).items()
            if k not in ("family_attending", "food_preference")
        },
    )
    assert started.status_code == 202, started.text

    assert verify(client, started.json()["registration_id"], mailbox.last_code).status_code == 200
    assert mailbox.passes == []


def test_pass_is_still_issued_when_the_email_fails(client, mailbox, register, make_event, db_session):
    event = make_event()
    registration_id = register(event.id).json()["registration_id"]
    code = mailbox.last_code
    mailbox.fail = True

    response = verify(client, registration_id, code)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "VERIFIED"
    assert db_session.scalars(select(Registration)).one().qr_token_hash is not None


PNG = EmailAttachment(filename="entry-pass.png", content=PNG_MAGIC + b"rest", mime_type="image/png")


def test_smtp_sender_adds_attachments(monkeypatch):
    sent = []

    class Server:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            pass

        def send_message(self, message):
            sent.append(message)

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", Server)
    settings = Settings(email_provider="smtp", smtp_host="smtp.example.com", email_from="events@example.com")
    SmtpEmailSender(settings).send("asha@example.com", "Pass", "Body", attachments=[PNG])

    (message,) = sent
    (part,) = list(message.iter_attachments())
    assert (part.get_filename(), part.get_content_type()) == ("entry-pass.png", "image/png")
    assert part.get_content() == PNG.content
    assert message.get_body(("plain",)).get_content().strip() == "Body"


def test_mailtrap_sender_adds_attachments_base64_encoded(monkeypatch):
    mails = []

    class Client:
        def __init__(self, token, **kwargs):
            pass

        def send(self, mail):
            mails.append(mail)

    monkeypatch.setattr(mt, "MailtrapClient", Client)
    settings = Settings(email_provider="mailtrap", mailtrap_api_token="t", email_from="events@mastek.test")
    MailtrapEmailSender(settings).send("asha@example.com", "Pass", "Body", attachments=[PNG])

    (attachment,) = mails[0].attachments
    assert (attachment.filename, attachment.mimetype) == ("entry-pass.png", "image/png")
    assert base64.b64decode(attachment.content) == PNG.content
    assert mails[0].api_data["attachments"][0]["type"] == "image/png"


def test_mailtrap_sender_without_attachments_sends_none(monkeypatch):
    mails = []
    monkeypatch.setattr(
        mt, "MailtrapClient", lambda token, **kwargs: type("C", (), {"send": lambda self, m: mails.append(m)})()
    )
    settings = Settings(email_provider="mailtrap", mailtrap_api_token="t", email_from="events@mastek.test")
    MailtrapEmailSender(settings).send("asha@example.com", "Code", "Body")
    assert mails[0].attachments is None


def test_console_sender_lists_attachments_without_content(capsys):
    ConsoleEmailSender().send("asha@example.com", "Pass", "Body", attachments=[PNG])
    out = capsys.readouterr().out
    assert "[attachment] entry-pass.png (image/png, 12 bytes)" in out
