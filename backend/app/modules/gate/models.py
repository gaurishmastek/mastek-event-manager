import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, utcnow


class ScanResult(str, enum.Enum):
    """Outcome of a scan or of the officer's approve/reject decision that follows it."""

    PENDING_VERIFICATION = "pending_verification"  # first visit: the officer must check the employee's ID
    PENDING_GUESTS = "pending_guests"  # employee already in; some registered guests are still to arrive
    ADMITTED = "admitted"  # the officer approved entry
    REJECTED = "rejected"  # the officer refused entry; the pass is unchanged
    ALREADY_CHECKED_IN = "already_checked_in"  # everyone on the pass has entered
    GUESTS_ALREADY_ENTERED = "guests_already_entered"  # an approval named a guest who is already in
    WRONG_EVENT = "wrong_event"
    INVALID = "invalid"
    GATE_CLOSED = "gate_closed"


class RejectionReason(str, enum.Enum):
    ID_MISMATCH = "ID_MISMATCH"  # the ID shown does not match the registered employee id
    ID_NOT_PRESENTED = "ID_NOT_PRESENTED"  # no employee ID was shown
    OTHER = "OTHER"  # explained in the note


class CheckIn(AuditMixin, Base):
    """The employee's entry, after the officer checked their ID. Accompanying guests enter through `GuestEntry`.

    The unique registration_id is the database's final guarantee that the employee enters only once."""

    __tablename__ = "check_ins"
    __table_args__ = (Index("ix_check_ins_event_checked_in_at", "event_id", "checked_in_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"), nullable=False, unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    officer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="QR")
    checked_in_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class GuestEntry(AuditMixin, Base):
    """One accompanying guest letting in, on the shared pass, after (or with) the employee.

    The unique registration_guest_id is the database's guarantee that each guest enters only once."""

    __tablename__ = "guest_entries"
    __table_args__ = (Index("ix_guest_entries_check_in_id", "check_in_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    check_in_id: Mapped[int] = mapped_column(ForeignKey("check_ins.id"), nullable=False)
    registration_guest_id: Mapped[int] = mapped_column(
        ForeignKey("registration_guests.id"), nullable=False, unique=True
    )
    officer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EntryRejection(AuditMixin, Base):
    """An officer refused entry to whoever presented a pass. The registration itself is left unchanged."""

    __tablename__ = "entry_rejections"
    __table_args__ = (
        Index("ix_entry_rejections_event_created_at", "event_id", "created_at"),
        CheckConstraint("reason IN ('ID_MISMATCH', 'ID_NOT_PRESENTED', 'OTHER')", name="ck_entry_rejections_reason"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"), nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    officer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ScanAttempt(Base):
    """Append-only log of every scan and its outcome. The scanned token is never stored."""

    __tablename__ = "scan_attempts"
    __table_args__ = (Index("ix_scan_attempts_event_created_at", "event_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    officer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    registration_id: Mapped[int | None] = mapped_column(ForeignKey("registrations.id"), nullable=True)
    gate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    result: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
