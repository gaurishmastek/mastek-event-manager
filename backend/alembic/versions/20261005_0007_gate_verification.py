"""officer verification at the gate: per-guest entries and entry rejections

`check_ins` still records the employee's entry. Accompanying guests who enter on the shared pass, possibly
later, get a `guest_entries` row each (unique per guest, so nobody enters twice). `entry_rejections` records
every refusal with its reason; refusing someone leaves the registration unchanged.

Revision ID: 20261005_0007
Revises: 20260930_0006
Create Date: 2026-10-05
"""

import sqlalchemy as sa

from alembic import op

revision = "20261005_0007"
down_revision = "20260930_0006"
branch_labels = None
depends_on = None


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "guest_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("check_in_id", sa.Integer(), sa.ForeignKey("check_ins.id"), nullable=False),
        sa.Column("registration_guest_id", sa.Integer(), sa.ForeignKey("registration_guests.id"), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=False),
        sa.Column("gate", sa.String(length=50), nullable=True),
        sa.Column("entered_at", sa.DateTime(), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint("registration_guest_id", name="uq_guest_entries_registration_guest_id"),
    )
    op.create_index("ix_guest_entries_check_in_id", "guest_entries", ["check_in_id"])
    op.create_index("ix_guest_entries_deleted_at", "guest_entries", ["deleted_at"])

    op.create_table(
        "entry_rejections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("registrations.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=False),
        sa.Column("gate", sa.String(length=50), nullable=True),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("reason IN ('ID_MISMATCH', 'ID_NOT_PRESENTED', 'OTHER')", name="ck_entry_rejections_reason"),
    )
    op.create_index("ix_entry_rejections_event_created_at", "entry_rejections", ["event_id", "created_at"])
    op.create_index("ix_entry_rejections_deleted_at", "entry_rejections", ["deleted_at"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("guest_entries", "entry_rejections"):
        rows = bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608 - fixed table names
        if rows:
            raise RuntimeError(f"{table} has {rows} rows; downgrading would lose them.")

    op.drop_table("entry_rejections")
    op.drop_table("guest_entries")
