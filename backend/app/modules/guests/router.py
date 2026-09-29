"""Public registration endpoints. No login: employees prove who they are with an OTP sent to their email."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.guests.schemas import (
    AttendanceDeclined,
    GuestPass,
    OtpSent,
    OtpVerify,
    PublicEventInfo,
    PublicEventRead,
    RegistrationCreate,
)
from app.modules.guests.service import (
    AlreadyCheckedInError,
    DeclineRecorded,
    DuplicateRegistrationError,
    EventFullError,
    EventNotFoundError,
    GuestRegistrationService,
    NoEmailOnRegistrationError,
    OtpSentResult,
    RegistrationClosedError,
    RegistrationNotFoundError,
    TooManyGuestsError,
)
from app.modules.notifications.email import EmailSender, get_email_sender
from app.modules.otp.service import OtpInvalidError, OtpService, OtpThrottledError, OtpUnavailableError

router = APIRouter(prefix="/public", tags=["public: guest registration"])

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
EventPublicId = Annotated[str, Path(pattern=UUID_PATTERN)]
RegistrationId = Annotated[str, Path(pattern=UUID_PATTERN)]


def get_guest_service(
    db: Annotated[Session, Depends(get_db)], email: Annotated[EmailSender, Depends(get_email_sender)]
) -> GuestRegistrationService:
    return GuestRegistrationService(db, OtpService(db, email))


Service = Annotated[GuestRegistrationService, Depends(get_guest_service)]


def _client_ip(request: Request) -> str | None:
    # Behind a reverse proxy, run uvicorn with --proxy-headers and --forwarded-allow-ips so this is the real client.
    return request.client.host if request.client else None


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _to_http(exc: Exception) -> HTTPException:
    match exc:
        case EventNotFoundError():
            return HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
        case RegistrationNotFoundError():
            return HTTPException(status.HTTP_404_NOT_FOUND, "Registration not found")
        case RegistrationClosedError():
            return HTTPException(status.HTTP_409_CONFLICT, "Registration for this event is closed")
        case EventFullError():
            return HTTPException(status.HTTP_409_CONFLICT, "This event does not have enough seats left for your party")
        case TooManyGuestsError(limit=limit):
            return HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"You can bring at most {limit} guests to this event"
            )
        case DuplicateRegistrationError():
            return HTTPException(
                status.HTTP_409_CONFLICT, "This employee ID or email address is already registered for this event"
            )
        case AlreadyCheckedInError():
            return HTTPException(status.HTTP_409_CONFLICT, "This pass has already been used to enter the event")
        case NoEmailOnRegistrationError():
            return HTTPException(status.HTTP_409_CONFLICT, "Please register again with your email address")
        case OtpThrottledError(retry_after=retry_after):
            return HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many OTP requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        case OtpUnavailableError():
            return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OTP could not be sent. Please try again later.")
        case OtpInvalidError():
            return HTTPException(status.HTTP_400_BAD_REQUEST, "The code is incorrect or has expired")
    raise exc


_SERVICE_ERRORS = (
    EventNotFoundError,
    RegistrationNotFoundError,
    RegistrationClosedError,
    EventFullError,
    TooManyGuestsError,
    DuplicateRegistrationError,
    AlreadyCheckedInError,
    NoEmailOnRegistrationError,
    OtpThrottledError,
    OtpUnavailableError,
    OtpInvalidError,
)


def _otp_sent(result: OtpSentResult) -> OtpSent:
    return OtpSent(
        registration_id=result.registration.public_id,
        email=result.registration.email_masked,
        otp_expires_at=result.otp.expires_at,
        resend_available_at=result.otp.resend_available_at,
    )


@router.get("/events/{event_public_id}", response_model=PublicEventInfo)
def get_event_for_registration(event_public_id: EventPublicId, service: Service) -> PublicEventInfo:
    try:
        event, registration_open, seats_left = service.event_info(event_public_id)
    except _SERVICE_ERRORS as exc:
        raise _to_http(exc) from exc
    return PublicEventInfo(
        **PublicEventRead.model_validate(event).model_dump(),
        registration_open=registration_open,
        seats_left=seats_left,
    )


@router.post("/events/{event_public_id}/registrations", response_model=OtpSent, status_code=status.HTTP_202_ACCEPTED)
def register_employee(
    event_public_id: EventPublicId, data: RegistrationCreate, request: Request, response: Response, service: Service
) -> OtpSent:
    """Start a registration for an employee and their guests (or resume a pending one) and email an OTP."""
    _no_store(response)
    try:
        return _otp_sent(service.register(event_public_id, data, ip=_client_ip(request)))
    except _SERVICE_ERRORS as exc:
        raise _to_http(exc) from exc


@router.post("/registrations/{registration_id}/otp", response_model=OtpSent, status_code=status.HTTP_202_ACCEPTED)
def resend_otp(registration_id: RegistrationId, request: Request, response: Response, service: Service) -> OtpSent:
    _no_store(response)
    try:
        return _otp_sent(service.resend_otp(registration_id, ip=_client_ip(request)))
    except _SERVICE_ERRORS as exc:
        raise _to_http(exc) from exc


@router.post("/registrations/{registration_id}/verify", response_model=GuestPass | AttendanceDeclined)
def verify_otp(
    registration_id: RegistrationId, data: OtpVerify, response: Response, service: Service
) -> GuestPass | AttendanceDeclined:
    """Check the OTP and return the guest's QR pass. Verifying again re-issues it and voids the old QR code.

    An employee who answered that they will not attend gets `AttendanceDeclined` instead: no seat, no pass."""
    _no_store(response)
    try:
        issued = service.verify(registration_id, data.code)
    except _SERVICE_ERRORS as exc:
        raise _to_http(exc) from exc
    registration = issued.registration
    if isinstance(issued, DeclineRecorded):
        return AttendanceDeclined(
            registration_id=registration.public_id,
            employee_id=registration.employee_id,
            employee_name=registration.employee_name,
            event=PublicEventRead.model_validate(issued.event),
            verified_at=registration.verified_at,
        )
    return GuestPass(
        registration_id=registration.public_id,
        status=registration.status,
        employee_id=registration.employee_id,
        employee_name=registration.employee_name,
        guest_names=registration.guest_names,
        adult_name=registration.adult_name,
        kid_names=registration.kid_names,
        food_preference=registration.food_preference,
        party_size=registration.party_size,
        event=PublicEventRead.model_validate(issued.event),
        qr_token=issued.token,
        qr_svg=issued.qr_svg,
        issued_at=registration.qr_issued_at,
    )
