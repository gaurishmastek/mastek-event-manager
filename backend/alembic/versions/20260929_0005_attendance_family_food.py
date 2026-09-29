"""attendance, family members and food preference on registrations

Registrations gain the answers to "Will you be attending?" (`attending`, true for existing rows),
"Will you be accompanied by your family?" (`family_attending`) and the food preference. Accompanying
guests gain a `guest_type` (ADULT or KID); guests registered before this stay untyped. Registrations
of employees who will not attend use the new status value DECLINED, which needs no schema change.

Revision ID: 20260929_0005
Revises: 20260928_0004
Create Date: 2026-09-29
"""

import sqlalchemy as sa

from alembic import op

revision = "20260929_0005"
down_revision = "20260928_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registrations") as batch:
        batch.add_column(sa.Column("attending", sa.Boolean(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("family_attending", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("food_preference", sa.String(length=20), nullable=True))
        batch.create_check_constraint(
            "ck_registrations_food_preference",
            "food_preference IS NULL OR food_preference IN ('VEG', 'JAIN', 'FAST_FOOD')",
        )

    with op.batch_alter_table("registration_guests") as batch:
        batch.add_column(sa.Column("guest_type", sa.String(length=10), nullable=True))
        batch.create_check_constraint(
            "ck_registration_guests_guest_type", "guest_type IS NULL OR guest_type IN ('ADULT', 'KID')"
        )


def downgrade() -> None:
    bind = op.get_bind()
    declined = bind.scalar(
        sa.text("SELECT COUNT(*) FROM registrations WHERE attending = :no OR status = 'DECLINED'"), {"no": False}
    )
    if declined:
        raise RuntimeError(f"{declined} registrations are declines; downgrading would turn them into attendees.")

    with op.batch_alter_table("registration_guests") as batch:
        batch.drop_constraint("ck_registration_guests_guest_type", type_="check")
        batch.drop_column("guest_type")

    with op.batch_alter_table("registrations") as batch:
        batch.drop_constraint("ck_registrations_food_preference", type_="check")
        batch.drop_column("food_preference")
        batch.drop_column("family_attending")
        batch.drop_column("attending")
