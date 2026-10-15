"""Operator-only import of previously collected employee registrations.

This module is deliberately not exposed as an HTTP endpoint. An operator must supply
the production application configuration and run the CLI from a trusted environment.
"""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import InvalidToken
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_pii, encrypt_pii, keyed_hash, token_hash
from app.core.email import mask_email
from app.db.mixins import utcnow
from app.modules.events.models import Event
from app.modules.guests.models import Registration, RegistrationStatus
from app.modules.guests.pass_email import send_pass_email
from app.modules.guests.qr import new_pass_token
from app.modules.guests.repository import RegistrationRepository
from app.modules.guests.schemas import RegistrationCreate, normalize_employee_id
from app.modules.notifications.email import EmailSender


@dataclass(frozen=True)
class ImportResult:
    employee_ids: tuple[str, ...]
    seats_added: int
    emails_accepted: tuple[str, ...]
    emails_failed: tuple[str, ...]


def _row_to_registration(row: dict) -> RegistrationCreate:
    employee_id = row.get("employee_id", "unknown")
    if row.get("attending") != "yes":
        raise ValueError(f"{employee_id}: this import only supports attending employees")
    if row.get("family_attending") not in {"yes", "no"}:
        raise ValueError(f"{employee_id}: invalid family_attending")
    adult = row.get("adult_name")
    if adult and "," in adult:
        raise ValueError(f"{employee_id}: adult_name contains multiple names; clarify adult and child")
    kids = [part.strip() for part in (row.get("kid_names") or "").split(",") if part.strip()]
    ages = [row.get(key) for key in ("kid_ages_1", "kids_ages_2", "kids_ages_3")]
    ages = [age for age in ages if age is not None]
    food = {"veg": "VEG", "jain": "JAIN", "fast food": "FAST_FOOD"}.get(
        str(row.get("food_preference", "")).strip().lower()
    )
    if food is None:
        raise ValueError(f"{employee_id}: unsupported food_preference")
    try:
        data = RegistrationCreate(
            employee_id=row["employee_id"],
            employee_name=row["employee_name"],
            email=row["email_id"],
            attending=True,
            family_attending=row["family_attending"] == "yes",
            accompanying_adult=bool(adult),
            adult_name=adult,
            accompanying_kids=bool(kids),
            kid_names=kids,
            kid_ages=ages,
            food_preference=food,
            consent=True,
        )
    except (KeyError, ValidationError) as exc:
        raise ValueError(f"{employee_id}: invalid registration: {exc}") from exc
    if len(data.accompanying_guests) != row.get("number_of_guests") or 1 + len(
        data.accompanying_guests
    ) != row.get("party_size"):
        raise ValueError(f"{employee_id}: party count does not match guest details")
    return data


def load_batch(path: Path, overrides_path: Path | None = None) -> list[RegistrationCreate]:
    """Validate the whole supplied file before any database or email action."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path else {}
    if not isinstance(rows, list) or not rows or not isinstance(overrides, dict):
        raise ValueError("expected a nonempty JSON array and an optional JSON object of overrides")
    seen_ids: set[str] = set()
    seen_emails: set[str] = set()
    result: list[RegistrationCreate] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every input row must be an object")
        employee_id = str(row.get("employee_id", ""))
        correction = overrides.get(employee_id, {})
        if not isinstance(correction, dict):
            raise ValueError(f"{employee_id}: override must be an object")
        data = _row_to_registration({**row, **correction})
        normalized_id = normalize_employee_id(data.employee_id)
        if normalized_id in seen_ids or data.email in seen_emails:
            raise ValueError(f"{employee_id}: duplicate employee id or email in input")
        seen_ids.add(normalized_id)
        seen_emails.add(data.email)
        result.append(data)
    unknown_overrides = set(overrides) - {row.employee_id for row in result}
    if unknown_overrides:
        raise ValueError("overrides contain employee ids absent from input")
    return result


def import_verified(
    db: Session,
    sender: EmailSender,
    *,
    event_id: int,
    expected_title: str,
    batch: list[RegistrationCreate],
) -> ImportResult:
    """Atomically add a validated batch, issue one QR per party, then email the passes.

    Sending occurs after commit so a received pass always refers to a real row. If a
    provider rejects a message, that employee id is reported for a later reissue.
    """
    if not batch:
        raise ValueError("batch is empty")
    try:
        # Existing data proves both production keys match the deployed application's keys.
        identity = db.execute(
            select(Registration.email_hash, Registration.email_encrypted)
            .where(Registration.email_hash.is_not(None), Registration.email_encrypted.is_not(None))
            .limit(1)
        ).first()
        if identity is not None:
            try:
                existing_email = decrypt_pii(identity.email_encrypted)
            except (InvalidToken, ValueError) as exc:
                raise ValueError("PII_ENCRYPTION_KEY does not match existing registrations") from exc
            if keyed_hash(existing_email, purpose="email") != identity.email_hash:
                raise ValueError("SECRET_KEY does not match existing registrations")
        event = db.scalars(
            select(Event).where(Event.id == event_id, Event.deleted_at.is_(None)).with_for_update()
        ).first()
        if event is None or event.title != expected_title:
            raise ValueError("event id and title do not match an active event")
        repo = RegistrationRepository(db)
        seats = sum(1 + len(data.accompanying_guests) for data in batch)
        if repo.count_seats_taken(event.id, locking=True) + seats > event.capacity:
            raise ValueError("event capacity is insufficient for the full batch")
        for data in batch:
            if len(data.accompanying_guests) > event.max_guests_per_registration:
                raise ValueError(f"{data.employee_id}: exceeds event guest limit")
            by_employee = repo.get_by_event_and_employee(event.id, normalize_employee_id(data.employee_id))
            by_email = repo.get_by_event_and_email(event.id, keyed_hash(data.email, purpose="email"))
            if by_employee or by_email:
                raise ValueError(f"{data.employee_id}: employee id or email already registered for this event")

        issued: list[tuple[Registration, str, str]] = []
        now = utcnow()
        for data in batch:
            token = new_pass_token()
            row = Registration(
                public_id=str(uuid.uuid4()),
                event_id=event.id,
                employee_id=data.employee_id,
                employee_id_normalized=normalize_employee_id(data.employee_id),
                employee_name=data.employee_name,
                attending=True,
                family_attending=data.family_attending,
                food_preference=data.food_preference.value,
                email_hash=keyed_hash(data.email, purpose="email"),
                email_encrypted=encrypt_pii(data.email),
                email_masked=mask_email(data.email),
                status=RegistrationStatus.VERIFIED.value,
                consent_at=now,
                verified_at=now,
                qr_token_hash=token_hash(token),
                qr_issued_at=now,
            )
            repo.add(row)
            repo.set_guests(row, data.accompanying_guests)
            issued.append((row, data.email, token))
        db.commit()
    except Exception:
        db.rollback()
        raise

    accepted: list[str] = []
    failed: list[str] = []
    for row, email, token in issued:
        if send_pass_email(sender, email, row, event, token):
            accepted.append(row.employee_id)
        else:
            failed.append(row.employee_id)
    return ImportResult(
        employee_ids=tuple(row.employee_id for row, _, _ in issued),
        seats_added=seats,
        emails_accepted=tuple(accepted),
        emails_failed=tuple(failed),
    )
