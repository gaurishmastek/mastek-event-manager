"""Staff sign-in.

- Admins: email and password (with lockout), then a 6-digit code emailed to their account address.
- Security officers: a 6-digit code emailed to their account address. No password.

Codes go through `OtpService`, so they share its expiry, attempt limit, resend cooldown, per-address and
per-IP caps and the daily email budget.
"""

import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_login_challenge,
    decode_login_challenge,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.db.mixins import utcnow
from app.modules.auth.schemas import SessionResponse, SessionUser
from app.modules.otp.service import OtpInvalidError, OtpService
from app.modules.users.models import Role, User
from app.modules.users.service import get_active_user_by_email, get_user

ADMIN_2FA = "ADMIN_2FA"
OFFICER_LOGIN = "OFFICER_LOGIN"

# One message for every failure so the response never reveals whether an email is registered,
# whether the account is locked, disabled, or not an admin.
INVALID_LOGIN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)
INVALID_CODE = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The code is incorrect or has expired")


class AuthService:
    def __init__(self, db: Session, otp: OtpService) -> None:
        self.db = db
        self.otp = otp

    # --- admin: password, then emailed code---------------------------------------------------

    def start_admin_login(self, email: str, password: str, *, ip: str | None) -> tuple[str, datetime]:
        """Check the password and email a code. Returns the challenge id to redeem with the code."""
        user = self._check_password(email, password)
        nonce = secrets.token_urlsafe(16)
        issued = self.otp.issue(purpose=ADMIN_2FA, subject_ref=_admin_ref(user.id, nonce), email=user.email, ip=ip)
        self.db.commit()
        return create_login_challenge(user.id, nonce), issued.resend_available_at

    def finish_admin_login(self, challenge_id: str, code: str) -> SessionResponse:
        claims = decode_login_challenge(challenge_id)
        if claims is None:
            raise INVALID_CODE
        user = get_user(self.db, int(claims["sub"]))
        if user is None or not user.is_active or user.role != Role.ADMIN:
            raise INVALID_CODE
        self._verify_code(ADMIN_2FA, _admin_ref(user.id, claims["nonce"]), code)
        return self._start_session(user)

    # --- security officer: emailed code only--------------------------------------------------

    def send_officer_code(self, email: str, *, ip: str | None) -> datetime:
        """Email a code to a registered officer. Unknown addresses get the same answer and no email."""
        officer = self._officer_by_email(email)
        if officer is None:
            return utcnow() + timedelta(seconds=get_settings().otp_resend_cooldown_seconds)
        issued = self.otp.issue(purpose=OFFICER_LOGIN, subject_ref=_officer_ref(officer.id), email=officer.email, ip=ip)
        self.db.commit()
        return issued.resend_available_at

    def finish_officer_login(self, email: str, code: str) -> SessionResponse:
        officer = self._officer_by_email(email)
        if officer is None:
            raise INVALID_CODE
        self._verify_code(OFFICER_LOGIN, _officer_ref(officer.id), code)
        return self._start_session(officer, minutes=get_settings().officer_session_minutes)

    # --- shared -------------------------------------------------------------------------------

    def logout(self, user: User) -> None:
        user.session_version += 1
        self.db.commit()

    def _check_password(self, email: str, password: str) -> User:
        settings = get_settings()
        user = get_active_user_by_email(self.db, email)
        now = utcnow()

        if user is None or user.role != Role.ADMIN:
            verify_password(password, None)
            raise INVALID_LOGIN

        if user.locked_until and user.locked_until > now:
            verify_password(password, None)
            raise INVALID_LOGIN

        if not verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.max_failed_login_attempts:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.failed_login_attempts = 0
            self.db.commit()
            raise INVALID_LOGIN

        if not user.is_active:
            raise INVALID_LOGIN

        user.failed_login_attempts = 0
        user.locked_until = None
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return user

    def _officer_by_email(self, email: str) -> User | None:
        user = get_active_user_by_email(self.db, email)
        if user is None or not user.is_active or user.role != Role.SECURITY_OFFICER:
            return None
        return user

    def _verify_code(self, purpose: str, subject_ref: str, code: str) -> None:
        try:
            self.otp.verify(purpose=purpose, subject_ref=subject_ref, code=code)
        except OtpInvalidError:
            raise INVALID_CODE from None

    def _start_session(self, user: User, *, minutes: int | None = None) -> SessionResponse:
        user.last_login_at = utcnow()
        self.db.commit()
        token, expires_in = create_access_token(user.id, user.role.value, user.session_version, minutes=minutes)
        return SessionResponse(
            access_token=token,
            expires_in=expires_in,
            user=SessionUser(id=user.id, role=user.role, name=user.full_name),
        )


def _admin_ref(user_id: int, nonce: str) -> str:
    return f"admin:{user_id}:{nonce}"


def _officer_ref(user_id: int) -> str:
    return f"officer:{user_id}"
