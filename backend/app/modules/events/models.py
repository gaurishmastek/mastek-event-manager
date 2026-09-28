from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin


class Event(AuditMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_events_capacity_positive"),
        CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="ck_events_ends_after_starts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)


class OfficerEvent(AuditMixin, Base):
    """Assigns a security officer to an event. Officers only see events they are assigned to."""

    __tablename__ = "officer_events"
    __table_args__ = (UniqueConstraint("officer_id", "event_id", name="uq_officer_events_officer_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # References users.id; the foreign key is added once the users table exists.
    officer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
