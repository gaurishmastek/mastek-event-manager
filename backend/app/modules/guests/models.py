import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin


class RegistrationStatus(str, enum.Enum):
    PENDING_OTP = "PENDING_OTP"  # form submitted, email not yet verified; holds no seat
    VERIFIED = "VERIFIED"  # email verified, seat taken, QR pass issued
    CHECKED_IN = "CHECKED_IN"  # pass scanned at the gate; cannot be used again


SEAT_HOLDING_STATUSES = (RegistrationStatus.VERIFIED.value, RegistrationStatus.CHECKED_IN.value)


class Registration(AuditMixin, Base):
    """A guest's registration for one event.

    The email address is kept three ways: an HMAC for lookups and uniqueness, an encrypted
    copy for sending OTPs, and a masked copy for display. The QR pass token is stored only
    as a SHA-256 hash.

    Guests registered before OTPs moved to email have only the `mobile_*` columns. They are
    kept so those passes still show a contact at the gate, and are never written any more.
    """

    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "email_hash", name="uq_registrations_event_email"),
        Index("ix_registrations_event_status", "event_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    guest_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Nullable only because of registrations from before the switch to email; every new row has them.
    email_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email_masked: Mapped[str | None] = mapped_column(String(260), nullable=True)
    mobile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mobile_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mobile_masked: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RegistrationStatus.PENDING_OTP.value)
    consent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    qr_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    qr_issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
