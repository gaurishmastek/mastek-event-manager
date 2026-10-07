"""admin can close registration for an event

Revision ID: 20261007_0008
Revises: 20261005_0007
Create Date: 2026-10-07
"""

import sqlalchemy as sa

from alembic import op

revision = "20261007_0008"
down_revision = "20261005_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("registration_open", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("events", "registration_open")
