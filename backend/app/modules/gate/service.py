from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import token_hash
from app.db.mixins import utcnow
from app.modules.auth.dependencies import CurrentUser
from app.modules.events.models import Event
from app.modules.events.repository import EventRepository
from app.modules.gate.access import EventScopePolicy
from app.modules.gate.models import CheckIn, ScanAttempt, ScanResult
from app.modules.guests.models import Registration, RegistrationStatus
from app.modules.guests.repository import RegistrationRepository


class GateEventNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class ScanOutcome:
    result: ScanResult
    registration: Registration | None = None
    check_in: CheckIn | None = None


def gate_window(event: Event) -> tuple[datetime, datetime]:
    opens = event.starts_at - timedelta(minutes=settings.gate_opens_minutes_before_start)
    closes = event.ends_at or event.starts_at + timedelta(hours=settings.gate_closes_hours_after_start_if_no_end)
    return opens, closes


class GateService:
    """Security officers scan guest passes. Every scan is logged; a pass admits exactly once."""

    def __init__(self, db: Session, policy: EventScopePolicy) -> None:
        self.db = db
        self.policy = policy
        self.events = EventRepository(db)
        self.registrations = RegistrationRepository(db)

    def get_event(self, user: CurrentUser, event_id: int) -> Event:
        # Unassigned events look the same as missing ones, so officers cannot probe other events.
        event = self.events.get(event_id)
        if event is None or not self.policy.allows(user, event_id):
            raise GateEventNotFoundError
        return event

    def scan(self, user: CurrentUser, event_id: int, token: str, gate: str | None) -> ScanOutcome:
        event = self.get_event(user, event_id)
        now = utcnow()
        hashed = token_hash(token)

        opens, closes = gate_window(event)
        if not opens <= now <= closes:
            return self._finish(ScanOutcome(ScanResult.GATE_CLOSED), event_id, user, gate)

        if self.registrations.check_in(token_hash=hashed, event_id=event_id, officer_id=user.id, at=now):
            registration = self.registrations.get_by_token_hash(hashed)
            self.db.refresh(registration)
            check_in = CheckIn(
                registration_id=registration.id,
                event_id=event_id,
                officer_id=user.id,
                gate=gate,
                method="QR",
                checked_in_at=now,
                created_by=user.id,
                updated_by=user.id,
            )
            self.db.add(check_in)
            try:
                self.db.flush()
            except IntegrityError:
                # Unreachable while check_in() guards the status, but the unique index has the final say.
                self.db.rollback()
                return self._rejected(event_id, user, gate, hashed)
            return self._finish(ScanOutcome(ScanResult.ADMITTED, registration, check_in), event_id, user, gate)

        return self._rejected(event_id, user, gate, hashed)

    def entries(self, user: CurrentUser, event_id: int, *, limit: int, offset: int) -> tuple[list[tuple], int]:
        self.get_event(user, event_id)
        total = self.db.scalar(select(func.count()).select_from(CheckIn).where(CheckIn.event_id == event_id)) or 0
        rows = self.db.execute(
            select(CheckIn, Registration)
            .join(Registration, Registration.id == CheckIn.registration_id)
            .where(CheckIn.event_id == event_id)
            .order_by(CheckIn.checked_in_at.desc(), CheckIn.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [tuple(row) for row in rows], total

    def _rejected(self, event_id: int, user: CurrentUser, gate: str | None, hashed: str) -> ScanOutcome:
        registration = self.registrations.get_by_token_hash(hashed)
        if registration is None or registration.deleted_at is not None:
            outcome = ScanOutcome(ScanResult.INVALID)
        elif registration.event_id != event_id:
            # Say nothing about the other event's guest.
            outcome = ScanOutcome(ScanResult.WRONG_EVENT)
        elif registration.status == RegistrationStatus.CHECKED_IN.value:
            check_in = self.db.scalars(select(CheckIn).where(CheckIn.registration_id == registration.id)).first()
            outcome = ScanOutcome(ScanResult.ALREADY_CHECKED_IN, registration, check_in)
        else:
            outcome = ScanOutcome(ScanResult.INVALID)
        return self._finish(outcome, event_id, user, gate)

    def _finish(self, outcome: ScanOutcome, event_id: int, user: CurrentUser, gate: str | None) -> ScanOutcome:
        self.db.add(
            ScanAttempt(
                event_id=event_id,
                officer_id=user.id,
                registration_id=outcome.registration.id
                if outcome.registration and outcome.result != ScanResult.WRONG_EVENT
                else None,
                gate=gate,
                result=outcome.result.value,
            )
        )
        self.db.commit()
        return outcome
