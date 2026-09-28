from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import (
    LoginChallenge,
    LoginRequest,
    LoginVerifyRequest,
    OfficerOtpRequest,
    OfficerOtpSent,
    OfficerVerifyRequest,
    SessionResponse,
)
from app.modules.auth.service import AuthService
from app.modules.notifications.email import EmailSender, get_email_sender
from app.modules.otp.service import OtpService, OtpThrottledError, OtpUnavailableError
from app.modules.users.models import User
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(
    db: Annotated[Session, Depends(get_db)], email: Annotated[EmailSender, Depends(get_email_sender)]
) -> AuthService:
    return AuthService(db, OtpService(db, email))


Service = Annotated[AuthService, Depends(get_auth_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _client_ip(request: Request) -> str | None:
    # Behind a reverse proxy, run uvicorn with --proxy-headers and --forwarded-allow-ips so this is the real client.
    return request.client.host if request.client else None


def _otp_http_error(exc: OtpThrottledError | OtpUnavailableError) -> HTTPException:
    if isinstance(exc, OtpThrottledError):
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many code requests. Please try again later.",
            headers={"Retry-After": str(exc.retry_after)},
        )
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The code could not be sent. Please try again later.")


@router.post("/login", response_model=LoginChallenge)
def login(data: LoginRequest, request: Request, service: Service) -> LoginChallenge:
    """Admin step 1: email and password. Emails a code to the admin's address."""
    try:
        challenge_id, resend_at = service.start_admin_login(data.email, data.password, ip=_client_ip(request))
    except (OtpThrottledError, OtpUnavailableError) as exc:
        raise _otp_http_error(exc) from exc
    return LoginChallenge(challenge_id=challenge_id, resend_available_at=resend_at)


@router.post("/login/verify", response_model=SessionResponse)
def login_verify(data: LoginVerifyRequest, service: Service) -> SessionResponse:
    """Admin step 2: the code from the email."""
    return service.finish_admin_login(data.challenge_id, data.code)


@router.post("/officer/otp", response_model=OfficerOtpSent, status_code=status.HTTP_202_ACCEPTED)
def officer_otp(data: OfficerOtpRequest, request: Request, service: Service) -> OfficerOtpSent:
    """Officer step 1. Answers the same whether or not the address belongs to an officer."""
    try:
        resend_at = service.send_officer_code(data.email, ip=_client_ip(request))
    except (OtpThrottledError, OtpUnavailableError) as exc:
        raise _otp_http_error(exc) from exc
    return OfficerOtpSent(resend_available_at=resend_at)


@router.post("/officer/verify", response_model=SessionResponse)
def officer_verify(data: OfficerVerifyRequest, service: Service) -> SessionResponse:
    return service.finish_officer_login(data.email, data.code)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: CurrentUser, service: Service) -> Response:
    """Revokes every access token issued to this user so far."""
    service.logout(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user
