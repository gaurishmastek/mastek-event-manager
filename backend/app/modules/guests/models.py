import enum
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, and_
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import AuditMixin


class RegistrationStatus(str, enum.Enum):
    PENDING_OTP = "PENDING_OTP"  # form submitted, email not yet verified; holds no seat
    VERIFIED = "VERIFIED"  # email verified, seats for the whole party taken, QR pass issued
    CHECKED_IN = "CHECKED_IN"  # pass scanned at the gate; cannot be used again
    DECLINED = "DECLINED"  # email verified, employee said they will not attend; holds no seat and has no pass


SEAT_HOLDING_STATUSES = (RegistrationStatus.VERIFIED.value, RegistrationStatus.CHECKED_IN.value)


class FoodPreference(str, enum.Enum):
    VEG = "VEG"
    JAIN = "JAIN"
    FAST_FOOD = "FAST_FOOD"


class GuestType(str, enum.Enum):
    """Who an accompanying guest is. Guests registered before the family questions have no type."""

    ADULT = "ADULT"
    KID = "KID"


# Accompanying kids are under 18; each kid's age is given in whole years.
MIN_KID_AGE = 0
MAX_KID_AGE = 17


def _in_check(column: str, enum_cls: type[enum.Enum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IS NULL OR {column} IN ({values})"


class RegistrationGuest(AuditMixin, Base):
    """One accompanying guest of an employee's registration, in the order the employee listed them.

    Rows are never hard-deleted: when a pending registration drops a guest, that row is soft-deleted,
    and it is revived if the employee adds a guest at that position again.
    """

    __tablename__ = "registration_guests"
    __table_args__ = (
        UniqueConstraint("registration_id", "position", name="uq_registration_guests_position"),
        CheckConstraint(_in_check("guest_type", GuestType), name="ck_registration_guests_guest_type"),
        CheckConstraint(
            f"age IS NULL OR (age >= {MIN_KID_AGE} AND age <= {MAX_KID_AGE})", name="ck_registration_guests_age"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # ADULT or KID; null only for guests registered before the family questions.
    guest_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Age in years, set for every kid; null for the adult and for kids registered before ages were asked.
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Registration(AuditMixin, Base):
    """An employee's registration for one event, covering the employee and their accompanying guests.

    One QR pass admits the whole party once. The party takes `1 + number_of_guests` seats, and only
    after the email is verified.

    The email and mobile are each kept three ways: an HMAC for lookups and uniqueness, an encrypted
    copy (the email is decrypted only to send OTPs; OTPs never go to the mobile), and a masked copy
    for display. The QR pass token is stored only as a SHA-256 hash.

    An employee who answers that they will not attend still verifies their email; the registration then
    becomes DECLINED, with no party, no seat and no pass.

    Registrations made before the registration-link workflow have no employee id and no guests;
    those made before OTPs moved to email have only the `mobile_*` columns.
    """

    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "email_hash", name="uq_registrations_event_email"),
        UniqueConstraint("event_id", "employee_id_normalized", name="uq_registrations_event_employee"),
        Index("ix_registrations_event_status", "event_id", "status"),
        CheckConstraint(_in_check("food_preference", FoodPreference), name="ck_registrations_food_preference"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    # Nullable only because of registrations from before the registration-link workflow.
    employee_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    employee_id_normalized: Mapped[str | None] = mapped_column(String(30), nullable=True)
    employee_name: Mapped[str] = mapped_column(String(100), nullable=False)
    number_of_guests: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # The answers to "Will you be attending?" and "Will you be accompanied by your family?". Registrations from
    # before these questions count as attending, with no family answer. `family_attending` and `food_preference`
    # are null when the employee is not attending.
    attending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    family_attending: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    food_preference: Mapped[str | None] = mapped_column(String(20), nullable=True)
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

    @property
    def adult_name(self) -> str | None:
        return next((guest.name for guest in self.guests if guest.guest_type == GuestType.ADULT.value), None)

    @property
    def kid_names(self) -> list[str]:
        return [guest.name for guest in self.guests if guest.guest_type == GuestType.KID.value]

    @property
    def kid_ages(self) -> list[int | None]:
        """Ages in the same order as `kid_names`; None for kids registered before ages were asked."""
        return [guest.age for guest in self.guests if guest.guest_type == GuestType.KID.value]
