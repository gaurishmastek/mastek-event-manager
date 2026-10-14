"""security officers sign in with email and password: give existing officers the default password

Revision ID: 20261014_0009
Revises: 20261007_0008
Create Date: 2026-10-14

Officers used to sign in with an emailed code and had a random, unknown password hash. This sets every officer's
password to DEFAULT_OFFICER_PASSWORD (default "admin@123"), stored only as an Argon2 hash, and clears any lockout.
Admins are untouched. No schema change.
"""

import sqlalchemy as sa

from alembic import op
from app.core.config import get_settings
from app.core.security import hash_password

revision = "20261014_0009"
down_revision = "20261007_0008"
branch_labels = None
depends_on = None

users = sa.table(
    "users",
    sa.column("role", sa.String),
    sa.column("password_hash", sa.String),
    sa.column("failed_login_attempts", sa.Integer),
    sa.column("locked_until", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)


def upgrade() -> None:
    op.execute(
        users.update()
        .where(users.c.role == "security_officer")
        .values(
            password_hash=hash_password(get_settings().default_officer_password),
            failed_login_attempts=0,
            locked_until=None,
            updated_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    # The old hashes were of random values nobody knew, so there is nothing to restore. Officers keep the default
    # password, which the code-only sign-in of the older revision simply ignores.
    pass
