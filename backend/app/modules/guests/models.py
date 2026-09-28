import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin


class RegistrationStatus(str, enum.Enum):
    PENDING_OTP = "PENDING_OTP"  # form submitted, mobile not yet verified; holds no seat
    VERIFIED = "VERIFIED"  # mobile verified, seat taken, QR pass issued
    CHECKED_IN = "CHECKED_IN"  # pass scanned at the gate; cannot be used again


SEAT_HOLDING_STATUSES = (RegistrationStatus.VERIFIED.value, RegistrationStatus.CHECKED_IN.value)


class Registration(AuditMixin, Base):
    """A guest's registration for one event.

    The mobile number is kept three ways: an HMAC for lookups and uniqueness, an encrypted
    copy for sending OTPs, and a masked copy for display. The QR pass token is stored only
    as a SHA-256 hash.
    """

    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "mobile_hash", name="uq_registrations_event_mobile"),
        Index("ix_registrations_event_status", "event_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    guest_name: Mapped[str] = mapped_column(String(100), nullable=False)
    mobile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_encrypted: Mapped[str] = mapped_column(String(255), nullable=False)
    mobile_masked: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RegistrationStatus.PENDING_OTP.value)
    consent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    qr_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    qr_issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
