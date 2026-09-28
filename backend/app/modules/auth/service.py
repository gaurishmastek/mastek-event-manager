from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.db.mixins import utcnow
from app.modules.auth.schemas import TokenResponse
from app.modules.users.service import get_active_user_by_email

# One message for every failure so the response never reveals whether an email is registered,
# whether the account is locked, or whether it is disabled.
INVALID_LOGIN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


def authenticate(db: Session, email: str, password: str) -> TokenResponse:
    settings = get_settings()
    user = get_active_user_by_email(db, email)
    now = utcnow()

    if user is None:
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
        db.commit()
        raise INVALID_LOGIN

    if not user.is_active:
        raise INVALID_LOGIN

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    db.commit()

    token, expires_in = create_access_token(user.id, user.role.value)
    return TokenResponse(access_token=token, expires_in=expires_in)
