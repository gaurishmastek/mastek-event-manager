"""Admin view of an event's registrations. Mounted behind authentication; admins only."""

from collections.abc import Iterator
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import ROLE_ADMIN, CurrentUser, require_roles
from app.modules.guests.excel import build_registration_workbook
from app.modules.guests.models import Registration
from app.modules.guests.schemas import (
    AdminQrPass,
    RegistrationAdminPage,
    RegistrationAdminRead,
    RegistrationAdminUpdate,
    StatusFilter,
)
from app.modules.guests.service import (
    DuplicateRegistrationError,
    EventFullError,
    EventNotFoundError,
    QrRegenerationUnavailableError,
    RegistrationListService,
    RegistrationNotFoundError,
    RegistrationPartyEditLockedError,
    TooManyGuestsError,
)

router = APIRouter(prefix="/events", tags=["admin: registrations"])

EventId = Annotated[int, Path(ge=1, le=2_147_483_647)]
Admin = Annotated[CurrentUser, Depends(require_roles(ROLE_ADMIN))]


def get_registration_list_service(db: Annotated[Session, Depends(get_db)]) -> RegistrationListService:
    return RegistrationListService(db)


Service = Annotated[RegistrationListService, Depends(get_registration_list_service)]
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file_chunks(file: BinaryIO, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    try:
        while chunk := file.read(chunk_size):
            yield chunk
    finally:
        file.close()


def to_admin_read(registration: Registration) -> RegistrationAdminRead:
    return RegistrationAdminRead(
        registration_id=registration.public_id,
        employee_id=registration.employee_id,
        employee_name=registration.employee_name,
        email_masked=registration.email_masked,
        mobile_masked=registration.mobile_masked,
        attending=registration.attending,
        family_attending=registration.family_attending,
        guest_names=registration.guest_names,
        adult_name=registration.adult_name,
        kid_names=registration.kid_names,
        kid_ages=registration.kid_ages,
        food_preference=registration.food_preference,
        number_of_guests=registration.number_of_guests,
        party_size=registration.party_size,
        status=registration.status,
        verified_at=registration.verified_at,
        qr_issued=registration.qr_token_hash is not None,
        qr_issued_at=registration.qr_issued_at,
        checked_in_at=registration.checked_in_at,
        created_at=registration.created_at,
    )


@router.get("/{event_id}/registrations", response_model=RegistrationAdminPage)
def list_registrations(
    event_id: EventId,
    response: Response,
    service: Service,
    _: Admin,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100, description="Employee id or name")] = None,
    status_filter: Annotated[StatusFilter | None, Query(alias="status")] = None,
) -> RegistrationAdminPage:
    response.headers["Cache-Control"] = "no-store"
    try:
        rows, total = service.list(event_id, limit=limit, offset=offset, search=search, status=status_filter)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found") from exc
    return RegistrationAdminPage(items=[to_admin_read(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/{event_id}/registrations/export.xlsx", response_class=StreamingResponse)
def export_registrations(event_id: EventId, service: Service, _: Admin) -> StreamingResponse:
    """Download every active registration for one event as an admin-safe Excel workbook."""
    try:
        _, registrations = service.export(event_id)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found") from exc

    workbook = build_registration_workbook(registrations)
    return StreamingResponse(
        _file_chunks(workbook),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="event-{event_id}-registrations.xlsx"',
        },
    )


@router.patch("/{event_id}/registrations/{registration_id}", response_model=RegistrationAdminRead)
def update_registration(
    event_id: EventId,
    registration_id: str,
    data: RegistrationAdminUpdate,
    service: Service,
    admin: Admin,
) -> RegistrationAdminRead:
    try:
        return to_admin_read(service.update(event_id, registration_id, data, actor_id=admin.id))
    except EventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found") from exc
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found") from exc
    except DuplicateRegistrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Employee ID or email already registered"
        ) from exc
    except EventFullError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This event does not have enough seats left"
        ) from exc
    except TooManyGuestsError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"At most {exc.limit} guests are allowed for this event",
        ) from exc
    except RegistrationPartyEditLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The accompanying guests of a checked-in registration cannot be edited",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{event_id}/registrations/{registration_id}/qr", response_model=AdminQrPass)
def regenerate_registration_qr(event_id: EventId, registration_id: str, service: Service, admin: Admin) -> AdminQrPass:
    try:
        issued = service.regenerate_qr(event_id, registration_id, actor_id=admin.id)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found") from exc
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found") from exc
    except QrRegenerationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A QR pass can be generated only for a verified registration that has not checked in",
        ) from exc
    issued_at = issued.registration.qr_issued_at
    if issued_at is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="QR issue time is unavailable")
    return AdminQrPass(
        registration_id=issued.registration.public_id,
        employee_name=issued.registration.employee_name,
        qr_svg=issued.qr_svg,
        issued_at=issued_at,
    )
