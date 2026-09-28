# Postponed annotations: the `list` method would otherwise shadow the builtin in later signatures.
from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.events.models import Event, OfficerEvent

Row = TypeVar("Row", Event, OfficerEvent)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _visible(officer_id: int | None) -> list[ColumnElement[bool]]:
    """Base filter for reads: hide soft-deleted rows and, for an officer, unassigned events.

    Scope is applied in the query itself so an officer can never reach another event by ID.
    """
    conditions = [Event.deleted_at.is_(None)]
    if officer_id is not None:
        assigned = select(OfficerEvent.event_id).where(
            OfficerEvent.officer_id == officer_id, OfficerEvent.deleted_at.is_(None)
        )
        conditions.append(Event.id.in_(assigned))
    return conditions


class EventRepository:
    """Data access for events. Soft-deleted rows are invisible to every read.

    Pass `officer_id` to restrict reads to the events that officer is assigned to.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, event_id: int, *, officer_id: int | None = None) -> Event | None:
        stmt = select(Event).where(Event.id == event_id, *_visible(officer_id))
        return self.db.scalars(stmt).first()

    def get_by_public_id(self, public_id: str) -> Event | None:
        stmt = select(Event).where(Event.public_id == public_id, Event.deleted_at.is_(None))
        return self.db.scalars(stmt).first()

    def get_for_update(self, event_id: int) -> Event | None:
        """Lock the event row until the transaction ends.

        Anything that must respect capacity (e.g. guest registration) should take this
        lock before counting seats, so concurrent requests cannot overbook the event.
        """
        stmt = select(Event).where(Event.id == event_id, Event.deleted_at.is_(None)).with_for_update()
        return self.db.scalars(stmt).first()

    def list(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None = None,
        starts_after: datetime | None = None,
        officer_id: int | None = None,
    ) -> tuple[list[Event], int]:
        conditions = _visible(officer_id)
        if search:
            conditions.append(Event.title.ilike(f"%{_escape_like(search)}%", escape="\\"))
        if starts_after is not None:
            conditions.append(Event.starts_at >= starts_after)

        total = self.db.scalar(select(func.count()).select_from(Event).where(*conditions)) or 0
        stmt = select(Event).where(*conditions).order_by(Event.starts_at, Event.id).limit(limit).offset(offset)
        return list(self.db.scalars(stmt)), total

    def add(self, row: Row) -> Row:
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def save(self, row: Row) -> Row:
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_assignment(self, event_id: int, officer_id: int) -> OfficerEvent | None:
        stmt = select(OfficerEvent).where(OfficerEvent.event_id == event_id, OfficerEvent.officer_id == officer_id)
        return self.db.scalars(stmt).first()

    def list_officer_ids(self, event_id: int) -> list[int]:
        stmt = (
            select(OfficerEvent.officer_id)
            .where(OfficerEvent.event_id == event_id, OfficerEvent.deleted_at.is_(None))
            .order_by(OfficerEvent.officer_id)
        )
        return list(self.db.scalars(stmt))
