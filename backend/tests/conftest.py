import os

# Settings are read at import time, so the test environment is set before the app loads.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.pop("CORS_ORIGINS", None)

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.auth.dependencies import get_current_user  # noqa: E402
from app.modules.users.models import Role, User  # noqa: E402
from app.modules.users.schemas import UserCreate  # noqa: E402
from app.modules.users.service import create_user  # noqa: E402

PASSWORD = "Correct-horse-42"

pytest_plugins = ["tests.guest_fixtures"]


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_user(db: Session, email: str, role: Role) -> User:
    return create_user(db, UserCreate(email=email, full_name=email.split("@")[0], password=PASSWORD, role=role))


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    response = login(client, email)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(db: Session) -> User:
    return make_user(db, "admin@example.com", Role.ADMIN)


@pytest.fixture
def officer(db: Session) -> User:
    return make_user(db, "officer@example.com", Role.SECURITY_OFFICER)


@pytest.fixture
def admin_headers(client: TestClient, admin: User) -> dict[str, str]:
    return auth_headers(client, admin.email)


@pytest.fixture
def officer_headers(client: TestClient, officer: User) -> dict[str, str]:
    return auth_headers(client, officer.email)


@pytest.fixture
def db_session(db: Session) -> Session:
    return db


@pytest.fixture
def login_as(db: Session):
    """Act as a user with the given role for the rest of the test, skipping the login round trip.

    Valid roles get a real stored user (created on first use); anything else gets an unsaved user,
    which is enough to prove the role checks reject it.
    """

    def _login(role: str, user_id: int = 1) -> User:
        if role in Role.__members__.values():
            user = db.get(User, user_id)
            if user is None:
                user = User(
                    id=user_id,
                    email=f"user{user_id}@example.com",
                    full_name=f"User {user_id}",
                    password_hash=hash_password(PASSWORD),
                    role=Role(role),
                )
                db.add(user)
            user.role = Role(role)
            db.commit()
        else:
            user = User(id=user_id, email=f"user{user_id}@example.com", role=role, is_active=True)
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    return _login
