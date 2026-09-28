from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"  # noqa: S105 - claim value, not a secret
TOKEN_TYPE_LOGIN_CHALLENGE = "login_challenge"  # noqa: S105 - claim value, not a secret

# Argon2id with the library's current recommended parameters.
_hasher = PasswordHasher()

# Verified against when the email is unknown, so a failed login takes the same
# time whether or not the account exists.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalisation")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(
    user_id: int, role: str, session_version: int, *, minutes: int | None = None
) -> tuple[str, int]:
    settings = get_settings()
    expires_in = (minutes or settings.access_token_expire_minutes) * 60
    token = _encode({"sub": str(user_id), "role": role, "sv": session_version}, TOKEN_TYPE_ACCESS, expires_in)
    return token, expires_in


def create_login_challenge(user_id: int, nonce: str) -> str:
    """Short-lived proof that the password step passed; only redeemable with the second-factor code."""
    return _encode({"sub": str(user_id), "nonce": nonce}, TOKEN_TYPE_LOGIN_CHALLENGE, get_settings().otp_ttl_seconds)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Return the token's claims, or None if it is invalid, expired or not an access token."""
    return _decode(token, TOKEN_TYPE_ACCESS, ["sub", "exp", "iat", "type", "sv"])


def decode_login_challenge(token: str) -> dict[str, Any] | None:
    return _decode(token, TOKEN_TYPE_LOGIN_CHALLENGE, ["sub", "exp", "iat", "type", "nonce"])


def _encode(claims: dict[str, Any], token_type: str, expires_in: int) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "type": token_type, "iat": now, "exp": now + timedelta(seconds=expires_in)}
    return jwt.encode(payload, get_settings().secret_key, algorithm=JWT_ALGORITHM)


def _decode(token: str, token_type: str, required: list[str]) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALGORITHM], options={"require": required})
    except jwt.PyJWTError:
        return None
    if claims.get("type") != token_type:
        return None
    return claims
