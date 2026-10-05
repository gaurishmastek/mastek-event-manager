from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import token_hash
from app.db.mixins import utcnow
from app.modules.auth.dependencies import CurrentUser
from app.modules.events.models import Event
from app.modules.events.repository import EventRepository
from app.modules.events.timing import gate_window_for
from app.modules.gate.access import EventScopePolicy
from app.modules.gate.models import CheckIn, EntryRejection, GuestEntry, ScanAttempt, ScanResult
from app.modules.gate.schemas import Decision, DecisionRequest
from app.modules.guests.models import Registration, RegistrationStatus
from app.modules.guests.repository import RegistrationRepository


class GateEventNotFoundError(Exception):
    pass


class GateDecisionError(Exception):
    """The officer's decision is malformed for this pass; nothing was recorded. The message is safe to show."""


@dataclass(frozen=True)
class ScanOutcome:
    result: ScanResult
    registration: Registration | None = None
    check_in: CheckIn | None = None
    # Guests already let in, by registration guest id.
    guest_entries: Mapping[int, GuestEntry] = field(default_factory=dict)

    @property
    def people_entered(self) -> int | None:
        if self.registration is None or self.check_in is None:
            return None
        return 1 + len(self.guest_entries)


def gate_window(event: Event) -> tuple[datetime, datetime]:
    return gate_window_for(event.starts_at, event.ends_at)


class GateService:
    """Security officers scan guest passes, check the employee's ID and decide who comes in.

    A scan only looks the pass up. Entry happens when the officer approves: the first approval (employee ID
    checked) lets in the employee and any guests present, and later approvals let in guests who arrive late on the
    shared pass. Every scan and decision is logged; each person enters at most once.
    """

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

    # ---- scan: look up the pass, change nothing ---------------------------------------------

    def scan(self, user: CurrentUser, event_id: int, token: str, gate: str | None) -> ScanOutcome:
        event = self.get_event(user, event_id)
        if not self._gate_open(event):
            return self._finish(ScanOutcome(ScanResult.GATE_CLOSED), event_id, user, gate)
        registration = self.registrations.get_by_token_hash(token_hash(token))
        return self._finish(self._state(registration, event_id), event_id, user, gate)

    # ---- decide: approve or reject ------------------------------------------------------------

    def decide(self, user: CurrentUser, event_id: int, request: DecisionRequest) -> ScanOutcome:
        event = self.get_event(user, event_id)
        gate = request.gate
        if not self._gate_open(event):
            return self._finish(ScanOutcome(ScanResult.GATE_CLOSED), event_id, user, gate)

        hashed = token_hash(request.token)
        state = self._state(self.registrations.get_by_token_hash(hashed), event_id)
        if state.result not in (ScanResult.PENDING_VERIFICATION, ScanResult.PENDING_GUESTS):
            # Invalid, another event's, or fully used: nothing to approve or reject.
            return self._finish(state, event_id, user, gate)

        registration = state.registration
        if request.decision is Decision.REJECT:
            self.db.add(
                EntryRejection(
                    registration_id=registration.id,
                    event_id=event_id,
                    officer_id=user.id,
                    gate=gate,
                    reason=request.reason.value,
                    note=request.note,
                    created_by=user.id,
                    updated_by=user.id,
                )
            )
            return self._finish(ScanOutcome(ScanResult.REJECTED, registration), event_id, user, gate)

        self._require_known_guests(registration, request.guest_ids_entered)
        if state.result is ScanResult.PENDING_VERIFICATION:
            return self._admit_first(user, event_id, hashed, registration, request)
        return self._admit_late(user, event_id, registration, state, request)

    def _admit_first(
        self, user: CurrentUser, event_id: int, hashed: str, registration: Registration, request: DecisionRequest
    ) -> ScanOutcome:
        if not request.employee_id_checked:
            raise GateDecisionError("Check the employee's ID card and tick it before approving entry.")

        now = utcnow()
        gate = request.gate
        if not self.registrations.check_in(token_hash=hashed, event_id=event_id, officer_id=user.id, at=now):
            # Another officer admitted this pass first; show their entry rather than admitting twice.
            return self._finish(self._used(self.registrations.get_by_token_hash(hashed)), event_id, user, gate)

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
            self._add_guest_entries(check_in, request.guest_ids_entered, user, gate, now)
        except IntegrityError:
            # Unreachable while check_in() guards the status, but the unique indexes have the final say.
            self.db.rollback()
            return self._finish(
                self._state(self.registrations.get_by_token_hash(hashed), event_id), event_id, user, gate
            )
        outcome = ScanOutcome(ScanResult.ADMITTED, registration, check_in, self._guest_entries(registration))
        return self._finish(outcome, event_id, user, gate)

    def _admit_late(
        self, user: CurrentUser, event_id: int, registration: Registration, state: ScanOutcome, request: DecisionRequest
    ) -> ScanOutcome:
        """The employee is already in; let in the guests who have arrived since, on the shared pass."""
        if not request.guest_ids_entered:
            raise GateDecisionError("Tick at least one guest to let in.")

        gate = request.gate
        check_in = state.check_in
        if any(guest_id in state.guest_entries for guest_id in request.guest_ids_entered):
            outcome = ScanOutcome(ScanResult.GUESTS_ALREADY_ENTERED, registration, check_in, state.guest_entries)
            return self._finish(outcome, event_id, user, gate)

        try:
            self._add_guest_entries(check_in, request.guest_ids_entered, user, gate, utcnow())
        except IntegrityError:
            # Another officer let one of them in at the same moment; show the pass as it now stands.
            self.db.rollback()
            refreshed = self.registrations.get_by_token_hash(token_hash(request.token))
            outcome = ScanOutcome(
                ScanResult.GUESTS_ALREADY_ENTERED, refreshed, check_in, self._guest_entries(refreshed)
            )
            return self._finish(outcome, event_id, user, gate)
        outcome = ScanOutcome(ScanResult.ADMITTED, registration, check_in, self._guest_entries(registration))
        return self._finish(outcome, event_id, user, gate)

    # ---- entries --------------------------------------------------------------------------------

    def entries(self, user: CurrentUser, event_id: int, *, limit: int, offset: int) -> tuple[list[tuple], int]:
        """Check-ins with their registration and how many accompanying guests are in, newest first."""
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
        check_in_ids = [check_in.id for check_in, _ in rows]
        counts = dict(
            self.db.execute(
                select(GuestEntry.check_in_id, func.count())
                .where(GuestEntry.check_in_id.in_(check_in_ids), GuestEntry.deleted_at.is_(None))
                .group_by(GuestEntry.check_in_id)
            ).all()
        )
        return [(check_in, registration, counts.get(check_in.id, 0)) for check_in, registration in rows], total

    # ---- helpers --------------------------------------------------------------------------------

    @staticmethod
    def _gate_open(event: Event) -> bool:
        opens, closes = gate_window(event)
        return opens <= utcnow() <= closes

    def _state(self, registration: Registration | None, event_id: int) -> ScanOutcome:
        """Where a pass stands, without changing anything."""
        if registration is None or registration.deleted_at is not None:
            return ScanOutcome(ScanResult.INVALID)
        if registration.event_id != event_id:
            # Say nothing about the other event's guest.
            return ScanOutcome(ScanResult.WRONG_EVENT)
        if registration.status == RegistrationStatus.VERIFIED.value:
            return ScanOutcome(ScanResult.PENDING_VERIFICATION, registration)
        if registration.status == RegistrationStatus.CHECKED_IN.value:
            return self._used(registration)
        return ScanOutcome(ScanResult.INVALID)

    def _used(self, registration: Registration | None) -> ScanOutcome:
        """A pass whose employee is in: awaiting late guests if any remain, otherwise fully used."""
        if registration is None:
            return ScanOutcome(ScanResult.INVALID)
        check_in = self.db.scalars(select(CheckIn).where(CheckIn.registration_id == registration.id)).first()
        entries = self._guest_entries(registration)
        waiting = check_in is not None and any(guest.id not in entries for guest in registration.guests)
        result = ScanResult.PENDING_GUESTS if waiting else ScanResult.ALREADY_CHECKED_IN
        return ScanOutcome(result, registration, check_in, entries)

    def _guest_entries(self, registration: Registration) -> dict[int, GuestEntry]:
        guest_ids = [guest.id for guest in registration.guests]
        if not guest_ids:
            return {}
        rows = self.db.scalars(
            select(GuestEntry).where(GuestEntry.registration_guest_id.in_(guest_ids), GuestEntry.deleted_at.is_(None))
        )
        return {row.registration_guest_id: row for row in rows}

    @staticmethod
    def _require_known_guests(registration: Registration, guest_ids: Sequence[int]) -> None:
        on_pass = {guest.id for guest in registration.guests}
        if not set(guest_ids) <= on_pass:
            raise GateDecisionError("Some of the selected guests are not on this pass. Scan the pass again.")

    def _add_guest_entries(
        self, check_in: CheckIn, guest_ids: Sequence[int], user: CurrentUser, gate: str | None, at: datetime
    ) -> None:
        for guest_id in guest_ids:
            self.db.add(
                GuestEntry(
                    check_in_id=check_in.id,
                    registration_guest_id=guest_id,
                    officer_id=user.id,
                    gate=gate,
                    entered_at=at,
                    created_by=user.id,
                    updated_by=user.id,
                )
            )
        self.db.flush()

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
