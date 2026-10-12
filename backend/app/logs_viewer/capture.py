import logging
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import LogsSettings
from .models import LogEntry, LogMessage, level_from_python
from .writer import LogWriter

# The entry for the request currently being handled, so log lines emitted
# inside it are attached to that request (like Vercel's "Messages" column).
current_entry: ContextVar[LogEntry | None] = ContextVar("logs_viewer_entry", default=None)

# Loggers whose output is never stored: our own internals and the MongoDB driver.
IGNORED_LOGGER_PREFIXES = ("logs_viewer.internal", "pymongo")
ACCESS_LOGGER = "uvicorn.access"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_at(settings: LogsSettings, ts: datetime) -> datetime | None:
    if settings.retention_days > 0:
        return ts + timedelta(days=settings.retention_days)
    return None


def _access_message(record: logging.LogRecord) -> str:
    """uvicorn prints 'ADDR - "GET /x HTTP/1.1" 200 OK'; the 'OK' is added by its console formatter, so add it here."""
    message = record.getMessage()
    try:
        return f"{message} {HTTPStatus(int(record.args[4])).phrase}"  # type: ignore[index]
    except (TypeError, ValueError, IndexError):
        return message


class MongoLogHandler(logging.Handler):
    """Captures Python log records. Inside a request they are added to that
    request's entry; outside a request each becomes its own "app" entry."""

    def __init__(self, writer: LogWriter, settings: LogsSettings):
        super().__init__(level=settings.capture_level)
        self.writer = writer
        self.settings = settings

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(IGNORED_LOGGER_PREFIXES):
            return
        is_access = record.name == ACCESS_LOGGER
        if is_access and (not self.settings.capture_server_logs or current_entry.get() is None):
            # Access lines belong on their request. Outside one they are the logs API's own polling: skip them.
            return
        try:
            exception = None
            if record.exc_info and record.exc_info[0] is not None:
                exception = "".join(traceback.format_exception(*record.exc_info))
            message = LogMessage(
                timestamp=datetime.fromtimestamp(record.created, timezone.utc),
                level=level_from_python(record.levelno),
                logger=record.name,
                message=_access_message(record) if is_access else record.getMessage(),
                exception=exception,
            )
            entry = current_entry.get()
            if entry is not None:
                entry.messages.append(message)
                return
            standalone = LogEntry(
                request_id=uuid.uuid4().hex,
                type="app",
                timestamp=message.timestamp,
                service=self.settings.service_name,
                environment=self.settings.environment,
                messages=[message],
                expires_at=_expires_at(self.settings, message.timestamp),
            ).finalize()
            self.writer.submit(standalone)
        except Exception:
            self.handleError(record)


class PrintCapture:
    """Wraps sys.stdout so print() output inside a request is also attached to
    that request as "info" messages. Everything is still printed as before."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text: str) -> int:
        entry = current_entry.get()
        if entry is not None and text:
            buffer = entry._print_buffer + text
            *lines, entry._print_buffer = buffer.split("\n")
            for line in lines:
                if line.strip():
                    entry.messages.append(
                        LogMessage(timestamp=_now(), level="info", logger="print", message=line)
                    )
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _flush_print_buffer(entry: LogEntry) -> None:
    if entry._print_buffer.strip():
        entry.messages.append(
            LogMessage(timestamp=_now(), level="info", logger="print", message=entry._print_buffer)
        )
    entry._print_buffer = ""


class RequestLogMiddleware:
    """ASGI middleware that records one entry per HTTP request."""

    def __init__(self, app: ASGIApp, writer: LogWriter, settings: LogsSettings):
        self.app = app
        self.writer = writer
        self.settings = settings
        self.logger = logging.getLogger("logs_viewer.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._excluded(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        started_at = _now()
        entry = LogEntry(
            request_id=headers.get("x-request-id") or uuid.uuid4().hex,
            timestamp=started_at,
            service=self.settings.service_name,
            environment=self.settings.environment,
            host=headers.get("host"),
            method=scope["method"],
            path=scope["path"],
            query=scope.get("query_string", b"").decode("latin-1") or None,
            client_ip=scope["client"][0] if scope.get("client") else None,
            user_agent=headers.get("user-agent"),
            expires_at=_expires_at(self.settings, started_at),
        )
        token = current_entry.set(entry)
        start = perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                entry.status_code = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", entry.request_id.encode("latin-1")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            if entry.status_code is None:
                entry.status_code = 500
            self.logger.exception("Unhandled error on %s %s", entry.method, entry.path)
            raise
        finally:
            entry.duration_ms = round((perf_counter() - start) * 1000, 2)
            route = scope.get("route")
            entry.route = getattr(route, "path", None)
            current_entry.reset(token)
            _flush_print_buffer(entry)
            self.writer.submit(entry.finalize())

    def _excluded(self, path: str) -> bool:
        return any(path == p or path.startswith(p.rstrip("/") + "/") for p in self.settings.excluded_paths)
