from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.modules.users.models import Role, User
from app.modules.users.service import get_user

# Names the events module uses for roles and the signed-in user.
ROLE_ADMIN = Role.ADMIN
ROLE_SECURITY_OFFICER = Role.SECURITY_OFFICER
CurrentUser = User

_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _UNAUTHENTICATED
    claims = decode_access_token(credentials.credentials)
    if claims is None:
        raise _UNAUTHENTICATED
    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError):
        raise _UNAUTHENTICATED from None
    # The role in the token is informational; permissions come from the database so a
    # role change, deactivation or deletion takes effect on the very next request.
    user = get_user(db, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    allowed = frozenset(roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return dependency
