from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.events.schemas import _clean_single_line

# Pass tokens are URL-safe base64 from secrets.token_urlsafe(32); anything else is rejected before lookup.
PassToken = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{20,128}$")]
GateName = Annotated[str, Field(min_length=1, max_length=50), AfterValidator(_clean_single_line)]


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    token: PassToken
    gate: GateName | None = None


class ScannedGuest(BaseModel):
    """Enough for the officer to check the party in front of them against the registration.

    Only ever returned for a pass of the scanned event that is admitted or already used.
    """

    name: str = Field(description="The employee's name")
    contact: str = Field(description="Masked email, e.g. as•••@example.com (masked mobile for old registrations)")
    employee_id: str | None = None
    guest_names: list[str] = Field(default_factory=list, description="Accompanying guests, in the order registered")
    party_size: int = Field(1, description="The employee plus their accompanying guests")
    email_masked: str | None = None
    mobile_masked: str | None = None


class ScanResponse(BaseModel):
    result: str
    message: str
    guest: ScannedGuest | None = None
    checked_in_at: datetime | None = None
    gate: str | None = None


class EntryRead(BaseModel):
    guest: ScannedGuest
    checked_in_at: datetime
    gate: str | None
    officer_id: int


class EntryPage(BaseModel):
    items: list[EntryRead]
    total: int
    limit: int
    offset: int
