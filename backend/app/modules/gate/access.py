"""Which events a staff member may run the gate for.

Admins may run any event's gate. Security officers only the events they are assigned to in
`officer_events`; the same scope the events module applies to their reads.
"""

from sqlalchemy.orm import Session

from app.modules.auth.dependencies import ROLE_ADMIN, ROLE_SECURITY_OFFICER, CurrentUser
from app.modules.events.repository import EventRepository

GATE_ROLES = (ROLE_ADMIN, ROLE_SECURITY_OFFICER)


class EventScopePolicy:
    def __init__(self, db: Session) -> None:
        self.events = EventRepository(db)

    def allows(self, user: CurrentUser, event_id: int) -> bool:
        if user.role == ROLE_ADMIN:
            return True
        if user.role == ROLE_SECURITY_OFFICER:
            return self.events.get(event_id, officer_id=user.id) is not None
        return False
