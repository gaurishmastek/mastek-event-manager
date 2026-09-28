from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.mobile import normalize_indian_mobile
from app.modules.users.models import Role

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class UserCreate(BaseModel):
    """A staff account. Admins sign in with a password plus an emailed code; officers with an emailed code only.

    The mobile is optional contact info; codes always go to the email address.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    mobile: str | None = Field(default=None, min_length=10, max_length=20)
    password: str | None = Field(default=None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    role: Role

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name must not be blank")
        return value

    @field_validator("mobile")
    @classmethod
    def normalize_mobile(cls, value: str | None) -> str | None:
        return normalize_indian_mobile(value) if value is not None else None

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str | None) -> str | None:
        if value is not None and (value.isalpha() or value.isdigit()):
            raise ValueError("password must mix letters with digits or symbols")
        return value

    @model_validator(mode="after")
    def password_matches_role(self) -> Self:
        if self.role == Role.ADMIN and self.password is None:
            raise ValueError("admins need a password")
        if self.role == Role.SECURITY_OFFICER and self.password is not None:
            raise ValueError("security officers sign in with an emailed code and do not have a password")
        return self


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
