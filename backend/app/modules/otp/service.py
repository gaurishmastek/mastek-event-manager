"""One-time passwords sent by SMS, with the abuse limits from the security review.

- 6-digit codes from `secrets`, stored only as an HMAC, valid for `otp_ttl_seconds`.
- At most `otp_max_attempts` wrong guesses per code; a new code invalidates older ones.
- A resend cooldown per subject, caps per mobile (hour and day) and per IP (hour), and a
  daily SMS budget for the whole app, so the public form cannot be used for SMS pumping.
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
from app.db.mixins import utcnow
from app.modules.otp.models import OtpChallenge
from app.modules.otp.sms import SmsDeliveryError, SmsSender

logger = logging.getLogger(__name__)

GUEST_VERIFY = "GUEST_VERIFY"


class OtpError(Exception):
    pass


class OtpThrottledError(OtpError):
    """Too many OTPs for this subject, mobile or IP. `retry_after` is in seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many OTP requests")
        self.retry_after = retry_after


class OtpUnavailableError(OtpError):
    """OTPs cannot be sent right now (daily SMS budget reached or the SMS provider failed)."""


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


class OtpService:
    def __init__(self, db: Session, sms: SmsSender) -> None:
        self.db = db
        self.sms = sms

    def issue(self, *, purpose: str, subject_ref: str, mobile: str, ip: str | None) -> OtpIssued:
        """Create a code and send it. Flushes but does not commit; the caller commits on success.

        Raises before writing anything when a limit is hit, so the caller can roll back.
        """
        now = utcnow()
        mobile_hash = keyed_hash(mobile, purpose="mobile")
        ip_hash = keyed_hash(ip, purpose="ip") if ip else None
        self._enforce_limits(purpose, subject_ref, mobile_hash, ip_hash, now)

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
            mobile_hash=mobile_hash,
            ip_hash=ip_hash,
            attempts=0,
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
            created_at=now,
        )
        self.db.add(challenge)
        self.db.flush()

        try:
            self.sms.send_otp(mobile, code)
        except SmsDeliveryError as exc:
            logger.warning("OTP SMS delivery failed for challenge %s: %s", challenge.id, exc)
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
        self, purpose: str, subject_ref: str, mobile_hash: str, ip_hash: str | None, now: datetime
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
        if self._count(OtpChallenge.mobile_hash == mobile_hash, since=hour_ago) >= settings.otp_max_per_mobile_per_hour:
            raise OtpThrottledError(3600)
        if self._count(OtpChallenge.mobile_hash == mobile_hash, since=day_ago) >= settings.otp_max_per_mobile_per_day:
            raise OtpThrottledError(86400)
        if ip_hash and self._count(OtpChallenge.ip_hash == ip_hash, since=hour_ago) >= settings.otp_max_per_ip_per_hour:
            raise OtpThrottledError(3600)
        if self._count(since=day_ago) >= settings.sms_daily_budget:
            logger.error("Daily SMS budget of %s reached; OTP sending is paused", settings.sms_daily_budget)
            raise OtpUnavailableError("Daily SMS budget reached")

    def _count(self, *conditions, since: datetime) -> int:
        stmt = select(func.count()).select_from(OtpChallenge).where(OtpChallenge.created_at > since, *conditions)
        return self.db.scalar(stmt) or 0


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, int((moment - now).total_seconds() + 0.999))
