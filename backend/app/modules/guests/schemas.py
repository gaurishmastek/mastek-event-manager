from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from app.core.email import normalize_email
from app.core.mobile import normalize_indian_mobile
from app.modules.events.models import MAX_GUESTS_PER_REGISTRATION_CAP
from app.modules.events.schemas import _clean_single_line

PersonName = Annotated[str, Field(min_length=2, max_length=100), AfterValidator(_clean_single_line)]
# Letters, digits, '.', '_' and '-', starting with a letter or digit, e.g. "MT-10423".
EmployeeId = Annotated[str, StringConstraints(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
Email = Annotated[EmailStr, Field(max_length=254), AfterValidator(normalize_email)]
Mobile = Annotated[str, Field(min_length=10, max_length=20), AfterValidator(normalize_indian_mobile)]
GuestCount = Annotated[int, Field(ge=0, le=MAX_GUESTS_PER_REGISTRATION_CAP, strict=True)]
OtpCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]
StatusFilter = Literal["PENDING_OTP", "VERIFIED", "CHECKED_IN"]


def normalize_employee_id(employee_id: str) -> str:
    """Employee ids are compared case-insensitively: 'mt-104' and 'MT-104' are the same employee."""
    return employee_id.upper()


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegistrationCreate(_StrictInput):
    employee_id: EmployeeId
    employee_name: PersonName
    email: Email
    mobile: Mobile = Field(description="Indian mobile number, stored as +91XXXXXXXXXX. OTPs still go by email only")
    number_of_guests: GuestCount = Field(description="Accompanying guests, not counting the employee")
    guest_names: list[PersonName] = Field(default_factory=list, max_length=MAX_GUESTS_PER_REGISTRATION_CAP)
    consent: Literal[True] = Field(
        description="Employee agrees to their and their guests' details being used for event entry"
    )

    @model_validator(mode="after")
    def _guest_names_match_count(self) -> "RegistrationCreate":
        if len(self.guest_names) != self.number_of_guests:
            raise ValueError("guest_names must list exactly number_of_guests names")
        return self


class OtpVerify(_StrictInput):
    code: OtpCode


class PublicEventRead(BaseModel):
    """What the public registration form may show about an event. No internal id, audit or staff fields."""

    model_config = ConfigDict(from_attributes=True)

    public_id: str
    title: str
    description: str | None
    location: str
    starts_at: datetime
    ends_at: datetime | None
    max_guests_per_registration: int


class PublicEventInfo(PublicEventRead):
    registration_open: bool
    seats_left: int


class OtpSent(BaseModel):
    registration_id: str
    email: str = Field(description="Masked address the OTP was sent to")
    otp_expires_at: datetime
    resend_available_at: datetime


class GuestPass(BaseModel):
    """Returned once per verification. The token is shown to the employee and never stored in clear."""

    registration_id: str
    status: str
    employee_id: str | None
    employee_name: str
    guest_names: list[str]
    party_size: int = Field(description="The employee plus their accompanying guests; the pass admits all of them once")
    event: PublicEventRead
    qr_token: str
    qr_svg: str = Field(description="QR code of qr_token as an SVG data URI")
    issued_at: datetime


class RegistrationAdminRead(BaseModel):
    """An admin's view of one registration. Contact details are masked; no QR, OTP or encrypted data."""

    registration_id: str
    employee_id: str | None
    employee_name: str
    email_masked: str | None
    mobile_masked: str | None
    guest_names: list[str]
    number_of_guests: int
    party_size: int
    status: str
    verified_at: datetime | None
    qr_issued: bool
    qr_issued_at: datetime | None
    checked_in_at: datetime | None
    created_at: datetime


class RegistrationAdminPage(BaseModel):
    items: list[RegistrationAdminRead]
    total: int
    limit: int
    offset: int
