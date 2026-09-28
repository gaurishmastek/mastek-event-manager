import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, and_
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import AuditMixin


class RegistrationStatus(str, enum.Enum):
    PENDING_OTP = "PENDING_OTP"  # form submitted, email not yet verified; holds no seat
    VERIFIED = "VERIFIED"  # email verified, seats for the whole party taken, QR pass issued
    CHECKED_IN = "CHECKED_IN"  # pass scanned at the gate; cannot be used again


SEAT_HOLDING_STATUSES = (RegistrationStatus.VERIFIED.value, RegistrationStatus.CHECKED_IN.value)


class RegistrationGuest(AuditMixin, Base):
    """One accompanying guest of an employee's registration, in the order the employee listed them.

    Rows are never hard-deleted: when a pending registration drops a guest, that row is soft-deleted,
    and it is revived if the employee adds a guest at that position again.
    """

    __tablename__ = "registration_guests"
    __table_args__ = (UniqueConstraint("registration_id", "position", name="uq_registration_guests_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Registration(AuditMixin, Base):
    """An employee's registration for one event, covering the employee and their accompanying guests.

    One QR pass admits the whole party once. The party takes `1 + number_of_guests` seats, and only
    after the email is verified.

    The email and mobile are each kept three ways: an HMAC for lookups and uniqueness, an encrypted
    copy (the email is decrypted only to send OTPs; OTPs never go to the mobile), and a masked copy
    for display. The QR pass token is stored only as a SHA-256 hash.

    Registrations made before the registration-link workflow have no employee id and no guests;
    those made before OTPs moved to email have only the `mobile_*` columns.
    """

    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "email_hash", name="uq_registrations_event_email"),
        UniqueConstraint("event_id", "employee_id_normalized", name="uq_registrations_event_employee"),
        Index("ix_registrations_event_status", "event_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    # Nullable only because of registrations from before the registration-link workflow.
    employee_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    employee_id_normalized: Mapped[str | None] = mapped_column(String(30), nullable=True)
    employee_name: Mapped[str] = mapped_column(String(100), nullable=False)
    number_of_guests: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
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

    # Active guests only, in order. Written through RegistrationRepository.set_guests.
    guests: Mapped[list[RegistrationGuest]] = relationship(
        RegistrationGuest,
        primaryjoin=lambda: and_(
            RegistrationGuest.registration_id == Registration.id, RegistrationGuest.deleted_at.is_(None)
        ),
        order_by=RegistrationGuest.position,
        viewonly=True,
        lazy="selectin",
    )

    @property
    def party_size(self) -> int:
        return 1 + self.number_of_guests

    @property
    def guest_names(self) -> list[str]:
        return [guest.name for guest in self.guests]
