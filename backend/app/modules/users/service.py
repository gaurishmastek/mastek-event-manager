import secrets

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_pii, keyed_hash
from app.core.security import hash_password
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate


def normalise_email(email: str) -> str:
    return email.strip().lower()


def get_active_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalise_email(email), User.deleted_at.is_(None)))


def mobile_lookup_hash(mobile: str) -> str:
    return keyed_hash(mobile, purpose="staff-mobile")


def get_active_user_by_mobile(db: Session, mobile: str) -> User | None:
    return db.scalar(select(User).where(User.mobile_hash == mobile_lookup_hash(mobile), User.deleted_at.is_(None)))


def get_user(db: Session, user_id: int) -> User | None:
    return db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.id)))


def create_user(db: Session, data: UserCreate, actor_id: int | None = None) -> User:
    email = normalise_email(data.email)
    exists = db.scalar(select(func.count()).select_from(User).where(User.email == email))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")
    mobile_hash = mobile_lookup_hash(data.mobile)
    if db.scalar(select(func.count()).select_from(User).where(User.mobile_hash == mobile_hash)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this mobile already exists")
    # Officers have no password; store a hash of a random value nobody knows so the column stays uniform.
    password = data.password or secrets.token_urlsafe(32)
    user = User(
        email=email,
        full_name=data.full_name,
        mobile_hash=mobile_hash,
        mobile_encrypted=encrypt_pii(data.mobile),
        password_hash=hash_password(password),
        role=data.role,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
