from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.gate.access import GATE_ROLES, EventScopePolicy
from app.modules.gate.models import CheckIn, ScanResult
from app.modules.gate.schemas import EntryPage, EntryRead, ScannedGuest, ScanRequest, ScanResponse
from app.modules.gate.service import GateEventNotFoundError, GateService, ScanOutcome
from app.modules.guests.models import Registration

router = APIRouter(prefix="/gate", tags=["gate"])

EventId = Annotated[int, Path(ge=1, le=2_147_483_647)]
GateUser = Annotated[CurrentUser, Depends(require_roles(*GATE_ROLES))]


def get_gate_service(db: Annotated[Session, Depends(get_db)]) -> GateService:
    return GateService(db, EventScopePolicy(db))


Service = Annotated[GateService, Depends(get_gate_service)]

_MESSAGES = {
    ScanResult.ADMITTED: "Entry allowed",
    ScanResult.ALREADY_CHECKED_IN: "This pass has already been used",
    ScanResult.WRONG_EVENT: "This pass is for a different event",
    ScanResult.INVALID: "This pass is not valid",
    ScanResult.GATE_CLOSED: "Entry is not open for this event right now",
}


def _guest(registration: Registration) -> ScannedGuest:
    return ScannedGuest(name=registration.guest_name, mobile=registration.mobile_masked)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")


def _scan_response(outcome: ScanOutcome) -> ScanResponse:
    show_guest = outcome.result in (ScanResult.ADMITTED, ScanResult.ALREADY_CHECKED_IN)
    check_in: CheckIn | None = outcome.check_in
    return ScanResponse(
        result=outcome.result.value,
        message=_MESSAGES[outcome.result],
        guest=_guest(outcome.registration) if show_guest and outcome.registration else None,
        checked_in_at=check_in.checked_in_at if check_in else None,
        gate=check_in.gate if check_in else None,
    )


@router.post("/events/{event_id}/scan", response_model=ScanResponse)
def scan_pass(
    event_id: EventId, data: ScanRequest, response: Response, service: Service, user: GateUser
) -> ScanResponse:
    """Check a guest in. Always 200 with a `result` the scanner shows; only `admitted` lets the guest in."""
    response.headers["Cache-Control"] = "no-store"
    try:
        outcome = service.scan(user, event_id, data.token, data.gate)
    except GateEventNotFoundError as exc:
        raise _not_found() from exc
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
        EntryRead(guest=_guest(reg), checked_in_at=ci.checked_in_at, gate=ci.gate, officer_id=ci.officer_id)
        for ci, reg in rows
    ]
    return EntryPage(items=items, total=total, limit=limit, offset=offset)
