"""Admin view of an event's registrations. Mounted behind authentication; admins only."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import ROLE_ADMIN, CurrentUser, require_roles
from app.modules.guests.models import Registration
from app.modules.guests.schemas import RegistrationAdminPage, RegistrationAdminRead, StatusFilter
from app.modules.guests.service import EventNotFoundError, RegistrationListService

router = APIRouter(prefix="/events", tags=["admin: registrations"])

EventId = Annotated[int, Path(ge=1, le=2_147_483_647)]
Admin = Annotated[CurrentUser, Depends(require_roles(ROLE_ADMIN))]


def get_registration_list_service(db: Annotated[Session, Depends(get_db)]) -> RegistrationListService:
    return RegistrationListService(db)


Service = Annotated[RegistrationListService, Depends(get_registration_list_service)]


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
