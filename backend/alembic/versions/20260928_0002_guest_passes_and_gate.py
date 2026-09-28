"""guest registrations, OTP challenges, check-ins and scan log

Revision ID: 20260928_0002
Revises: 20260928_0001
Create Date: 2026-09-28
"""

import sqlalchemy as sa

from alembic import op

revision = "20260928_0002"
down_revision = "20260928_0001"
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
        "registrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("guest_name", sa.String(length=100), nullable=False),
        sa.Column("mobile_hash", sa.String(length=64), nullable=False),
        sa.Column("mobile_encrypted", sa.String(length=255), nullable=False),
        sa.Column("mobile_masked", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("consent_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("qr_token_hash", sa.String(length=64), nullable=True),
        sa.Column("qr_issued_at", sa.DateTime(), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("public_id", name="uq_registrations_public_id"),
        sa.UniqueConstraint("qr_token_hash", name="uq_registrations_qr_token_hash"),
        sa.UniqueConstraint("event_id", "mobile_hash", name="uq_registrations_event_mobile"),
    )
    op.create_index("ix_registrations_event_status", "registrations", ["event_id", "status"])
    op.create_index("ix_registrations_deleted_at", "registrations", ["deleted_at"])

    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("subject_ref", sa.String(length=64), nullable=False),
        sa.Column("code_hmac", sa.String(length=64), nullable=False),
        sa.Column("mobile_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_otp_challenges_subject", "otp_challenges", ["purpose", "subject_ref", "created_at"])
    op.create_index("ix_otp_challenges_mobile", "otp_challenges", ["mobile_hash", "created_at"])
    op.create_index("ix_otp_challenges_ip", "otp_challenges", ["ip_hash", "created_at"])
    op.create_index("ix_otp_challenges_created_at", "otp_challenges", ["created_at"])

    op.create_table(
        "check_ins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("registrations.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=False),
        sa.Column("gate", sa.String(length=50), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint("registration_id", name="uq_check_ins_registration_id"),
    )
    op.create_index("ix_check_ins_event_checked_in_at", "check_ins", ["event_id", "checked_in_at"])
    op.create_index("ix_check_ins_deleted_at", "check_ins", ["deleted_at"])

    op.create_table(
        "scan_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=False),
        sa.Column("registration_id", sa.Integer(), sa.ForeignKey("registrations.id"), nullable=True),
        sa.Column("gate", sa.String(length=50), nullable=True),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_scan_attempts_event_created_at", "scan_attempts", ["event_id", "created_at"])


def downgrade() -> None:
    op.drop_table("scan_attempts")
    op.drop_table("check_ins")
    op.drop_table("otp_challenges")
    op.drop_table("registrations")
