from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.core.mobile import normalize_indian_mobile
from app.modules.events.schemas import _clean_single_line

GuestName = Annotated[str, Field(min_length=2, max_length=100), AfterValidator(_clean_single_line)]
Mobile = Annotated[str, Field(max_length=20), AfterValidator(normalize_indian_mobile)]
OtpCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegistrationCreate(_StrictInput):
    guest_name: GuestName
    mobile: Mobile
    consent: Literal[True] = Field(description="Guest agrees to their name and mobile being used for event entry")


class OtpVerify(_StrictInput):
    code: OtpCode


class PublicEventRead(BaseModel):
    """What the public registration form may show about an event. No audit or staff fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    location: str
    starts_at: datetime
    ends_at: datetime | None


class PublicEventInfo(PublicEventRead):
    registration_open: bool
    seats_left: int


class OtpSent(BaseModel):
    registration_id: str
    mobile: str = Field(description="Masked mobile the OTP was sent to")
    otp_expires_at: datetime
    resend_available_at: datetime


class GuestPass(BaseModel):
    """Returned once per verification. The token is shown to the guest and never stored in clear."""

    registration_id: str
    status: str
    guest_name: str
    event: PublicEventRead
    qr_token: str
    qr_svg: str = Field(description="QR code of qr_token as an SVG data URI")
    issued_at: datetime
