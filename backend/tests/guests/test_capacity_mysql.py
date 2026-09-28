"""Concurrency and migration checks that need a real MySQL server (SQLite ignores row locks).

Skipped unless TEST_MYSQL_URL points at an empty, disposable database, e.g.
TEST_MYSQL_URL=mysql+pymysql://root:pw@127.0.0.1:3306/events_test
"""

import os
import threading
from datetime import timedelta

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.db.mixins import utcnow
from app.modules.events.models import Event
from app.modules.guests.models import Registration
from app.modules.guests.schemas import RegistrationCreate
from app.modules.guests.service import EventFullError, GuestRegistrationService
from app.modules.otp.service import OtpService
from tests.guest_fixtures import FakeMailbox, registration_body

MYSQL_URL = os.environ.get("TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="set TEST_MYSQL_URL to run MySQL-only tests")


def _recreate_database() -> None:
    url = make_url(MYSQL_URL)
    server = create_engine(url.set(database=""))
    with server.begin() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS `{url.database}`"))
        connection.execute(text(f"CREATE DATABASE `{url.database}`"))
    server.dispose()


def _alembic() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", MYSQL_URL)
    return config


def test_registration_link_migration_upgrades_and_downgrades_on_mysql():
    _recreate_database()
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "20260928_0003")
    command.upgrade(_alembic(), "head")
    _recreate_database()


@pytest.fixture()
def mysql():
    _recreate_database()
    command.upgrade(_alembic(), "head")
    engine = create_engine(MYSQL_URL, pool_size=20)
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()
        _recreate_database()


def test_concurrent_verifications_cannot_oversell_party_seats(mysql):
    mailbox = FakeMailbox()
    with mysql() as db:
        event = Event(
            title="Diwali Night",
            location="Mumbai",
            starts_at=utcnow() + timedelta(days=5),
            capacity=5,
            max_guests_per_registration=5,
        )
        db.add(event)
        db.commit()
        pending = []
        for n in range(6):
            data = RegistrationCreate(**registration_body(f"guest{n}@example.com", guests=["Plus One"]))
            sent = GuestRegistrationService(db, OtpService(db, mailbox)).register(event.public_id, data, ip=None)
            pending.append((sent.registration.public_id, mailbox.last_code))

    barrier = threading.Barrier(len(pending))
    outcomes: list[str] = []

    def verify(public_id: str, code: str) -> None:
        with mysql() as db:
            service = GuestRegistrationService(db, OtpService(db, mailbox))
            barrier.wait()
            try:
                service.verify(public_id, code)
                outcomes.append("verified")
            except EventFullError:
                outcomes.append("full")

    threads = [threading.Thread(target=verify, args=item) for item in pending]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Parties of two in five seats: exactly two fit, and nobody gets in partially.
    assert sorted(outcomes) == ["full"] * 4 + ["verified"] * 2
    with mysql() as db:
        seats = db.scalar(select(func.sum(1 + Registration.number_of_guests)).where(Registration.status == "VERIFIED"))
    assert seats == 4
