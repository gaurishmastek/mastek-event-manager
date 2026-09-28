"""send OTPs by email instead of SMS

Guest registrations get email columns and are unique per event by email. The mobile columns stay,
nullable, so registrations made before the switch keep their data. OTP send-log rows key their
per-address caps on `recipient_hash` instead of `mobile_hash`.

Revision ID: 20260928_0003
Revises: 20260928_0002
Create Date: 2026-09-28
"""

import sqlalchemy as sa

from alembic import op

revision = "20260928_0003"
down_revision = "20260928_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registrations") as batch:
        batch.add_column(sa.Column("email_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("email_encrypted", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("email_masked", sa.String(length=260), nullable=True))
        batch.alter_column("mobile_hash", existing_type=sa.String(length=64), nullable=True)
        batch.alter_column("mobile_encrypted", existing_type=sa.String(length=255), nullable=True)
        batch.alter_column("mobile_masked", existing_type=sa.String(length=20), nullable=True)
        # Create before dropping, so MySQL always has an index covering the event_id foreign key.
        batch.create_unique_constraint("uq_registrations_event_email", ["event_id", "email_hash"])
        batch.drop_constraint("uq_registrations_event_mobile", type_="unique")

    op.drop_index("ix_otp_challenges_mobile", table_name="otp_challenges")
    with op.batch_alter_table("otp_challenges") as batch:
        batch.alter_column(
            "mobile_hash", new_column_name="recipient_hash", existing_type=sa.String(length=64), existing_nullable=False
        )
    op.create_index("ix_otp_challenges_recipient", "otp_challenges", ["recipient_hash", "created_at"])


def downgrade() -> None:
    email_only = op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM registrations WHERE mobile_hash IS NULL"))
    if email_only:
        raise RuntimeError(f"{email_only} registrations have no mobile number; downgrading cannot keep them.")

    op.drop_index("ix_otp_challenges_recipient", table_name="otp_challenges")
    with op.batch_alter_table("otp_challenges") as batch:
        batch.alter_column(
            "recipient_hash", new_column_name="mobile_hash", existing_type=sa.String(length=64), existing_nullable=False
        )
    op.create_index("ix_otp_challenges_mobile", "otp_challenges", ["mobile_hash", "created_at"])

    with op.batch_alter_table("registrations") as batch:
        batch.create_unique_constraint("uq_registrations_event_mobile", ["event_id", "mobile_hash"])
        batch.drop_constraint("uq_registrations_event_email", type_="unique")
        batch.alter_column("mobile_masked", existing_type=sa.String(length=20), nullable=False)
        batch.alter_column("mobile_encrypted", existing_type=sa.String(length=255), nullable=False)
        batch.alter_column("mobile_hash", existing_type=sa.String(length=64), nullable=False)
        batch.drop_column("email_masked")
        batch.drop_column("email_encrypted")
        batch.drop_column("email_hash")
