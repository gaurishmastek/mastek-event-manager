from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import Role
from app.modules.users.schemas import PASSWORD_MAX_LENGTH

OTP_CODE = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class LoginChallenge(BaseModel):
    challenge_id: str
    resend_available_at: datetime


class LoginVerifyRequest(_Input):
    challenge_id: str = Field(min_length=1, max_length=1000)
    code: str = OTP_CODE


class OfficerLoginRequest(_Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class SessionUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Role
    name: str


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int
    user: SessionUser
