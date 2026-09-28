"""Command-line helpers. Create the first admin with:

python -m app.cli create-admin --email admin@example.com --name "Admin" --mobile 9876543210

The mobile receives the sign-in code. In development, set SMS_PROVIDER=console to print codes instead.
"""

import argparse
import getpass
import sys

from pydantic import ValidationError

from app.db.session import SessionLocal
from app.modules.users.models import Role
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user


def create_admin(email: str, name: str, mobile: str) -> int:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an admin account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    admin.add_argument("--mobile", required=True, help="Indian mobile number that receives sign-in codes")
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.name, args.mobile)
    return 1


if __name__ == "__main__":
    sys.exit(main())
