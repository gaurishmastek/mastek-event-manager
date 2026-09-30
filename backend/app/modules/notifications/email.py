"""Email delivery for OTPs and other notifications.

`EMAIL_PROVIDER` picks the adapter: `smtp` sends through the configured SMTP server, `mailtrap` sends through the
Mailtrap Email API (https://mailtrap.io), `console` prints messages to stdout for local development (refused in
production), and `disabled` refuses to send.

SMTP and Mailtrap failures are classified (`EmailDeliveryError.kind`) and logged with the stage, the numeric SMTP
code (or HTTP status) and a redacted provider reply, so an operator can tell a DNS problem from a rejected login or a
refused sender without the log ever holding a credential, the message body or a full address.
"""

import base64
import logging
import re
import smtplib
import socket
import ssl
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.email import mask_email

logger = logging.getLogger(__name__)

# Failure kinds, from where the conversation with the server broke down.
NOT_CONFIGURED = "not_configured"
DNS = "dns"
CONNECT = "connect"
TIMEOUT = "timeout"
TLS = "tls"
AUTH = "auth"
SENDER_REJECTED = "sender_rejected"
RECIPIENT_REJECTED = "recipient_rejected"
DATA_REJECTED = "data_rejected"
RATE_LIMITED = "rate_limited"
UNKNOWN = "unknown"

_ADDRESS = re.compile(r"[^\s<>@\"']+@[^\s<>@\"']+")
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f]+")


class EmailDeliveryError(Exception):
    """Delivery failed. `kind` is one of the module's failure kinds; `smtp_code` is the server's numeric reply."""

    def __init__(self, message: str, *, kind: str = UNKNOWN, stage: str | None = None, smtp_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.stage = stage
        self.smtp_code = smtp_code


@dataclass(frozen=True)
class EmailAttachment:
    """A file sent with a message, e.g. the QR entry pass as a PNG image."""

    filename: str
    content: bytes
    mime_type: str  # "maintype/subtype", e.g. "image/png"


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str, attachments: Sequence[EmailAttachment] = ()) -> None: ...


class DisabledEmailSender:
    def send(self, to: str, subject: str, body: str, attachments: Sequence[EmailAttachment] = ()) -> None:
        logger.warning("Email not sent: EMAIL_PROVIDER is disabled (check backend/.env or the environment)")
        raise EmailDeliveryError("Email delivery is not configured", kind=NOT_CONFIGURED)


class ConsoleEmailSender:
    """Development only: prints the message instead of sending it. Refused in production by config."""

    def send(self, to: str, subject: str, body: str, attachments: Sequence[EmailAttachment] = ()) -> None:
        files = "".join(f"\n[attachment] {a.filename} ({a.mime_type}, {len(a.content)} bytes)" for a in attachments)
        print(f"[dev email] To: {mask_email(to)} | {subject}\n{body}{files}", file=sys.stdout, flush=True)


def redact_smtp_reply(reply: bytes | str | None, limit: int = 160) -> str:
    """A provider reply that is safe to log: addresses replaced, one line, bounded length."""
    if reply is None:
        return ""
    text = reply.decode("utf-8", "replace") if isinstance(reply, bytes) else str(reply)
    text = _ADDRESS.sub("<address>", text)
    text = _UNPRINTABLE.sub(" ", text).strip()
    return text[:limit]


def _smtp_reply(exc: BaseException) -> tuple[int | None, bytes | str | None]:
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        # {address: (code, reply)}; the addresses themselves are never used.
        for code, reply in exc.recipients.values():
            return code, reply
        return None, None
    if isinstance(exc, smtplib.SMTPResponseException):
        return exc.smtp_code, exc.smtp_error
    return None, None


def classify_smtp_failure(exc: BaseException, stage: str) -> str:
    """Map an exception raised while talking to the server at `stage` to a failure kind."""
    # Order matters: timeouts, DNS failures and TLS errors are all OSErrors.
    if isinstance(exc, TimeoutError):
        return TIMEOUT
    if isinstance(exc, socket.gaierror):
        return DNS
    if isinstance(exc, ssl.SSLError) or stage == "starttls":
        return TLS
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return SENDER_REJECTED
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return RECIPIENT_REJECTED
    if isinstance(exc, smtplib.SMTPDataError):
        return DATA_REJECTED
    if stage == "login":
        # Rejected credentials, or no authentication mechanism both sides support.
        return AUTH
    if isinstance(exc, smtplib.SMTPConnectError) or (stage == "connect" and isinstance(exc, OSError)):
        return CONNECT
    if isinstance(exc, smtplib.SMTPServerDisconnected | ConnectionError):
        return CONNECT
    return UNKNOWN


class SmtpEmailSender:
    """Sends plain-text mail through an SMTP server, over STARTTLS or implicit TLS unless told otherwise.

    The certificate is always verified (`ssl.create_default_context()`); a TLS failure is reported, never retried
    in the clear.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, to: str, subject: str, body: str, attachments: Sequence[EmailAttachment] = ()) -> None:
        s = self.settings
        message = EmailMessage()
        message["From"] = s.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        for attachment in attachments:
            maintype, subtype = attachment.mime_type.split("/", 1)
            message.add_attachment(attachment.content, maintype=maintype, subtype=subtype, filename=attachment.filename)
        context = ssl.create_default_context()
        stage = "connect"
        try:
            if s.smtp_security == "ssl":
                server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context)
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds)
            with server:
                if s.smtp_security == "starttls":
                    stage = "starttls"
                    server.starttls(context=context)
                if s.smtp_username:
                    stage = "login"
                    server.login(s.smtp_username, s.smtp_password)
                stage = "send"
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            kind = classify_smtp_failure(exc, stage)
            code, reply = _smtp_reply(exc)
            logger.warning(
                "SMTP delivery failed: kind=%s stage=%s code=%s error=%s host=%s port=%s security=%s "
                "sender=%s recipient=%s reply=%r",
                kind,
                stage,
                code,
                exc.__class__.__name__,
                s.smtp_host,
                s.smtp_port,
                s.smtp_security,
                mask_email(parseaddr(s.email_from)[1]),
                mask_email(to),
                redact_smtp_reply(reply),
            )
            raise EmailDeliveryError(
                f"SMTP delivery failed: {kind} at {stage} ({exc.__class__.__name__}, code {code})",
                kind=kind,
                stage=stage,
                smtp_code=code,
            ) from exc


def classify_mailtrap_failure(exc: BaseException) -> str:
    """Map an exception raised by the Mailtrap SDK (or the HTTP library under it) to a failure kind."""
    import mailtrap as mt
    import requests

    # Order matters: SSLError and ConnectTimeout are both ConnectionErrors.
    if isinstance(exc, requests.exceptions.SSLError):
        return TLS
    if isinstance(exc, requests.exceptions.Timeout):
        return TIMEOUT
    if isinstance(exc, requests.exceptions.ConnectionError):
        return CONNECT
    if isinstance(exc, mt.APIError):
        if exc.status == 401:
            return AUTH  # Token missing, revoked or mistyped.
        if exc.status == 403:
            return SENDER_REJECTED  # Token lacks access to the sending domain, or EMAIL_FROM is not on it.
        if exc.status == 429:
            return RATE_LIMITED
        if 400 <= exc.status < 500:
            return DATA_REJECTED
    return UNKNOWN


class MailtrapEmailSender:
    """Sends plain-text mail through the Mailtrap Email API (HTTPS, certificate verified by `requests`).

    `EMAIL_FROM` ("Name <address>" or a bare address) must be on a sending domain verified in Mailtrap, and
    `MAILTRAP_API_TOKEN` must have access to that domain. Delivery status for each message is in Mailtrap's email logs.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, to: str, subject: str, body: str, attachments: Sequence[EmailAttachment] = ()) -> None:
        # Imported here so the SDK only loads when this provider is chosen.
        import mailtrap as mt

        s = self.settings
        sender_name, sender_email = parseaddr(s.email_from)
        mail = mt.Mail(
            sender=mt.Address(email=sender_email, name=sender_name or None),
            to=[mt.Address(email=to)],
            subject=subject,
            text=body,
            category=s.mailtrap_category or None,
            attachments=[
                mt.Attachment(
                    content=base64.b64encode(a.content),
                    filename=a.filename,
                    mimetype=a.mime_type,
                    disposition=mt.Disposition.ATTACHMENT,
                )
                for a in attachments
            ]
            or None,
        )
        try:
            mt.MailtrapClient(token=s.mailtrap_api_token).send(mail)
        except Exception as exc:  # the SDK raises MailtrapError, requests errors and pydantic validation errors
            kind = classify_mailtrap_failure(exc)
            status = getattr(exc, "status", None)
            errors = "; ".join(getattr(exc, "errors", None) or [])
            logger.warning(
                "Mailtrap delivery failed: kind=%s status=%s error=%s sender=%s recipient=%s reply=%r",
                kind,
                status,
                exc.__class__.__name__,
                mask_email(sender_email),
                mask_email(to),
                redact_smtp_reply(errors),
            )
            raise EmailDeliveryError(
                f"Mailtrap delivery failed: {kind} ({exc.__class__.__name__}, status {status})", kind=kind, stage="send"
            ) from exc


def email_config_summary(settings: Settings) -> dict[str, object]:
    """The effective email configuration with nothing secret in it: no password, and addresses masked."""
    from app.core.config import ENV_FILE

    sender = parseaddr(settings.email_from)[1]
    username = settings.smtp_username
    return {
        "environment": settings.environment,
        "env_file": str(ENV_FILE) if ENV_FILE else "(none)",
        "env_file_found": bool(ENV_FILE and ENV_FILE.is_file()),
        "email_provider": settings.email_provider,
        "smtp_host": settings.smtp_host or "(empty)",
        "smtp_port": settings.smtp_port,
        "smtp_security": settings.smtp_security,
        "smtp_timeout_seconds": settings.smtp_timeout_seconds,
        "email_from": mask_email(sender) if "@" in sender else "(empty or invalid)",
        "smtp_username": (mask_email(username) if "@" in username else "(set)") if username else "(empty)",
        "smtp_password_configured": bool(settings.smtp_password),
        "mailtrap_api_token_configured": bool(settings.mailtrap_api_token.strip()),
        "mailtrap_category": settings.mailtrap_category or "(empty)",
    }


def get_email_sender() -> EmailSender:
    settings = get_settings()
    if settings.email_provider == "smtp":
        return SmtpEmailSender(settings)
    if settings.email_provider == "mailtrap":
        return MailtrapEmailSender(settings)
    if settings.email_provider == "console" and not settings.is_production:
        return ConsoleEmailSender()
    return DisabledEmailSender()
