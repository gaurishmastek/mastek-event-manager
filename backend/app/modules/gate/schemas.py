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
    """Enough for the officer to compare against the person in front of them (e.g. a forwarded screenshot)."""

    name: str
    contact: str = Field(description="Masked email, e.g. as•••@example.com")


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
