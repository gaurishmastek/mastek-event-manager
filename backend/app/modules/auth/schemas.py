from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.mobile import normalize_indian_mobile
from app.modules.users.models import Role
from app.modules.users.schemas import PASSWORD_MAX_LENGTH

OTP_CODE = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _MobileInput(_Input):
    mobile: str = Field(min_length=10, max_length=20)

    @field_validator("mobile")
    @classmethod
    def normalize_mobile(cls, value: str) -> str:
        return normalize_indian_mobile(value)


class LoginRequest(_Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class LoginChallenge(BaseModel):
    challenge_id: str
    resend_available_at: datetime


class LoginVerifyRequest(_Input):
    challenge_id: str = Field(min_length=1, max_length=1000)
    code: str = OTP_CODE


class OfficerOtpRequest(_MobileInput):
    pass


class OfficerOtpSent(BaseModel):
    resend_available_at: datetime


class OfficerVerifyRequest(_MobileInput):
    code: str = OTP_CODE


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
