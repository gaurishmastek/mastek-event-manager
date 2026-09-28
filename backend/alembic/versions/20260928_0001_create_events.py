"""create events and officer_events tables

Revision ID: 20260928_0001
Revises: 20260928_0000
Create Date: 2026-09-28
"""

import sqlalchemy as sa

from alembic import op

revision = "20260928_0001"
down_revision = "20260928_0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("capacity > 0", name="ck_events_capacity_positive"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="ck_events_ends_after_starts"),
    )
    op.create_index("ix_events_starts_at", "events", ["starts_at"])
    op.create_index("ix_events_deleted_at", "events", ["deleted_at"])

    op.create_table(
        "officer_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("officer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("officer_id", "event_id", name="uq_officer_events_officer_event"),
    )
    op.create_index("ix_officer_events_officer_id", "officer_events", ["officer_id"])
    op.create_index("ix_officer_events_event_id", "officer_events", ["event_id"])
    op.create_index("ix_officer_events_deleted_at", "officer_events", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_officer_events_deleted_at", table_name="officer_events")
    op.drop_index("ix_officer_events_event_id", table_name="officer_events")
    op.drop_index("ix_officer_events_officer_id", table_name="officer_events")
    op.drop_table("officer_events")
    op.drop_index("ix_events_deleted_at", table_name="events")
    op.drop_index("ix_events_starts_at", table_name="events")
    op.drop_table("events")
