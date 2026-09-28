"""public registration links, employee registrations and accompanying guests

Events get a random `public_id` (UUID4) for their public registration link, filled in for existing
events, and a `max_guests_per_registration` setting (default 5). Registrations become employee
registrations: `guest_name` is renamed `employee_name` (data kept), and they gain an employee id
(unique per event), `number_of_guests`, and a `registration_guests` child table for the names of
accompanying guests. Existing registrations keep their passes; they count as a party of one.

Revision ID: 20260928_0004
Revises: 20260928_0003
Create Date: 2026-09-28
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20260928_0004"
down_revision = "20260928_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("public_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("max_guests_per_registration", sa.Integer(), nullable=False, server_default="5"))

    bind = op.get_bind()
    events = sa.table("events", sa.column("id", sa.Integer()), sa.column("public_id", sa.String(36)))
    for (event_id,) in bind.execute(sa.select(events.c.id)).all():
        bind.execute(events.update().where(events.c.id == event_id).values(public_id=str(uuid.uuid4())))

    with op.batch_alter_table("events") as batch:
        batch.alter_column("public_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_unique_constraint("uq_events_public_id", ["public_id"])
        batch.create_check_constraint(
            "ck_events_max_guests_range", "max_guests_per_registration >= 0 AND max_guests_per_registration <= 10"
        )

    with op.batch_alter_table("registrations") as batch:
        batch.alter_column(
            "guest_name", new_column_name="employee_name", existing_type=sa.String(length=100), existing_nullable=False
        )
        batch.add_column(sa.Column("employee_id", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("employee_id_normalized", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("number_of_guests", sa.Integer(), nullable=False, server_default="0"))
        batch.create_unique_constraint("uq_registrations_event_employee", ["event_id", "employee_id_normalized"])

    op.create_table(
        "registration_guests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("registrations.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("registration_id", "position", name="uq_registration_guests_position"),
    )
    op.create_index("ix_registration_guests_deleted_at", "registration_guests", ["deleted_at"])


def downgrade() -> None:
    employee_rows = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM registrations WHERE employee_id IS NOT NULL OR number_of_guests > 0")
    )
    if employee_rows:
        raise RuntimeError(
            f"{employee_rows} registrations have an employee id or accompanying guests; downgrading cannot keep them."
        )

    op.drop_index("ix_registration_guests_deleted_at", table_name="registration_guests")
    op.drop_table("registration_guests")

    with op.batch_alter_table("registrations") as batch:
        batch.drop_constraint("uq_registrations_event_employee", type_="unique")
        batch.drop_column("number_of_guests")
        batch.drop_column("employee_id_normalized")
        batch.drop_column("employee_id")
        batch.alter_column(
            "employee_name", new_column_name="guest_name", existing_type=sa.String(length=100), existing_nullable=False
        )

    with op.batch_alter_table("events") as batch:
        batch.drop_constraint("ck_events_max_guests_range", type_="check")
        batch.drop_constraint("uq_events_public_id", type_="unique")
        batch.drop_column("max_guests_per_registration")
        batch.drop_column("public_id")
