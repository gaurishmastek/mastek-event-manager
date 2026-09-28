import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.modules.events.models import DEFAULT_MAX_GUESTS_PER_REGISTRATION, MAX_GUESTS_PER_REGISTRATION_CAP

TITLE_MAX = 200
LOCATION_MAX = 255
DESCRIPTION_MAX = 5000
CAPACITY_MAX = 100_000

# Control characters other than tab/newline/carriage return never belong in user text.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_single_line(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    if _CONTROL_CHARS.search(value) or "\n" in value or "\r" in value:
        raise ValueError("must be a single line of printable text")
    return value


def _clean_multi_line(value: str) -> str:
    value = value.strip()
    if _CONTROL_CHARS.search(value):
        raise ValueError("contains invalid control characters")
    return value


def _to_utc_naive(value: datetime) -> datetime:
    """Require an explicit timezone and store everything as naive UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must include a timezone offset, e.g. 2026-10-20T18:00:00+05:30")
    return value.astimezone(UTC).replace(tzinfo=None)


Title = Annotated[str, Field(min_length=3, max_length=TITLE_MAX), AfterValidator(_clean_single_line)]
Location = Annotated[str, Field(min_length=2, max_length=LOCATION_MAX), AfterValidator(_clean_single_line)]
Description = Annotated[str, Field(max_length=DESCRIPTION_MAX), AfterValidator(_clean_multi_line)]
Capacity = Annotated[int, Field(ge=1, le=CAPACITY_MAX, strict=True)]
MaxGuests = Annotated[int, Field(ge=0, le=MAX_GUESTS_PER_REGISTRATION_CAP, strict=True)]
AwareDatetime = Annotated[datetime, AfterValidator(_to_utc_naive)]


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EventCreate(_StrictInput):
    title: Title
    description: Description | None = None
    location: Location
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    capacity: Capacity
    max_guests_per_registration: MaxGuests = DEFAULT_MAX_GUESTS_PER_REGISTRATION

    @model_validator(mode="after")
    def _check_dates(self) -> "EventCreate":
        if self.ends_at is not None and self.ends_at < self.starts_at:
            raise ValueError("ends_at must not be before starts_at")
        return self


class EventUpdate(_StrictInput):
    """Partial update. Only fields present in the request body are changed."""

    title: Title | None = None
    description: Description | None = None
    location: Location | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    capacity: Capacity | None = None
    max_guests_per_registration: MaxGuests | None = None

    @model_validator(mode="after")
    def _reject_null_required(self) -> "EventUpdate":
        for name in ("title", "location", "starts_at", "capacity", "max_guests_per_registration"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str = Field(description="UUID used in the public registration link /register/{public_id}")
    title: str
    description: str | None
    location: str
    starts_at: datetime
    ends_at: datetime | None
    capacity: int
    max_guests_per_registration: int
    created_at: datetime
    updated_at: datetime
    created_by: int | None
    updated_by: int | None


class EventPage(BaseModel):
    items: list[EventRead]
    total: int
    limit: int
    offset: int
