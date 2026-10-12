import logging
import time
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_db
from app.logs_viewer import db as logs_db
from app.main import API_PREFIX, PUBLIC_ROUTES, app, create_app
from app.modules.users.models import Role, User
from tests.conftest import make_user

LOGS_API = f"{API_PREFIX}/logs"


class PymongoLikeCollection:
    """A mongomock-motor collection that behaves like pymongo's AsyncCollection, where aggregate() is a coroutine."""

    def __init__(self, inner):
        self._inner = inner

    async def aggregate(self, pipeline, *args, **kwargs):
        return self._inner.aggregate(pipeline, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def collection(monkeypatch: pytest.MonkeyPatch) -> PymongoLikeCollection:
    fake = PymongoLikeCollection(AsyncMongoMockClient()["logs"]["entries"])
    connect = logs_db.connect
    monkeypatch.setattr(logs_db, "connect", lambda settings, collection=None: connect(settings, fake))
    return fake


@pytest.fixture
def logs_app(monkeypatch: pytest.MonkeyPatch, collection, db: Session) -> Iterator[FastAPI]:
    monkeypatch.setenv("LOGS_MONGODB_URL", "mongodb://logs.test:27017")
    monkeypatch.setenv("LOGS_FLUSH_INTERVAL_SECONDS", "0.05")
    logs_app = create_app()
    logs_app.dependency_overrides[get_db] = lambda: db
    yield logs_app


@pytest.fixture
def logs_client(logs_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(logs_app) as client:
        yield client


def bearer(user: User) -> str:
    token, _ = create_access_token(user.id, user.role.value, user.session_version)
    return token


def _has_logs_api(application: FastAPI) -> bool:
    return any(getattr(route, "path", "").startswith(LOGS_API) for route in application.routes)


def test_logs_are_off_until_a_mongodb_url_is_set(monkeypatch: pytest.MonkeyPatch):
    assert not _has_logs_api(app)
    # A copied .env.example leaves the URL blank, which also means off.
    monkeypatch.setenv("LOGS_MONGODB_URL", "")
    assert not _has_logs_api(create_app())


def test_every_logs_route_requires_authentication(logs_app: FastAPI, logs_client: TestClient):
    logs_routes = [
        (method, path)
        for path, operations in logs_app.openapi()["paths"].items()
        if path.startswith(LOGS_API)
        for method in operations
    ]
    assert logs_routes
    for method, path in logs_routes:
        assert (method.upper(), path) not in PUBLIC_ROUTES
        response = logs_client.request(method, path.replace("{log_id}", "abc"))
        assert response.status_code == 401, f"{method} {path} is reachable without a token"


def test_only_admins_can_read_logs(logs_client: TestClient, db: Session):
    admin = make_user(db, "admin@example.com", Role.ADMIN)
    officer = make_user(db, "officer@example.com", Role.SECURITY_OFFICER)

    response = logs_client.get(LOGS_API, headers={"Authorization": f"Bearer {bearer(officer)}"})
    assert response.status_code == 403

    response = logs_client.get(LOGS_API, headers={"Authorization": f"Bearer {bearer(admin)}"})
    assert response.status_code == 200, response.text
    assert "items" in response.json()


def test_token_query_parameter_works_for_downloads(logs_client: TestClient, db: Session):
    admin = make_user(db, "admin@example.com", Role.ADMIN)

    response = logs_client.get(f"{LOGS_API}/export", params={"format": "csv", "token": bearer(admin)})
    assert response.status_code == 200, response.text

    response = logs_client.get(f"{LOGS_API}/export", params={"format": "csv", "token": "not-a-token"})
    assert response.status_code == 401


def test_requests_are_recorded_but_logs_api_calls_are_not(logs_client: TestClient, db: Session):
    admin = make_user(db, "admin@example.com", Role.ADMIN)
    headers = {"Authorization": f"Bearer {bearer(admin)}"}
    logs_client.get("/health")

    deadline = time.monotonic() + 3
    paths: list[str] = []
    while time.monotonic() < deadline:
        items = logs_client.get(LOGS_API, headers=headers).json()["items"]
        paths = [item["path"] for item in items if item["type"] == "request"]
        if "/health" in paths:
            break
        time.sleep(0.05)
    assert "/health" in paths
    assert not any(path.startswith(LOGS_API) for path in paths)


def test_printed_output_is_not_stored(logs_app: FastAPI):
    # EMAIL_PROVIDER=console prints OTP emails, codes included; they must never reach the logs database.
    assert logs_app.state.logs_settings.capture_print is False


def test_refused_requests_log_why(logs_client: TestClient, db: Session):
    admin = make_user(db, "admin@example.com", Role.ADMIN)
    headers = {"Authorization": f"Bearer {bearer(admin)}"}
    logs_client.get(f"{API_PREFIX}/events")  # no token: 401
    logs_client.get(f"{API_PREFIX}/events", params={"limit": "x"}, headers=headers)  # 422

    deadline = time.monotonic() + 3
    messages: list[str] = []
    while time.monotonic() < deadline:
        items = logs_client.get(LOGS_API, headers=headers).json()["items"]
        messages = [m["message"] for item in items for m in item["messages"]]
        if len(messages) >= 2:
            break
        time.sleep(0.05)
    assert "401: Not authenticated" in messages
    assert any(m.startswith("422: invalid request") and "query.limit" in m for m in messages)


def test_successful_actions_log_a_message(logs_client: TestClient, db: Session):
    admin = make_user(db, "admin@example.com", Role.ADMIN)
    headers = {"Authorization": f"Bearer {bearer(admin)}"}
    logs_client.post(
        f"{API_PREFIX}/users",
        json={"email": "officer@example.com", "full_name": "Officer", "role": "security_officer"},
        headers=headers,
    )

    deadline = time.monotonic() + 3
    messages: list[str] = []
    while time.monotonic() < deadline:
        items = logs_client.get(LOGS_API, headers=headers).json()["items"]
        messages = [m["message"] for item in items for m in item["messages"]]
        if any(m.startswith("User ") for m in messages):
            break
        time.sleep(0.05)
    assert any(m.startswith("User ") and "(security_officer) created by user" in m for m in messages), messages
    assert not any("officer@example.com" in m for m in messages)


def test_server_access_lines_attach_to_their_request(logs_app: FastAPI, logs_client: TestClient, db: Session):
    access = logging.getLogger("uvicorn.access")

    @logs_app.get("/_access-demo")
    def access_demo() -> dict[str, str]:
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/_access-demo", "1.1", 200)
        return {}

    admin = make_user(db, "admin@example.com", Role.ADMIN)
    headers = {"Authorization": f"Bearer {bearer(admin)}"}
    logs_client.get("/_access-demo")
    # Outside any recorded request (the logs page's own polling) an access line must not create an entry.
    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/api/v1/logs", "1.1", 200)

    deadline = time.monotonic() + 3
    items: list[dict] = []
    while time.monotonic() < deadline:
        items = logs_client.get(LOGS_API, headers=headers).json()["items"]
        if any(item.get("path") == "/_access-demo" for item in items):
            break
        time.sleep(0.05)
    entry = next(item for item in items if item.get("path") == "/_access-demo")
    assert [m["message"] for m in entry["messages"]] == ['127.0.0.1:5000 - "GET /_access-demo HTTP/1.1" 200 OK']
    assert not any(
        "127.0.0.1:5000" in m["message"] for item in items if item["type"] == "app" for m in item["messages"]
    )


def test_server_logs_can_be_switched_off(monkeypatch: pytest.MonkeyPatch, logs_app: FastAPI):
    monkeypatch.setenv("LOGS_CAPTURE_SERVER_LOGS", "false")
    assert create_app().state.logs_settings.capture_server_logs is False
