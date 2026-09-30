"""Emails a verified employee their QR entry pass, so they still have it after leaving the pass page."""

import logging
from datetime import UTC, datetime, timedelta, timezone

from app.core.email import mask_email
from app.modules.events.models import Event
from app.modules.guests.models import Registration
from app.modules.guests.qr import qr_png
from app.modules.notifications.email import EmailAttachment, EmailSender

logger = logging.getLogger(__name__)

# Events are in Mumbai; stored times are naive UTC.
IST = timezone(timedelta(hours=5, minutes=30), "IST")
ENTRY_PASS_EMAIL_SUBJECT = "Your entry pass for {title}"  # noqa: S105 - not a secret


def _ist(value: datetime) -> str:
    return value.replace(tzinfo=UTC).astimezone(IST).strftime("%a %d %b %Y, %I:%M %p IST")


def pass_email_body(registration: Registration, event: Event) -> str:
    people = [f"{registration.employee_name} ({registration.employee_id})"]
    if registration.adult_name or registration.kid_names:
        if registration.adult_name:
            people.append(f"{registration.adult_name} (adult)")
        for name, age in zip(registration.kid_names, registration.kid_ages, strict=False):
            people.append(f"{name} (kid, age {age})" if age is not None else f"{name} (kid)")
    else:
        people.extend(registration.guest_names)
    size = registration.party_size
    lines = [
        f"Hello {registration.employee_name},",
        "",
        f"You're registered for {event.title}.",
        f"Where: {event.location}",
        f"When: {_ist(event.starts_at)}",
        "",
        f"Your QR entry pass is attached. It admits {size} {'person' if size == 1 else 'people'} once:",
        *(f"  - {person}" for person in people),
        "",
        "Arrive together and show the QR code at the gate. It can be scanned only once, for your whole party.",
        "Keep this email private: anyone with the QR code can use it. If you verify again, this pass stops working",
        "and a new one is emailed to you.",
    ]
    return "\n".join(lines)


def send_pass_email(sender: EmailSender, to: str, registration: Registration, event: Event, token: str) -> bool:
    """Send the pass to the registration's verified email. Returns False instead of raising when delivery fails:
    the pass is already issued and shown on screen, so a mail problem must not fail the verification."""
    try:
        sender.send(
            to,
            ENTRY_PASS_EMAIL_SUBJECT.format(title=event.title),
            pass_email_body(registration, event),
            attachments=[EmailAttachment(filename="entry-pass.png", content=qr_png(token), mime_type="image/png")],
        )
    except Exception:
        logger.warning(
            "Pass email delivery failed for registration %s to %s",
            registration.public_id,
            mask_email(to),
            exc_info=True,
        )
        return False
    return True
