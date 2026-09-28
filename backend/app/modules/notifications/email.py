"""Email delivery for OTPs and other notifications.

`EMAIL_PROVIDER` picks the adapter: `smtp` sends through the configured SMTP server, `console` prints
messages to stdout for local development (refused in production), and `disabled` refuses to send.
"""

import smtplib
import ssl
import sys
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.email import mask_email


class EmailDeliveryError(Exception):
    pass


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class DisabledEmailSender:
    def send(self, to: str, subject: str, body: str) -> None:
        raise EmailDeliveryError("Email delivery is not configured")


class ConsoleEmailSender:
    """Development only: prints the message instead of sending it. Refused in production by config."""

    def send(self, to: str, subject: str, body: str) -> None:
        print(f"[dev email] To: {mask_email(to)} | {subject}\n{body}", file=sys.stdout, flush=True)


class SmtpEmailSender:
    """Sends plain-text mail through an SMTP server, over STARTTLS or implicit TLS unless told otherwise."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, to: str, subject: str, body: str) -> None:
        s = self.settings
        message = EmailMessage()
        message["From"] = s.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        try:
            if s.smtp_security == "ssl":
                server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context)
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
            with server:
                if s.smtp_security == "starttls":
                    server.starttls(context=context)
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(f"SMTP delivery failed: {exc.__class__.__name__}") from exc


def get_email_sender() -> EmailSender:
    settings = get_settings()
    if settings.email_provider == "smtp":
        return SmtpEmailSender(settings)
    if settings.email_provider == "console" and not settings.is_production:
        return ConsoleEmailSender()
    return DisabledEmailSender()
