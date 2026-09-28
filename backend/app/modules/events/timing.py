"""When an event's gate accepts scans. Shared by the gate service and the event read model."""

from datetime import datetime, timedelta

from app.core.config import settings


def gate_window_for(starts_at: datetime, ends_at: datetime | None) -> tuple[datetime, datetime]:
    """Naive-UTC (opens, closes): opens a while before the start, closes at the end (or hours after the start)."""
    opens = starts_at - timedelta(minutes=settings.gate_opens_minutes_before_start)
    closes = ends_at or starts_at + timedelta(hours=settings.gate_closes_hours_after_start_if_no_end)
    return opens, closes
