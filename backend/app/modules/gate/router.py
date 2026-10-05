from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.gate.access import GATE_ROLES, EventScopePolicy
from app.modules.gate.models import CheckIn, GuestEntry, ScanResult
from app.modules.gate.schemas import (
    DecisionRequest,
    EntryPage,
    EntryRead,
    PartyMember,
    ScannedGuest,
    ScanRequest,
    ScanResponse,
)
from app.modules.gate.service import GateDecisionError, GateEventNotFoundError, GateService, ScanOutcome
from app.modules.guests.models import Registration

router = APIRouter(prefix="/gate", tags=["gate"])

EventId = Annotated[int, Path(ge=1, le=2_147_483_647)]
GateUser = Annotated[CurrentUser, Depends(require_roles(*GATE_ROLES))]


def get_gate_service(db: Annotated[Session, Depends(get_db)]) -> GateService:
    return GateService(db, EventScopePolicy(db))


Service = Annotated[GateService, Depends(get_gate_service)]

_MESSAGES = {
    ScanResult.PENDING_VERIFICATION: "Check the employee's ID, then approve or reject entry",
    ScanResult.PENDING_GUESTS: "The employee is already in. Some guests are still to arrive",
    ScanResult.ADMITTED: "Entry allowed",
    ScanResult.REJECTED: "Entry refused",
    ScanResult.ALREADY_CHECKED_IN: "This pass has already been used",
    ScanResult.GUESTS_ALREADY_ENTERED: "Some of these guests have already entered",
    ScanResult.WRONG_EVENT: "This pass is for a different event",
    ScanResult.INVALID: "This pass is not valid",
    ScanResult.GATE_CLOSED: "Entry is not open for this event right now",
}

# Party details go to the officer only for a pass of this event that is awaiting a decision, admitted or used.
_SHOWS_PARTY = (
    ScanResult.PENDING_VERIFICATION,
    ScanResult.PENDING_GUESTS,
    ScanResult.ADMITTED,
    ScanResult.ALREADY_CHECKED_IN,
    ScanResult.GUESTS_ALREADY_ENTERED,
)


def _guest(
    registration: Registration, entries: Mapping[int, GuestEntry] | None = None, *, employee_entered: bool = False
) -> ScannedGuest:
    # Registrations from before the switch to email only have a masked mobile.
    contact = registration.email_masked or registration.mobile_masked or ""
    members = (
        [
            PartyMember(
                id=guest.id,
                name=guest.name,
                type=guest.guest_type,
                age=guest.age,
                entered=guest.id in entries,
                entered_at=entries[guest.id].entered_at if guest.id in entries else None,
            )
            for guest in registration.guests
        ]
        if entries is not None
        else []
    )
    return ScannedGuest(
        name=registration.employee_name,
        contact=contact,
        employee_id=registration.employee_id,
        guest_names=registration.guest_names,
        party_size=registration.party_size,
        email_masked=registration.email_masked,
        mobile_masked=registration.mobile_masked,
        employee_entered=employee_entered,
        members=members,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")


def _scan_response(outcome: ScanOutcome) -> ScanResponse:
    show_guest = outcome.result in _SHOWS_PARTY and outcome.registration is not None
    check_in: CheckIn | None = outcome.check_in
    return ScanResponse(
        result=outcome.result.value,
        message=_MESSAGES[outcome.result],
        guest=_guest(outcome.registration, outcome.guest_entries, employee_entered=check_in is not None)
        if show_guest
        else None,
        checked_in_at=check_in.checked_in_at if check_in else None,
        gate=check_in.gate if check_in else None,
        people_entered=outcome.people_entered if show_guest else None,
    )


@router.post("/events/{event_id}/scan", response_model=ScanResponse)
def scan_pass(
    event_id: EventId, data: ScanRequest, response: Response, service: Service, user: GateUser
) -> ScanResponse:
    """Look a pass up. Nothing changes: `pending_verification` or `pending_guests` hand the officer the party to
    check; entry happens only when the officer approves with `POST .../decision`."""
    response.headers["Cache-Control"] = "no-store"
    try:
        outcome = service.scan(user, event_id, data.token, data.gate)
    except GateEventNotFoundError as exc:
        raise _not_found() from exc
    return _scan_response(outcome)


@router.post("/events/{event_id}/decision", response_model=ScanResponse)
def decide_entry(
    event_id: EventId, data: DecisionRequest, response: Response, service: Service, user: GateUser
) -> ScanResponse:
    """Approve or reject a scanned pass. Always 200 with a `result` unless the request itself is wrong (422).

    Only `admitted` lets anyone in. The first approval needs `employee_id_checked`; later approvals let in guests
    who arrive after the employee, each at most once.
    """
    response.headers["Cache-Control"] = "no-store"
    try:
        outcome = service.decide(user, event_id, data)
    except GateEventNotFoundError as exc:
        raise _not_found() from exc
    except GateDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _scan_response(outcome)


@router.get("/events/{event_id}/entries", response_model=EntryPage)
def list_entries(
    event_id: EventId,
    response: Response,
    service: Service,
    user: GateUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> EntryPage:
    response.headers["Cache-Control"] = "no-store"
    try:
        rows, total = service.entries(user, event_id, limit=limit, offset=offset)
    except GateEventNotFoundError as exc:
        raise _not_found() from exc
    items = [
        EntryRead(
            guest=_guest(reg, employee_entered=True),
            checked_in_at=ci.checked_in_at,
            gate=ci.gate,
            officer_id=ci.officer_id,
            people_entered=1 + guests_in,
        )
        for ci, reg, guests_in in rows
    ]
    return EntryPage(items=items, total=total, limit=limit, offset=offset)
