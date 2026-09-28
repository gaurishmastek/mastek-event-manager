"""One-time passwords sent by email, with the abuse limits from the security review.

- 6-digit codes from `secrets`, stored only as an HMAC, valid for `otp_ttl_seconds`.
- At most `otp_max_attempts` wrong guesses per code; a new code invalidates older ones.
- A resend cooldown per subject, caps per email address (hour and day) and per IP (hour), and a
  daily email budget for the whole app, so the public form cannot be used to flood inboxes or
  burn the sending quota.
- Codes are never returned, logged or written to the audit trail.
"""

import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import keyed_hash
from app.core.email import normalize_email
from app.db.mixins import utcnow
from app.modules.notifications.email import EmailDeliveryError, EmailSender
from app.modules.otp.models import OtpChallenge

logger = logging.getLogger(__name__)

GUEST_VERIFY = "GUEST_VERIFY"

_SUBJECTS = {
    GUEST_VERIFY: "Your event registration code",
    "ADMIN_2FA": "Your admin sign-in code",
    "OFFICER_LOGIN": "Your gate sign-in code",
}


class OtpError(Exception):
    pass


class OtpThrottledError(OtpError):
    """Too many OTPs for this subject, email address or IP. `retry_after` is in seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many OTP requests")
        self.retry_after = retry_after


class OtpUnavailableError(OtpError):
    """OTPs cannot be sent right now (daily email budget reached or the email provider failed)."""


class OtpInvalidError(OtpError):
    """Wrong, expired, used-up or missing code. Deliberately one error for all of these."""


@dataclass(frozen=True)
class OtpIssued:
    expires_at: datetime
    resend_available_at: datetime


def _generate_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def _code_hmac(purpose: str, subject_ref: str, code: str) -> str:
    return keyed_hash(f"{subject_ref}:{code}", purpose=f"otp:{purpose}")


def _otp_email(purpose: str, code: str) -> tuple[str, str]:
    minutes = max(1, settings.otp_ttl_seconds // 60)
    body = (
        f"Your {settings.app_name} verification code is {code}.\n\n"
        f"It expires in {minutes} minutes and can be used once. Do not share it with anyone; "
        "Mastek staff will never ask for it.\n\n"
        "If you did not request this code, you can ignore this email."
    )
    return _SUBJECTS.get(purpose, "Your verification code"), body


class OtpService:
    def __init__(self, db: Session, email: EmailSender) -> None:
        self.db = db
        self.email = email

    def issue(self, *, purpose: str, subject_ref: str, email: str, ip: str | None) -> OtpIssued:
        """Create a code and email it. Flushes but does not commit; the caller commits on success.

        Raises before writing anything when a limit is hit, so the caller can roll back.
        """
        now = utcnow()
        email = normalize_email(email)
        recipient_hash = keyed_hash(email, purpose="otp-email")
        ip_hash = keyed_hash(ip, purpose="ip") if ip else None
        self._enforce_limits(purpose, subject_ref, recipient_hash, ip_hash, now)

        self.db.execute(
            update(OtpChallenge)
            .where(
                OtpChallenge.purpose == purpose,
                OtpChallenge.subject_ref == subject_ref,
                OtpChallenge.consumed_at.is_(None),
                OtpChallenge.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        code = _generate_code()
        challenge = OtpChallenge(
            purpose=purpose,
            subject_ref=subject_ref,
            code_hmac=_code_hmac(purpose, subject_ref, code),
            recipient_hash=recipient_hash,
            ip_hash=ip_hash,
            attempts=0,
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
            created_at=now,
        )
        self.db.add(challenge)
        self.db.flush()

        subject, body = _otp_email(purpose, code)
        try:
            self.email.send(email, subject, body)
        except EmailDeliveryError as exc:
            logger.warning("OTP email delivery failed for challenge %s: %s", challenge.id, exc)
            raise OtpUnavailableError("Could not send the OTP") from exc

        return OtpIssued(
            expires_at=challenge.expires_at,
            resend_available_at=now + timedelta(seconds=settings.otp_resend_cooldown_seconds),
        )

    def verify(self, *, purpose: str, subject_ref: str, code: str) -> None:
        """Consume the current code if it matches.

        A wrong guess is committed immediately so the attempt counts even though the request
        fails. A correct code is only flushed: the caller commits it together with whatever the
        verification unlocks, so a failure there leaves the code unused.
        """
        now = utcnow()
        challenge = self.db.scalars(
            select(OtpChallenge)
            .where(
                OtpChallenge.purpose == purpose,
                OtpChallenge.subject_ref == subject_ref,
                OtpChallenge.consumed_at.is_(None),
                OtpChallenge.invalidated_at.is_(None),
            )
            .order_by(OtpChallenge.created_at.desc(), OtpChallenge.id.desc())
            .limit(1)
        ).first()
        if challenge is None or challenge.expires_at <= now:
            raise OtpInvalidError

        # Count the attempt atomically, so parallel guesses cannot exceed the limit.
        counted = self.db.execute(
            update(OtpChallenge)
            .where(OtpChallenge.id == challenge.id, OtpChallenge.attempts < settings.otp_max_attempts)
            .values(attempts=OtpChallenge.attempts + 1)
        ).rowcount
        if counted != 1:
            self.db.commit()
            raise OtpInvalidError

        if not hmac.compare_digest(challenge.code_hmac, _code_hmac(purpose, subject_ref, code)):
            self.db.commit()
            raise OtpInvalidError

        consumed = self.db.execute(
            update(OtpChallenge)
            .where(OtpChallenge.id == challenge.id, OtpChallenge.consumed_at.is_(None))
            .values(consumed_at=now)
        ).rowcount
        if consumed != 1:
            self.db.rollback()
            raise OtpInvalidError

    def _enforce_limits(
        self, purpose: str, subject_ref: str, recipient_hash: str, ip_hash: str | None, now: datetime
    ) -> None:
        last_sent = self.db.scalar(
            select(func.max(OtpChallenge.created_at)).where(
                OtpChallenge.purpose == purpose, OtpChallenge.subject_ref == subject_ref
            )
        )
        cooldown = timedelta(seconds=settings.otp_resend_cooldown_seconds)
        if last_sent is not None and now - last_sent < cooldown:
            raise OtpThrottledError(_seconds_until(last_sent + cooldown, now))

        hour_ago, day_ago = now - timedelta(hours=1), now - timedelta(days=1)
        same_address = OtpChallenge.recipient_hash == recipient_hash
        if self._count(same_address, since=hour_ago) >= settings.otp_max_per_email_per_hour:
            raise OtpThrottledError(3600)
        if self._count(same_address, since=day_ago) >= settings.otp_max_per_email_per_day:
            raise OtpThrottledError(86400)
        if ip_hash and self._count(OtpChallenge.ip_hash == ip_hash, since=hour_ago) >= settings.otp_max_per_ip_per_hour:
            raise OtpThrottledError(3600)
        if self._count(since=day_ago) >= settings.email_daily_budget:
            logger.error("Daily email budget of %s reached; OTP sending is paused", settings.email_daily_budget)
            raise OtpUnavailableError("Daily email budget reached")

    def _count(self, *conditions, since: datetime) -> int:
        stmt = select(func.count()).select_from(OtpChallenge).where(OtpChallenge.created_at > since, *conditions)
        return self.db.scalar(stmt) or 0


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, int((moment - now).total_seconds() + 0.999))
