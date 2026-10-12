import logging

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import ENV_FILE, get_settings
from app.core.logs_auth import require_logs_access
from app.logs_viewer import LogsSettings, install_log_capture
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.router import router as auth_router
from app.modules.events.router import router as events_router
from app.modules.gate.router import router as gate_router
from app.modules.guests.admin_router import router as registrations_admin_router
from app.modules.guests.router import router as guests_router
from app.modules.users.router import router as users_router

API_PREFIX = "/api/v1"

logger = logging.getLogger(__name__)

# Routes reachable without a token. Everything else is behind authentication by default,
# and tests fail if a new route is exposed without being added here on purpose.
PUBLIC_ROUTES = frozenset(
    {
        ("GET", "/health"),
        ("POST", f"{API_PREFIX}/auth/login"),
        ("POST", f"{API_PREFIX}/auth/login/verify"),
        ("POST", f"{API_PREFIX}/auth/officer/otp"),
        ("POST", f"{API_PREFIX}/auth/officer/verify"),
        # Employee self-registration from an event's public link: no accounts, the email is proved with an OTP.
        ("GET", f"{API_PREFIX}/public/events/{{event_public_id}}"),
        ("POST", f"{API_PREFIX}/public/events/{{event_public_id}}/registrations"),
        ("POST", f"{API_PREFIX}/public/registrations/{{registration_id}}/otp"),
        ("POST", f"{API_PREFIX}/public/registrations/{{registration_id}}/verify"),
    }
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # The gate scanner needs the camera on our own origin only; nothing may use it from a frame or another origin.
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
}


def create_app() -> FastAPI:
    settings = get_settings()
    # Interactive API docs are only exposed outside production.
    docs_url = None if settings.is_production else "/docs"
    app = FastAPI(
        title=settings.app_name,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response

    # Error responses are otherwise silent, so the Logs page shows no message for them. Log why each one was
    # refused (never the request values, which can hold personal data), then answer exactly as before.
    @app.exception_handler(StarletteHTTPException)
    async def log_http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code != 404:
            logger.warning("%s: %s", exc.status_code, exc.detail)
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def log_validation_error(request: Request, exc: RequestValidationError) -> Response:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        logger.warning("422: invalid request (%s)", problems)
        return await request_validation_exception_handler(request, exc)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(guests_router, prefix=API_PREFIX)
    authenticated = [Depends(get_current_user)]
    app.include_router(users_router, prefix=API_PREFIX, dependencies=authenticated)
    app.include_router(events_router, prefix=API_PREFIX, dependencies=authenticated)
    app.include_router(registrations_admin_router, prefix=API_PREFIX, dependencies=authenticated)
    app.include_router(gate_router, prefix=API_PREFIX, dependencies=authenticated)

    # Request logs for the admin Logs page, stored in MongoDB. Off until LOGS_MONGODB_URL is set, so tests and
    # setups without MongoDB are unaffected. Read from the same .env file as the other settings. print() output is never
    # stored: EMAIL_PROVIDER=console prints OTP emails, codes included.
    logs_settings = LogsSettings(_env_file=ENV_FILE, api_prefix=f"{API_PREFIX}/logs", capture_print=False)
    if "mongodb_url" in logs_settings.model_fields_set and logs_settings.mongodb_url.strip():
        install_log_capture(app, settings=logs_settings, api_dependencies=[Depends(require_logs_access)])
    else:
        # Without this the Logs page only sees 404s from /api/v1/logs, with no hint why.
        logger.warning("Request logs are off: set LOGS_MONGODB_URL in backend/.env (see docs/LOGS_VIEWER.md)")
    return app


app = create_app()
