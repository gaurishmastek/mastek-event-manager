import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin

# Accompanying guests one employee may bring. The employee is not counted.
DEFAULT_MAX_GUESTS_PER_REGISTRATION = 5
MAX_GUESTS_PER_REGISTRATION_CAP = 10


class Event(AuditMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_events_capacity_positive"),
        CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="ck_events_ends_after_starts"),
        CheckConstraint(
            f"max_guests_per_registration >= 0 AND max_guests_per_registration <= {MAX_GUESTS_PER_REGISTRATION_CAP}",
            name="ck_events_max_guests_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Random UUID used in public registration links, so the internal id is never exposed or guessable.
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    max_guests_per_registration: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MAX_GUESTS_PER_REGISTRATION, server_default="5"
    )
    # An admin can close registration early; the public link then behaves as past the registration cutoff.
    registration_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class OfficerEvent(AuditMixin, Base):
    """Assigns a security officer to an event. Officers only see events they are assigned to."""

    __tablename__ = "officer_events"
    __table_args__ = (UniqueConstraint("officer_id", "event_id", name="uq_officer_events_officer_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    officer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
