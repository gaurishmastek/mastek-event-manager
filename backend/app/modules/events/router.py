from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.events.repository import EventRepository
from app.modules.events.schemas import EventCreate, EventPage, EventRead, EventUpdate
from app.modules.events.service import EventNotFoundError, EventService, EventValidationError

# Admins and event managers run events; security officers only need to read them at the gate.
WRITE_ROLES = ("admin", "event_manager")
READ_ROLES = (*WRITE_ROLES, "security")

router = APIRouter(prefix="/events", tags=["events"])


def get_event_service(db: Annotated[Session, Depends(get_db)]) -> EventService:
    return EventService(EventRepository(db))


Service = Annotated[EventService, Depends(get_event_service)]
Reader = Annotated[CurrentUser, Depends(require_roles(*READ_ROLES))]
Writer = Annotated[CurrentUser, Depends(require_roles(*WRITE_ROLES))]
EventId = Annotated[int, Path(ge=1, le=2_147_483_647)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")


def _unprocessable(exc: EventValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=EventPage)
def list_events(
    service: Service,
    _: Reader,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    upcoming: bool = False,
) -> EventPage:
    items, total = service.list(limit=limit, offset=offset, search=search, upcoming=upcoming)
    return EventPage(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(data: EventCreate, service: Service, user: Writer) -> EventRead:
    try:
        return service.create(data, actor_id=user.id)
    except EventValidationError as exc:
        raise _unprocessable(exc) from exc


@router.get("/{event_id}", response_model=EventRead)
def get_event(event_id: EventId, service: Service, _: Reader) -> EventRead:
    try:
        return service.get(event_id)
    except EventNotFoundError as exc:
        raise _not_found() from exc


@router.patch("/{event_id}", response_model=EventRead)
def update_event(event_id: EventId, data: EventUpdate, service: Service, user: Writer) -> EventRead:
    try:
        return service.update(event_id, data, actor_id=user.id)
    except EventNotFoundError as exc:
        raise _not_found() from exc
    except EventValidationError as exc:
        raise _unprocessable(exc) from exc


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: EventId, service: Service, user: Writer) -> Response:
    try:
        service.delete(event_id, actor_id=user.id)
    except EventNotFoundError as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
