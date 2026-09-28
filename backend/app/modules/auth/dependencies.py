"""Stand-in for the auth module.

The real implementation (login, tokens, roles) is being built separately. Until it
lands, every protected route rejects the request, so nothing is ever exposed
without authentication. Tests override `get_current_user`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status

ROLE_ADMIN = "admin"
ROLE_SECURITY_OFFICER = "security_officer"


@dataclass(frozen=True)
class CurrentUser:
    id: int
    role: str


def get_current_user() -> CurrentUser:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*roles: str) -> Callable[..., CurrentUser]:
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return dependency
