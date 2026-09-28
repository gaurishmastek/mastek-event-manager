from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.guests.models import SEAT_HOLDING_STATUSES, Registration, RegistrationStatus


class RegistrationRepository:
    """Data access for guest registrations. Soft-deleted rows are invisible to every read."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_public_id(self, public_id: str) -> Registration | None:
        stmt = select(Registration).where(Registration.public_id == public_id, Registration.deleted_at.is_(None))
        return self.db.scalars(stmt).first()

    def get_by_event_and_email(self, event_id: int, email_hash: str) -> Registration | None:
        stmt = select(Registration).where(
            Registration.event_id == event_id,
            Registration.email_hash == email_hash,
            Registration.deleted_at.is_(None),
        )
        return self.db.scalars(stmt).first()

    def get_by_token_hash(self, token_hash: str) -> Registration | None:
        stmt = select(Registration).where(Registration.qr_token_hash == token_hash)
        return self.db.scalars(stmt).first()

    def count_seats_taken(self, event_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Registration)
            .where(
                Registration.event_id == event_id,
                Registration.status.in_(SEAT_HOLDING_STATUSES),
                Registration.deleted_at.is_(None),
            )
        )
        return self.db.scalar(stmt) or 0

    def add(self, registration: Registration) -> Registration:
        self.db.add(registration)
        self.db.flush()
        return registration

    def check_in(self, *, token_hash: str, event_id: int, officer_id: int, at: datetime) -> bool:
        """Mark the pass used in one atomic statement. True only for the one request that wins.

        Two officers scanning the same pass at the same moment cannot both succeed: the second
        UPDATE no longer matches `status = VERIFIED` and changes no rows.
        """
        result = self.db.execute(
            update(Registration)
            .where(
                Registration.qr_token_hash == token_hash,
                Registration.event_id == event_id,
                Registration.status == RegistrationStatus.VERIFIED.value,
                Registration.deleted_at.is_(None),
            )
            .values(
                status=RegistrationStatus.CHECKED_IN.value,
                checked_in_at=at,
                updated_at=at,
                updated_by=officer_id,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1
