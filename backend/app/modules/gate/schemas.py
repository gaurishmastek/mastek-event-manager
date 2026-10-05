import enum
from datetime import datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.events.schemas import _clean_single_line
from app.modules.gate.models import RejectionReason

# Pass tokens are URL-safe base64 from secrets.token_urlsafe(32); anything else is rejected before lookup.
PassToken = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{20,128}$")]
GateName = Annotated[str, Field(min_length=1, max_length=50), AfterValidator(_clean_single_line)]
RejectionNote = Annotated[str, Field(min_length=3, max_length=255), AfterValidator(_clean_single_line)]
GuestRowId = Annotated[int, Field(ge=1, le=2_147_483_647)]
# More than any event allows (max_guests_per_registration is at most 10); bounds the request body.
MAX_GUEST_IDS = 20


class Decision(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    token: PassToken
    gate: GateName | None = None


class DecisionRequest(BaseModel):
    """The officer's decision on a scanned pass.

    Approving the first time needs `employee_id_checked` (the officer compared the employee's ID card with the
    registered id) and lists the accompanying guests present; approving again later lists the late guests. Rejecting
    needs a reason, and a note when the reason is OTHER. No client time is accepted: the server stamps every entry.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    token: PassToken
    decision: Decision
    gate: GateName | None = None
    employee_id_checked: bool = False
    guest_ids_entered: list[GuestRowId] = Field(default_factory=list, max_length=MAX_GUEST_IDS)
    reason: RejectionReason | None = None
    note: RejectionNote | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.decision is Decision.APPROVE:
            if self.reason is not None or self.note is not None:
                raise ValueError("an approval cannot carry a rejection reason or note")
            if len(set(self.guest_ids_entered)) != len(self.guest_ids_entered):
                raise ValueError("a guest can only be listed once")
        else:
            if self.reason is None:
                raise ValueError("a rejection needs a reason")
            if self.reason is RejectionReason.OTHER and self.note is None:
                raise ValueError("a note is required when the reason is OTHER")
            if self.employee_id_checked or self.guest_ids_entered:
                raise ValueError("a rejection cannot admit anyone")
        return self


class PartyMember(BaseModel):
    """One accompanying guest on the pass and whether they have come in yet."""

    id: int
    name: str
    type: str | None = Field(None, description="ADULT or KID; null for guests registered before the family questions")
    age: int | None = None
    entered: bool = False
    entered_at: datetime | None = None


class ScannedGuest(BaseModel):
    """Enough for the officer to check the party in front of them against the registration.

    Only ever returned for a pass of the scanned event that is awaiting a decision, admitted or already used.
    """

    name: str = Field(description="The employee's name")
    contact: str = Field(description="Masked email, e.g. as•••@example.com (masked mobile for old registrations)")
    employee_id: str | None = None
    guest_names: list[str] = Field(default_factory=list, description="Accompanying guests, in the order registered")
    party_size: int = Field(1, description="The employee plus their accompanying guests")
    email_masked: str | None = None
    mobile_masked: str | None = None
    employee_entered: bool = Field(False, description="True once the employee's ID has been checked and they are in")
    members: list[PartyMember] = Field(default_factory=list, description="Accompanying guests with their entry state")


class ScanResponse(BaseModel):
    result: str
    message: str
    guest: ScannedGuest | None = None
    checked_in_at: datetime | None = Field(None, description="When the employee entered")
    gate: str | None = Field(None, description="Where the employee entered")
    people_entered: int | None = Field(None, description="Employee plus guests let in so far, when a pass is shown")


class EntryRead(BaseModel):
    guest: ScannedGuest
    checked_in_at: datetime
    gate: str | None
    officer_id: int
    people_entered: int = Field(1, description="Employee plus the accompanying guests let in so far")


class EntryPage(BaseModel):
    items: list[EntryRead]
    total: int
    limit: int
    offset: int
