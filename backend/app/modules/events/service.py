# Postponed annotations: the `list` method would otherwise shadow the builtin in later signatures.
from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.db.mixins import utcnow
from app.modules.auth.dependencies import ROLE_SECURITY_OFFICER, CurrentUser
from app.modules.events.models import Event, OfficerEvent
from app.modules.events.repository import EventRepository
from app.modules.events.schemas import EventCreate, EventUpdate


def _officer_scope(viewer: CurrentUser | None) -> int | None:
    return viewer.id if viewer is not None and viewer.role == ROLE_SECURITY_OFFICER else None


class EventNotFoundError(Exception):
    pass


class EventValidationError(Exception):
    pass


class EventService:
    def __init__(self, repo: EventRepository) -> None:
        self.repo = repo

    def create(self, data: EventCreate, *, actor_id: int) -> Event:
        if data.starts_at <= utcnow():
            raise EventValidationError("starts_at must be in the future")
        event = Event(**data.model_dump(), created_by=actor_id, updated_by=actor_id)
        return self.repo.add(event)

    def get(self, event_id: int, *, viewer: CurrentUser | None = None) -> Event:
        """Fetch a live event. With a `viewer`, officers get 404 for events they are not assigned to."""
        event = self.repo.get(event_id, officer_id=_officer_scope(viewer))
        if event is None:
            raise EventNotFoundError
        return event

    def list(
        self, *, viewer: CurrentUser, limit: int, offset: int, search: str | None, upcoming: bool
    ) -> tuple[list[Event], int]:
        return self.repo.list(
            limit=limit,
            offset=offset,
            search=search,
            starts_after=utcnow() if upcoming else None,
            officer_id=_officer_scope(viewer),
        )

    def update(self, event_id: int, data: EventUpdate, *, actor_id: int) -> Event:
        event = self.get(event_id)
        changes = data.model_dump(exclude_unset=True)

        starts_at: datetime = changes.get("starts_at", event.starts_at)
        ends_at: datetime | None = changes.get("ends_at", event.ends_at)
        if ends_at is not None and ends_at < starts_at:
            raise EventValidationError("ends_at must not be before starts_at")
        if "starts_at" in changes and starts_at <= utcnow():
            raise EventValidationError("starts_at must be in the future")

        for field, value in changes.items():
            setattr(event, field, value)
        event.updated_by = actor_id
        return self.repo.save(event)

    def delete(self, event_id: int, *, actor_id: int) -> None:
        event = self.get(event_id)
        now = utcnow()
        event.deleted_at = now
        event.deleted_by = actor_id
        event.updated_at = now
        event.updated_by = actor_id
        self.repo.save(event)

    def list_officer_ids(self, event_id: int) -> list[int]:
        self.get(event_id)
        return self.repo.list_officer_ids(event_id)

    def assign_officer(self, event_id: int, officer_id: int, *, actor_id: int) -> None:
        """Assign a security officer. The caller checks officer_id is an active security officer."""
        self.get(event_id)
        assignment = self.repo.get_assignment(event_id, officer_id)
        if assignment is None:
            try:
                self.repo.add(
                    OfficerEvent(event_id=event_id, officer_id=officer_id, created_by=actor_id, updated_by=actor_id)
                )
                return
            except IntegrityError:
                # A concurrent request created the same assignment first (unique event/officer pair).
                self.repo.db.rollback()
                assignment = self.repo.get_assignment(event_id, officer_id)
                if assignment is None:
                    raise
        if assignment.deleted_at is not None:
            assignment.deleted_at = None
            assignment.deleted_by = None
            assignment.updated_by = actor_id
            self.repo.save(assignment)

    def unassign_officer(self, event_id: int, officer_id: int, *, actor_id: int) -> None:
        self.get(event_id)
        assignment = self.repo.get_assignment(event_id, officer_id)
        if assignment is None or assignment.deleted_at is not None:
            raise EventNotFoundError
        assignment.deleted_at = utcnow()
        assignment.deleted_by = actor_id
        assignment.updated_by = actor_id
        self.repo.save(assignment)
