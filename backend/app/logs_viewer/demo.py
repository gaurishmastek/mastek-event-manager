"""Fake log generator for demos. Only used when LOGS_ENABLE_DEMO_DATA=true (or by `python -m app.seed`).

Safe to delete when you move the viewer into a real project: nothing else depends on it
as long as LOGS_ENABLE_DEMO_DATA stays off.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from .models import LogEntry, LogMessage

ROUTES = [
    ("GET", "/", "/", 0.30),
    ("GET", "/items/{item_id}", "/items/{n}", 0.25),
    ("POST", "/items", "/items", 0.10),
    ("PUT", "/items/{item_id}", "/items/{n}", 0.05),
    ("DELETE", "/items/{item_id}", "/items/{n}", 0.03),
    ("GET", "/users/{user_id}", "/users/{n}", 0.12),
    ("POST", "/auth/login", "/auth/login", 0.08),
    ("GET", "/reports/daily", "/reports/daily", 0.07),
]
HOSTS = ["api.example.com", "localhost:8000"]
AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0", "python-httpx/0.27", "PostmanRuntime/7.39"]


def fake_entry(ts: datetime, service: str, environment: str, retention_days: int) -> LogEntry:
    method, route, path_tpl, _ = random.choices(ROUTES, weights=[r[3] for r in ROUTES])[0]
    path = path_tpl.replace("{n}", str(random.randint(1, 400)))
    roll = random.random()
    status = 200 if method != "POST" else 201
    messages: list[tuple[str, str, str | None]] = [("info", f"Handling {method} {path}", None)]
    if roll < 0.04:
        status = 500
        messages.append(("error", "Database query failed: connection reset by peer", "Traceback (most recent call last):\n  ...\nConnectionResetError: [Errno 104] Connection reset by peer"))
    elif roll < 0.05:
        status = 503
        messages.append(("fatal", "Upstream service unavailable, giving up after 3 retries", None))
    elif roll < 0.12:
        status = random.choice([400, 401, 404, 422])
        messages.append(("warning", {400: "Bad request payload", 401: "Invalid or expired token", 404: "Resource not found", 422: "Validation failed for field 'name'"}[status], None))
    elif roll < 0.18:
        messages.append(("warning", "Slow query detected (> 500ms)", None))
    duration = round(random.lognormvariate(3.2, 0.8), 2)
    entry = LogEntry(
        request_id=uuid.uuid4().hex,
        timestamp=ts,
        service=service,
        environment=environment,
        host=random.choice(HOSTS),
        method=method,
        path=path,
        route=route,
        status_code=status,
        duration_ms=duration,
        client_ip=f"10.0.{random.randint(0, 9)}.{random.randint(2, 254)}",
        user_agent=random.choice(AGENTS),
        messages=[
            LogMessage(timestamp=ts + timedelta(milliseconds=i * 3), level=lvl, logger="demo", message=msg, exception=exc)
            for i, (lvl, msg, exc) in enumerate(messages)
        ],
        expires_at=ts + timedelta(days=retention_days) if retention_days > 0 else None,
    )
    return entry.finalize()


def fake_entries(count: int, hours: float, service: str = "fastapi-logs-list", environment: str = "development", retention_days: int = 14) -> list[LogEntry]:
    now = datetime.now(timezone.utc)
    # hours=0 means "right now": spread over the last second or two so rows don't tie.
    spread = hours * 3600 if hours > 0 else 1.5
    stamps = sorted(now - timedelta(seconds=random.uniform(0, spread)) for _ in range(count))
    return [fake_entry(ts, service, environment, retention_days) for ts in stamps]


