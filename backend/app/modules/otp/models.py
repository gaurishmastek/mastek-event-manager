from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import utcnow


class OtpChallenge(Base):
    """One OTP sent by email. The code itself is never stored, only its HMAC.

    Rows are also the send log that per-address, per-IP and daily email caps are counted from,
    so they are never deleted.
    """

    __tablename__ = "otp_challenges"
    __table_args__ = (
        Index("ix_otp_challenges_subject", "purpose", "subject_ref", "created_at"),
        Index("ix_otp_challenges_recipient", "recipient_hash", "created_at"),
        Index("ix_otp_challenges_ip", "ip_hash", "created_at"),
        Index("ix_otp_challenges_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    # HMAC of the address the code went to. Rows from before the switch to email hold a mobile's HMAC.
    recipient_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
