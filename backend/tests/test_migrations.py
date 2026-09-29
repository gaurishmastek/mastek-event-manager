import re

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from alembic import command
from app.db.models import Base


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []

    command.downgrade(config, "base")


def test_registration_link_migration_keeps_existing_events_and_passes(tmp_path):
    url = f"sqlite:///{tmp_path / 'data.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "20260928_0003")
    engine = create_engine(url)
    with engine.begin() as connection:
        for event_id in (1, 2):
            connection.execute(
                text(
                    "INSERT INTO events (id, title, location, starts_at, capacity, created_at, updated_at) "
                    "VALUES (:id, 'Diwali', 'Mumbai', '2030-10-20 12:00:00', 50, '2026-09-28', '2026-09-28')"
                ),
                {"id": event_id},
            )
        connection.execute(
            text(
                "INSERT INTO registrations (public_id, event_id, guest_name, email_hash, status, consent_at, "
                "qr_token_hash, created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000001', 1, "
                "'Asha Patil', :email, 'VERIFIED', '2026-09-28', :qr, '2026-09-28', '2026-09-28')"
            ),
            {"email": "e" * 64, "qr": "q" * 64},
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        public_ids = connection.execute(text("SELECT public_id FROM events ORDER BY id")).scalars().all()
        registration = connection.execute(
            text("SELECT employee_name, employee_id, number_of_guests, qr_token_hash, status FROM registrations")
        ).one()
        max_guests = connection.execute(text("SELECT max_guests_per_registration FROM events")).scalars().all()
    assert len(set(public_ids)) == 2
    assert all(
        re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", p) for p in public_ids
    )
    assert tuple(registration) == ("Asha Patil", None, 0, "q" * 64, "VERIFIED")
    assert max_guests == [5, 5]

    # Only pre-workflow data exists, so downgrading keeps it.
    command.downgrade(config, "20260928_0003")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT guest_name FROM registrations")).scalar_one() == "Asha Patil"
    engine.dispose()


def test_attendance_migration_keeps_existing_registrations_as_attending(tmp_path):
    url = f"sqlite:///{tmp_path / 'attendance.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "20260928_0004")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO events (id, public_id, title, location, starts_at, capacity, created_at, updated_at) "
                "VALUES (1, '00000000-0000-4000-8000-00000000000e', 'Diwali', 'Mumbai', '2030-10-20 12:00:00', 50, "
                "'2026-09-28', '2026-09-28')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO registrations (id, public_id, event_id, employee_name, number_of_guests, status, "
                "consent_at, created_at, updated_at) VALUES (1, '00000000-0000-4000-8000-000000000001', 1, "
                "'Asha Patil', 1, 'VERIFIED', '2026-09-28', '2026-09-28', '2026-09-28')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO registration_guests (registration_id, name, position, created_at, updated_at) "
                "VALUES (1, 'Ravi Patil', 0, '2026-09-28', '2026-09-28')"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        registration = connection.execute(
            text("SELECT attending, family_attending, food_preference, number_of_guests FROM registrations")
        ).one()
        guest = connection.execute(text("SELECT name, guest_type FROM registration_guests")).one()
    assert tuple(registration) == (1, None, None, 1)
    assert tuple(guest) == ("Ravi Patil", None)

    # No declines exist, so downgrading keeps everything else.
    command.downgrade(config, "20260928_0004")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT employee_name FROM registrations")).scalar_one() == "Asha Patil"
    engine.dispose()
