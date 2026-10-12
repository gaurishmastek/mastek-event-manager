from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import _bearer, get_current_user
from app.modules.users.models import Role, User


def require_logs_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: Annotated[str | None, Query(include_in_schema=False)] = None,
    db: Session = Depends(get_db),
) -> User:
    """Only admins may read the request logs.

    The logs page's Live stream (EventSource) and downloads are plain browser requests that cannot send an
    Authorization header, so the logs API also accepts the same access token as ?token=. The logs API's own
    requests are never recorded, so the token does not end up in the logs.
    """
    if credentials is None and token:
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(credentials, db)
    if user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )
    return user
