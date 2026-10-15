"""Command-line helpers. Create the first admin with:

python -m app.cli create-admin --email admin@example.com --name "Admin" [--mobile 9876543210]

The email address receives the sign-in code; the mobile is optional contact info. In development, set
EMAIL_PROVIDER=console to print codes instead.

Check which .env was read and the effective email settings (no password, addresses masked, nothing is sent):

python -m app.cli email-config

Send one test message through the configured provider (smtp or mailtrap) to check delivery end to end:

python -m app.cli send-test-email --to you@example.com
"""

import argparse
import getpass
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.modules.guests.bulk_import import import_verified, load_batch
from app.modules.notifications.email import EmailDeliveryError, email_config_summary, get_email_sender
from app.modules.users.models import Role
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user


def create_admin(email: str, name: str, mobile: str | None = None) -> int:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match", file=sys.stderr)
        return 1
    try:
        data = UserCreate(email=email, full_name=name, mobile=mobile, password=password, role=Role.ADMIN)
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 1
    with SessionLocal() as db:
        user = create_user(db, data)
    print(f"Created admin {user.email} (id {user.id})")
    return 0


def email_config() -> int:
    for key, value in email_config_summary(get_settings()).items():
        print(f"{key}: {value}")
    return 0


def send_test_email(to: str) -> int:
    provider = get_settings().email_provider
    try:
        get_email_sender().send(
            to,
            "Mastek Event Manager test email",
            f"This is a test message from the Mastek Event Manager backend (EMAIL_PROVIDER={provider}).",
        )
    except EmailDeliveryError as exc:
        print(f"Not sent: {exc} (see the warning above; docs/DEPLOYMENT.md explains each kind)", file=sys.stderr)
        return 1
    print(f"Accepted by {provider}. Check the provider's logs for delivery status.")
    return 0


def import_verified_batch(
    path: Path, overrides: Path | None, event_id: int, expected_title: str, *, apply: bool
) -> int:
    try:
        batch = load_batch(path, overrides)
    except (OSError, ValueError) as exc:
        print(f"Input rejected: {exc}", file=sys.stderr)
        return 1
    seats = sum(1 + len(row.accompanying_guests) for row in batch)
    print(f"Validated {len(batch)} registrations and {seats} seats for event {event_id} ({expected_title}).")
    if not apply:
        print("Validation only; database and email were not accessed.")
        return 0
    settings = get_settings()
    if settings.environment != "production" or settings.email_provider not in {"smtp", "mailtrap"}:
        print("Import requires production app keys and an SMTP or Mailtrap email provider.", file=sys.stderr)
        return 1
    if settings.database_url == Settings.model_fields["database_url"].default:
        print("Import requires an explicitly configured DATABASE_URL.", file=sys.stderr)
        return 1
    try:
        with SessionLocal() as db:
            result = import_verified(
                db, get_email_sender(), event_id=event_id, expected_title=expected_title, batch=batch
            )
    except ValueError as exc:
        print(f"Import rejected: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Database operation failed; no pass emails were sent.", file=sys.stderr)
        return 1
    print(f"Imported {len(result.employee_ids)} verified registrations; reserved {result.seats_added} seats.")
    print(f"Pass emails accepted by provider: {len(result.emails_accepted)}.")
    if result.emails_failed:
        print(f"Pass email failures (employee IDs): {', '.join(result.emails_failed)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an admin account")
    admin.add_argument("--email", required=True, help="Address that receives sign-in codes")
    admin.add_argument("--name", required=True)
    admin.add_argument("--mobile", help="Optional Indian mobile number, for contact only")
    commands.add_parser("email-config", help="Show the effective email settings without secrets")
    test_email = commands.add_parser("send-test-email", help="Send one test message through EMAIL_PROVIDER")
    test_email.add_argument("--to", required=True, help="Recipient address")
    bulk = commands.add_parser("import-verified", help="Operator-only verified registration import")
    bulk.add_argument("--file", required=True, type=Path, help="JSON array of collected records")
    bulk.add_argument("--overrides", type=Path, help="JSON object keyed by employee id for approved corrections")
    bulk.add_argument("--event-id", required=True, type=int)
    bulk.add_argument("--expected-title", required=True)
    bulk.add_argument("--apply", action="store_true", help="Commit registrations and send QR passes")
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.name, args.mobile)
    if args.command == "email-config":
        return email_config()
    if args.command == "send-test-email":
        return send_test_email(args.to)
    if args.command == "import-verified":
        return import_verified_batch(args.file, args.overrides, args.event_id, args.expected_title, apply=args.apply)
    return 1


if __name__ == "__main__":
    sys.exit(main())
