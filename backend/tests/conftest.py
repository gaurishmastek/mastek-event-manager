import os
from collections.abc import Iterator

# Tests never touch MySQL; point settings at SQLite before the app is imported.
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.modules.auth.dependencies import CurrentUser, get_current_user

pytest_plugins = ["tests.guest_fixtures"]


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def login_as():
    """Act as a user with the given role for the rest of the test."""

    def _login(role: str, user_id: int = 1) -> CurrentUser:
        user = CurrentUser(id=user_id, role=role)
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    return _login
