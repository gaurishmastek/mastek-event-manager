from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr

Level = Literal["debug", "info", "warning", "error", "fatal"]

LEVEL_ORDER: dict[str, int] = {"debug": 10, "info": 20, "warning": 30, "error": 40, "fatal": 50}


def level_from_python(levelno: int) -> Level:
    if levelno >= 50:
        return "fatal"
    if levelno >= 40:
        return "error"
    if levelno >= 30:
        return "warning"
    if levelno >= 20:
        return "info"
    return "debug"


def level_from_status(status_code: int | None) -> Level:
    if status_code is None or status_code >= 500:
        return "error"
    if status_code >= 400:
        return "warning"
    return "info"


class LogMessage(BaseModel):
    """One application log line emitted while handling a request."""

    timestamp: datetime
    level: Level
    logger: str
    message: str
    exception: str | None = None


class LogEntry(BaseModel):
    """One document in MongoDB: a request (or a log line outside any request)
    with every message logged while it ran, like a row in Vercel's Logs table."""

    request_id: str
    type: Literal["request", "app"] = "request"
    timestamp: datetime
    service: str
    environment: str
    host: str | None = None

    method: str | None = None
    path: str | None = None
    route: str | None = None
    query: str | None = None
    status_code: int | None = None
    duration_ms: float | None = None
    client_ip: str | None = None
    user_agent: str | None = None

    # Highest level seen, plus every distinct level, for the sidebar filters
    level: Level = "info"
    levels: list[Level] = Field(default_factory=list)
    messages: list[LogMessage] = Field(default_factory=list)

    expires_at: datetime | None = None

    # Partial print() line waiting for its newline
    _print_buffer: str = PrivateAttr(default="")

    def finalize(self) -> "LogEntry":
        levels = {m.level for m in self.messages}
        if self.type == "request":
            levels.add(level_from_status(self.status_code))
        ordered = sorted(levels, key=LEVEL_ORDER.__getitem__)
        self.levels = ordered
        self.level = ordered[-1] if ordered else "info"
        return self
