"""Self-contained log capture for FastAPI apps.

Drop this package into any FastAPI project and call `install_log_capture(app)`:
every request, and every Python log line emitted while it runs, is stored in
MongoDB for the logs UI. Configure it with LOGS_* environment variables
(see .env.example).
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import Sequence

from fastapi import FastAPI, params

from . import db
from .api import router as logs_router
from .capture import MongoLogHandler, PrintCapture, RequestLogMiddleware
from .config import LogsSettings, get_settings
from .writer import LogWriter

__all__ = ["install_log_capture", "logs_router", "LogsSettings"]


# uvicorn's own loggers do not pass records up to the root logger, so the handler goes on them directly.
SERVER_LOGGERS = ("uvicorn", "uvicorn.access")


def _attach_server_logger_handler(handler: MongoLogHandler) -> list[logging.Logger]:
    attached = []
    for name in SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        if server_logger.propagate:
            continue  # the root handler already sees these (e.g. under gunicorn)
        # Drop a handler left by an earlier install (a reload, or an app built twice) so lines are not stored twice
        for old in [h for h in server_logger.handlers if isinstance(h, MongoLogHandler)]:
            server_logger.removeHandler(old)
        server_logger.addHandler(handler)
        attached.append(server_logger)
    return attached


def install_log_capture(
    app: FastAPI,
    settings: LogsSettings | None = None,
    collection=None,
    include_api: bool = True,
    api_dependencies: Sequence[params.Depends] | None = None,
) -> LogWriter:
    """Wire log capture into `app` and, unless `include_api` is False, mount the
    logs API at `settings.api_prefix`. Returns the writer (handy for tests).

    `api_dependencies` protects the logs API, e.g. [Depends(get_current_user)].
    `collection` overrides the MongoDB collection, e.g. with a mock in tests.
    """
    settings = settings or get_settings()
    app.state.logs_settings = settings
    writer = LogWriter(settings)
    handler = MongoLogHandler(writer, settings)
    server_loggers = _attach_server_logger_handler(handler) if settings.capture_server_logs else []

    if include_api:
        app.include_router(
            logs_router, prefix=settings.api_prefix, dependencies=list(api_dependencies or [])
        )
    app.add_middleware(RequestLogMiddleware, writer=writer, settings=settings)

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        coll = await db.connect(settings, collection)
        await writer.start(coll)
        root = logging.getLogger()
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > handler.level:
            root.setLevel(handler.level)
        stdout = sys.stdout
        if settings.capture_print and not isinstance(stdout, PrintCapture):
            sys.stdout = PrintCapture(stdout)
        try:
            async with original_lifespan(a) as state:
                yield state
        finally:
            if isinstance(sys.stdout, PrintCapture):
                sys.stdout = stdout
            root.removeHandler(handler)
            for server_logger in server_loggers:
                server_logger.removeHandler(handler)
            await writer.stop()
            await db.close()

    app.router.lifespan_context = lifespan
    app.state.log_writer = writer
    return writer
