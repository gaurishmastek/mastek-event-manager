import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, utcnow


class ScanResult(str, enum.Enum):
    ADMITTED = "admitted"
    ALREADY_CHECKED_IN = "already_checked_in"
    WRONG_EVENT = "wrong_event"
    INVALID = "invalid"
    GATE_CLOSED = "gate_closed"


class CheckIn(AuditMixin, Base):
    """One guest entry. The unique registration_id is the database's final guarantee of single use."""

    __tablename__ = "check_ins"
    __table_args__ = (Index("ix_check_ins_event_checked_in_at", "event_id", "checked_in_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"), nullable=False, unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    officer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="QR")
    checked_in_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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
