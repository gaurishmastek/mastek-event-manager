from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate


def normalise_email(email: str) -> str:
    return email.strip().lower()


def get_active_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalise_email(email), User.deleted_at.is_(None)))


def get_user(db: Session, user_id: int) -> User | None:
    return db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.id)))


def create_user(db: Session, data: UserCreate, actor_id: int | None = None) -> User:
    email = normalise_email(data.email)
    exists = db.scalar(select(func.count()).select_from(User).where(User.email == email))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")
    user = User(
        email=email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
