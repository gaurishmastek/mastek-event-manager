"""Imports every model so Alembic and table creation see the full metadata."""

from app.db.base import Base
from app.modules.events.models import Event, OfficerEvent
from app.modules.gate.models import CheckIn, ScanAttempt
from app.modules.guests.models import Registration
from app.modules.otp.models import OtpChallenge
from app.modules.users.models import User

__all__ = ["Base", "CheckIn", "Event", "OfficerEvent", "OtpChallenge", "Registration", "ScanAttempt", "User"]
