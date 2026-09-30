"""age of each accompanying kid

Accompanying guests gain an `age` in whole years (0-17), set for every kid. It stays null for the
adult and for kids registered before ages were asked.

Revision ID: 20260930_0006
Revises: 20260929_0005
Create Date: 2026-09-30
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0006"
down_revision = "20260929_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registration_guests") as batch:
        batch.add_column(sa.Column("age", sa.Integer(), nullable=True))
        batch.create_check_constraint("ck_registration_guests_age", "age IS NULL OR (age >= 0 AND age <= 17)")


def downgrade() -> None:
    with_age = op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM registration_guests WHERE age IS NOT NULL"))
    if with_age:
        raise RuntimeError(f"{with_age} accompanying kids have an age; downgrading would lose it.")

    with op.batch_alter_table("registration_guests") as batch:
        batch.drop_constraint("ck_registration_guests_age", type_="check")
        batch.drop_column("age")
