# Postponed annotations: the `list` method would otherwise shadow the builtin in later signatures.
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.db.mixins import utcnow
from app.modules.guests.models import (
    SEAT_HOLDING_STATUSES,
    GuestType,
    Registration,
    RegistrationGuest,
    RegistrationStatus,
)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RegistrationRepository:
    """Data access for employee registrations. Soft-deleted rows are invisible to every read."""

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

    def get_by_event_and_employee(self, event_id: int, employee_id_normalized: str) -> Registration | None:
        stmt = select(Registration).where(
            Registration.event_id == event_id,
            Registration.employee_id_normalized == employee_id_normalized,
            Registration.deleted_at.is_(None),
        )
        return self.db.scalars(stmt).first()

    def get_by_token_hash(self, token_hash: str) -> Registration | None:
        stmt = select(Registration).where(Registration.qr_token_hash == token_hash)
        return self.db.scalars(stmt).first()

    def count_seats_taken(self, event_id: int, *, locking: bool = False) -> int:
        """People, not rows: each verified registration takes the employee plus their guests.

        Pass `locking=True` when deciding whether to take seats, while holding the event lock. It makes
        this a locking read, which MySQL answers from the latest committed rows; a plain read inside a
        REPEATABLE READ transaction could return an older snapshot and oversell the event.
        """
        stmt = select(func.coalesce(func.sum(1 + Registration.number_of_guests), 0)).where(
            Registration.event_id == event_id,
            Registration.status.in_(SEAT_HOLDING_STATUSES),
            Registration.deleted_at.is_(None),
        )
        if locking:
            stmt = stmt.with_for_update(read=True)
        return int(self.db.scalar(stmt) or 0)

    def list(
        self,
        event_id: int,
        *,
        limit: int,
        offset: int,
        search: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Registration], int]:
        conditions = [Registration.event_id == event_id, Registration.deleted_at.is_(None)]
        if search:
            pattern = f"%{_escape_like(search)}%"
            conditions.append(
                or_(
                    Registration.employee_id.ilike(pattern, escape="\\"),
                    Registration.employee_name.ilike(pattern, escape="\\"),
                )
            )
        if status:
            conditions.append(Registration.status == status)

        total = self.db.scalar(select(func.count()).select_from(Registration).where(*conditions)) or 0
        stmt = (
            select(Registration)
            .where(*conditions)
            .order_by(Registration.created_at.desc(), Registration.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt)), total

    def add(self, registration: Registration) -> Registration:
        self.db.add(registration)
        self.db.flush()
        return registration

    def set_guests(self, registration: Registration, guests: Sequence[tuple[str, GuestType]]) -> None:
        """Make the registration's active guests exactly `guests` (name and type), in order, without
        hard-deleting rows.

        A name at a position that still exists is updated in place, extra positions are soft-deleted,
        and a soft-deleted row is revived if its position is needed again.
        """
        now = utcnow()
        existing = {
            row.position: row
            for row in self.db.scalars(
                select(RegistrationGuest).where(RegistrationGuest.registration_id == registration.id)
            )
        }
        for position, (name, guest_type) in enumerate(guests):
            row = existing.get(position)
            if row is None:
                self.db.add(
                    RegistrationGuest(
                        registration_id=registration.id, name=name, position=position, guest_type=guest_type.value
                    )
                )
            else:
                row.name = name
                row.guest_type = guest_type.value
                row.deleted_at = None
                row.deleted_by = None
                row.updated_at = now
        for position, row in existing.items():
            if position >= len(guests) and row.deleted_at is None:
                row.deleted_at = now
                row.updated_at = now
        registration.number_of_guests = len(guests)
        self.db.flush()
        self.db.expire(registration, ["guests"])

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
