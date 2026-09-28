from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.users import service
from app.modules.users.models import Role, User
from app.modules.users.schemas import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])

admin_only = require_roles(Role.ADMIN)


@router.get("", response_model=list[UserRead])
def list_users(role: Role | None = None, db: Session = Depends(get_db), _: User = Depends(admin_only)) -> list[User]:
    """Staff accounts, optionally only one role (e.g. `?role=security_officer` for the assignment picker)."""
    return service.list_users(db, role=role)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: Session = Depends(get_db), actor: User = Depends(admin_only)) -> User:
    return service.create_user(db, data, actor_id=actor.id)
