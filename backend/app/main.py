from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.router import router as auth_router
from app.modules.events.router import router as events_router
from app.modules.gate.router import router as gate_router
from app.modules.guests.admin_router import router as registrations_admin_router
from app.modules.guests.router import router as guests_router
from app.modules.users.router import router as users_router

API_PREFIX = "/api/v1"

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
    return app


app = create_app()
