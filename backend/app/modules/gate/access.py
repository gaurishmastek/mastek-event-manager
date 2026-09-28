"""Which events a staff member may run the gate for.

Security officers must only scan for events they are assigned to. Officer-to-event
assignment belongs to the auth module, which has not landed yet, so until it is wired in
here officers are denied and only admins can scan. Replace `EventScopePolicy.allows`
with a lookup of the officer's assignments when it lands.
"""

from app.modules.auth.dependencies import CurrentUser

ADMIN_ROLE = "admin"
GATE_ROLES = (ADMIN_ROLE, "security")


class EventScopePolicy:
    def allows(self, user: CurrentUser, event_id: int) -> bool:
        return user.role == ADMIN_ROLE


def get_event_scope_policy() -> EventScopePolicy:
    return EventScopePolicy()
