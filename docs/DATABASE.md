# Database

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4). Scope: tables created by the event,
guest registration/OTP/QR, and gate-scanning module. This file did not exist in the repo before.
MySQL via SQLAlchemy 2.x; every schema change goes through an Alembic migration
(`backend/alembic/versions/`).

Migrations so far:

- `20260928_0000_create_users.py` — `users`
- `20260928_0001_create_events.py` — `events`, `officer_events`
- `20260928_0002_guest_passes_and_gate.py` — `registrations`, `otp_challenges`, `check_ins`,
  `scan_attempts`
- `20260928_0003_email_otp.py` — email columns on `registrations`, `otp_challenges.recipient_hash`
- `20260928_0004_registration_links.py` — `events.public_id` (filled with a fresh UUID4 for existing events, then
  made unique and not null) and `events.max_guests_per_registration`; renames `registrations.guest_name` to
  `employee_name` (data kept) and adds `employee_id`, `employee_id_normalized`, `number_of_guests`; creates
  `registration_guests`. Existing registrations keep their passes and count as a party of one. Downgrading refuses
  to run once any registration has an employee id or guests.

## Audit columns

Tables marked "audited" below use `app/db/mixins.py::AuditMixin`:
`created_at`, `updated_at`, `deleted_at` (nullable — soft delete), `created_by`, `updated_by`,
`deleted_by` (all `Integer`, holding a `users.id`, without a foreign key). Repositories
filter out rows where `deleted_at IS NOT NULL`.

## Tables

### `users` (audited)

Staff accounts: admins and security officers. Guests never get a row here.

| Column | Type | Notes |
|---|---|---|
| `id` | int | PK |
| `email` | varchar(254) | not null, unique, stored lowercase |
| `full_name` | varchar(120) | not null |
| `password_hash` | varchar(255) | not null. Argon2id. Officers get a hash of a random value |
| `role` | enum `admin`, `security_officer` | not null |
| `mobile_hash` | varchar(64) | nullable, unique. HMAC of the mobile (contact info only; deprecated for 2FA) |
| `mobile_encrypted` | varchar(255) | nullable. Fernet-encrypted mobile (contact info only; deprecated for 2FA) |
| `is_active` | bool | not null |
| `session_version` | int | not null. Bumped on logout; access tokens carry it and stop working when it changes |
| `failed_login_attempts`, `locked_until`, `last_login_at` | int, datetime, datetime | Password lockout and last sign-in |


### `events` (audited)

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | Internal only; never used in public links |
| `public_id` | varchar(36) | not null, unique (`uq_events_public_id`). Random UUID4 for the registration link |
| `title` | varchar(200) | not null |
| `description` | text | nullable |
| `location` | varchar(255) | not null |
| `starts_at` | datetime | not null, indexed |
| `ends_at` | datetime | nullable |
| `capacity` | int | not null, `CHECK (capacity > 0)`. Counted in people |
| `max_guests_per_registration` | int | not null, default 5, `CHECK (0..10)` (`ck_events_max_guests_range`) |

Constraint: `ck_events_ends_after_starts` — `ends_at IS NULL OR ends_at >= starts_at`.

No `status` or `registered_count` column yet (see
[`BUSINESS_RULES.md`](./BUSINESS_RULES.md) and [`event-management.md`](./event-management.md#open-decisions)).
Seats taken are computed from `registrations`, not stored on `events`.

### `officer_events` (audited)

Assigns a security officer to an event.

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `officer_id` | int | not null, indexed, FK `users.id` |
| `event_id` | int | FK → `events.id`, not null, indexed |

Unique: `uq_officer_events_officer_event` on `(officer_id, event_id)`.

### `registrations` (audited)

An employee's registration for one event: one party (the employee plus `number_of_guests` accompanying guests) and
one QR pass. The email and mobile are each stored three ways: hashed for lookup, encrypted (the email to send OTPs),
masked for display — see [`SECURITY.md`](./SECURITY.md). Registrations from before the registration-link workflow
have no employee id and no guests; those from before the SMS→email switch have only mobile columns.

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `public_id` | varchar(36) | UUID4, unique — the id exposed to guests |
| `event_id` | int | FK → `events.id`, not null |
| `employee_id` | varchar(30) | nullable (older rows only) — as entered |
| `employee_id_normalized` | varchar(30) | nullable (older rows only) — upper-cased, for uniqueness |
| `employee_name` | varchar(100) | not null (was `guest_name` before `0004`) |
| `number_of_guests` | int | not null, default 0 — accompanying guests; the party takes `1 + number_of_guests` seats |
| `email_hash` | varchar(64) | not null — HMAC-SHA256, for lookup/uniqueness |
| `email_encrypted` | varchar(512) | not null — Fernet ciphertext |
| `email_masked` | varchar(260) | not null — display only, e.g. `as•••@example.com` |
| `mobile_hash` | varchar(64) | nullable — HMAC of the `+91` mobile. Set on every new registration |
| `mobile_encrypted` | varchar(255) | nullable — Fernet ciphertext of the mobile. Never used to send messages |
| `mobile_masked` | varchar(20) | nullable — display copy, e.g. `98•••••210` |
| `status` | varchar(20) | `PENDING_OTP` \| `VERIFIED` \| `CHECKED_IN`, default `PENDING_OTP` |
| `consent_at` | datetime | not null |
| `verified_at` | datetime | nullable |
| `qr_token_hash` | varchar(64) | nullable, unique — SHA-256 of the QR pass token; no separate `qr_passes` table |
| `qr_issued_at` | datetime | nullable |
| `checked_in_at` | datetime | nullable |

Unique: `uq_registrations_event_email` on `(event_id, email_hash)`, `uq_registrations_event_employee` on
`(event_id, employee_id_normalized)` (NULLs of older rows don't collide). Index: `ix_registrations_event_status` on
`(event_id, status)`.

### `registration_guests` (audited)

The accompanying guests of a registration, in the order the employee listed them. Never hard-deleted: when a pending
registration's guest list shrinks, the extra rows are soft-deleted, and revived if that position is needed again.

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `registration_id` | int | FK → `registrations.id`, not null |
| `name` | varchar(100) | not null |
| `position` | int | not null — 0-based order |

Unique: `uq_registration_guests_position` on `(registration_id, position)`.

### `otp_challenges` (append-only, no `AuditMixin`)

One row per OTP sent. Never deleted — also doubles as the send log that rate limits are counted
from.

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `purpose` | varchar(32) | e.g. `GUEST_VERIFY` |
| `subject_ref` | varchar(64) | e.g. the registration's `public_id` |
| `code_hmac` | varchar(64) | not null — the code is never stored in clear |
| `recipient_hash` | varchar(64) | not null — HMAC of email address (or legacy mobile) |
| `ip_hash` | varchar(64) | nullable |
| `attempts` | int | not null, default 0 |
| `expires_at` | datetime | not null |
| `consumed_at` | datetime | nullable |
| `invalidated_at` | datetime | nullable — set when a newer OTP for the same subject supersedes this one |
| `created_at`, `updated_at` | datetime | |

Indexes: `(purpose, subject_ref, created_at)`, `(recipient_hash, created_at)`,
`(ip_hash, created_at)`, `(created_at)`.

### `check_ins` (audited)

One row per successful gate entry. `registration_id` unique — the database's final guarantee
that a pass admits only once.

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `registration_id` | int | FK → `registrations.id`, not null, **unique** |
| `event_id` | int | FK → `events.id`, not null |
| `officer_id` | int | not null — no FK yet |
| `gate` | varchar(50) | nullable |
| `method` | varchar(10) | default `"QR"` (no `MANUAL` entries yet — see BUSINESS_RULES.md) |
| `checked_in_at` | datetime | not null |

Index: `ix_check_ins_event_checked_in_at` on `(event_id, checked_in_at)`.

### `scan_attempts` (append-only, no `AuditMixin`)

Every scan, successful or not. The scanned token itself is never stored.

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `event_id` | int | FK → `events.id`, not null |
| `officer_id` | int | not null |
| `registration_id` | int | FK → `registrations.id`, nullable (null for `wrong_event`/unmatched scans) |
| `gate` | varchar(50) | nullable |
| `result` | varchar(30) | one of the `ScanResult` values — see [`BUSINESS_RULES.md`](./BUSINESS_RULES.md) |
| `created_at` | datetime | not null |

Index: `ix_scan_attempts_event_created_at` on `(event_id, created_at)`.

## Not yet in the database

`sessions` (refresh tokens), `qr_passes` (as a separate table with its own validity window), and
`audit_log` do not exist on `main` — they belong to the fuller auth and audit design
described in [`event-management.md`](./event-management.md#3-data-model), which have not landed
yet.
