from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.email import normalize_email
from app.core.mobile import normalize_indian_mobile
from app.modules.events.schemas import _clean_single_line
from app.modules.guests.models import MAX_KID_AGE, MIN_KID_AGE, FoodPreference, GuestType

PersonName = Annotated[str, Field(min_length=2, max_length=100), AfterValidator(_clean_single_line)]
# Letters, digits, '.', '_' and '-', starting with a letter or digit, e.g. "MT-10423".
EmployeeId = Annotated[str, StringConstraints(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
Email = Annotated[EmailStr, Field(max_length=254), AfterValidator(normalize_email)]
Mobile = Annotated[str, Field(min_length=10, max_length=20), AfterValidator(normalize_indian_mobile)]
KidAge = Annotated[int, Field(ge=MIN_KID_AGE, le=MAX_KID_AGE, strict=True)]
OtpCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]
StatusFilter = Literal["PENDING_OTP", "VERIFIED", "CHECKED_IN", "DECLINED"]

# An attending employee may bring one adult family member and up to three kids. MAX_ACCOMPANYING_KIDS is
# mirrored as MAX_KIDS in frontend/src/app/public/registration-form.ts.
MAX_ACCOMPANYING_ADULTS = 1
MAX_ACCOMPANYING_KIDS = 3
# Whether an employee attending alone (no family) must still choose a food preference. Attendees who bring
# family always must. Mirrored in frontend/src/app/public/registration-form.ts.
FOOD_PREFERENCE_REQUIRED_WHEN_ALONE = True


def normalize_employee_id(employee_id: str) -> str:
    """Employee ids are compared case-insensitively: 'mt-104' and 'MT-104' are the same employee."""
    return employee_id.upper()


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegistrationCreate(_StrictInput):
    """The public registration form. Which fields apply depends on the attendance and family answers, and
    fields that do not apply must be left out (or null, false or empty) rather than silently ignored."""

    employee_id: EmployeeId
    employee_name: PersonName
    email: Email
    mobile: Mobile | None = Field(
        default=None, description="Optional Indian mobile number, stored as +91XXXXXXXXXX. OTPs still go by email only"
    )
    attending: StrictBool = Field(description="Will the employee attend the event?")
    family_attending: StrictBool | None = Field(
        default=None, description="Will family members accompany the employee? Required when attending"
    )
    accompanying_adult: StrictBool = Field(default=False, description="One adult family member comes along")
    accompanying_kids: StrictBool = Field(default=False, description="Kids come along")
    adult_name: PersonName | None = Field(default=None, description="Required when accompanying_adult is true")
    kid_names: list[PersonName] = Field(
        default_factory=list,
        max_length=10,
        description=f"1 to {MAX_ACCOMPANYING_KIDS} names when accompanying_kids is true, otherwise empty",
    )
    kid_ages: list[KidAge] = Field(
        default_factory=list,
        max_length=10,
        description=f"Each kid's age in whole years ({MIN_KID_AGE}-{MAX_KID_AGE}), in the same order as kid_names",
    )
    food_preference: FoodPreference | None = Field(default=None, description="Required when attending")
    consent: Literal[True] = Field(
        description="Employee agrees to their and their guests' details being used for event entry"
    )

    @field_validator("mobile", mode="before")
    @classmethod
    def _blank_mobile_is_absent(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _answers_are_consistent(self) -> "RegistrationCreate":
        if not self.attending:
            if (
                self.family_attending is not None
                or self.accompanying_adult
                or self.accompanying_kids
                or self.adult_name is not None
                or self.kid_names
                or self.kid_ages
                or self.food_preference is not None
            ):
                raise ValueError("family and food details must not be sent when you are not attending the event")
            return self

        if self.family_attending is None:
            raise ValueError("family_attending is required when you are attending the event")
        if not self.family_attending:
            if (
                self.accompanying_adult
                or self.accompanying_kids
                or self.adult_name is not None
                or self.kid_names
                or self.kid_ages
            ):
                raise ValueError("family member details must not be sent when your family is not accompanying you")
        else:
            if not (self.accompanying_adult or self.accompanying_kids):
                raise ValueError("select Adult, Kids or both when your family is accompanying you")
            if self.accompanying_adult and self.adult_name is None:
                raise ValueError("adult_name is required when Adult is selected")
            if not self.accompanying_adult and self.adult_name is not None:
                raise ValueError("adult_name must not be sent unless Adult is selected")
            if self.accompanying_kids and not self.kid_names:
                raise ValueError("enter at least one kid's name when Kids is selected")
            if not self.accompanying_kids and (self.kid_names or self.kid_ages):
                raise ValueError("kid_names and kid_ages must not be sent unless Kids is selected")
            if len(self.kid_names) > MAX_ACCOMPANYING_KIDS:
                raise ValueError(f"at most {MAX_ACCOMPANYING_KIDS} kids can accompany you")
            if len(self.kid_ages) != len(self.kid_names):
                raise ValueError("enter an age for every kid: kid_ages must match kid_names one for one")

        if self.food_preference is None and (self.family_attending or FOOD_PREFERENCE_REQUIRED_WHEN_ALONE):
            raise ValueError("food_preference is required when you are attending the event")
        return self

    @property
    def accompanying_guests(self) -> list[tuple[str, GuestType, int | None]]:
        """The party beyond the employee (name, type, age), adult first: these take seats and are listed on
        the pass."""
        adult = [(self.adult_name, GuestType.ADULT, None)] if self.adult_name is not None else []
        return adult + [(name, GuestType.KID, age) for name, age in zip(self.kid_names, self.kid_ages, strict=True)]


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
    attending: Literal[True] = True
    employee_id: str | None
    employee_name: str
    guest_names: list[str] = Field(description="Every accompanying guest: the adult first, then the kids")
    adult_name: str | None
    kid_names: list[str]
    kid_ages: list[int | None] = Field(description="Each kid's age, in the same order as kid_names")
    food_preference: FoodPreference | None
    party_size: int = Field(description="The employee plus their accompanying guests; the pass admits all of them once")
    event: PublicEventRead
    qr_token: str
    qr_svg: str = Field(description="QR code of qr_token as an SVG data URI")
    issued_at: datetime


class AttendanceDeclined(BaseModel):
    """Returned by verification when the employee said they will not attend: recorded, no seat, no pass."""

    registration_id: str
    status: Literal["DECLINED"] = "DECLINED"
    attending: Literal[False] = False
    employee_id: str | None
    employee_name: str
    event: PublicEventRead
    verified_at: datetime


class RegistrationAdminRead(BaseModel):
    """An admin's view of one registration. Contact details are masked; no QR, OTP or encrypted data."""

    registration_id: str
    employee_id: str | None
    employee_name: str
    email_masked: str | None
    mobile_masked: str | None
    attending: bool
    family_attending: bool | None
    guest_names: list[str]
    adult_name: str | None
    kid_names: list[str]
    kid_ages: list[int | None]
    food_preference: FoodPreference | None
    number_of_guests: int
    party_size: int
    status: str
    verified_at: datetime | None
    qr_issued: bool
    qr_issued_at: datetime | None
    checked_in_at: datetime | None
    created_at: datetime


class RegistrationAdminUpdate(_StrictInput):
    """Admin-only correction of one registration's identity and accompanying-family details.

    `email` is deliberately a replacement-only field: responses never disclose the stored full
    contact address, but an admin can supply a corrected address when needed.
    """

    employee_id: EmployeeId
    employee_name: PersonName
    email: Email | None = None
    adult_name: PersonName | None = None
    kid_names: list[PersonName] = Field(default_factory=list, max_length=MAX_ACCOMPANYING_KIDS)
    kid_ages: list[KidAge] = Field(default_factory=list, max_length=MAX_ACCOMPANYING_KIDS)

    @model_validator(mode="after")
    def _guest_details_are_consistent(self) -> "RegistrationAdminUpdate":
        if len(self.kid_ages) != len(self.kid_names):
            raise ValueError("enter an age for every kid: kid_ages must match kid_names one for one")
        return self

    @property
    def accompanying_guests(self) -> list[tuple[str, GuestType, int | None]]:
        adult = [(self.adult_name, GuestType.ADULT, None)] if self.adult_name is not None else []
        return adult + [(name, GuestType.KID, age) for name, age in zip(self.kid_names, self.kid_ages, strict=True)]


class AdminQrPass(BaseModel):
    """A newly generated pass returned only to an authorized admin for immediate download."""

    registration_id: str
    employee_name: str
    qr_svg: str = Field(description="QR code as an SVG data URI; it contains the new opaque pass token")
    issued_at: datetime


class RegistrationAdminPage(BaseModel):
    items: list[RegistrationAdminRead]
    total: int
    limit: int
    offset: int
