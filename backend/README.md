# Backend (FastAPI)

## Setup

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set DATABASE_URL to your MySQL database
alembic upgrade head
uvicorn app.main:app --reload
```

Run the tests (SQLite in memory, no MySQL needed): `pytest`. Lint: `ruff check . && ruff format --check .`

## Events API

All routes live under `/api/v1/events` and require an authenticated user.

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/events` | admin, event_manager, security | `limit` (1-100, default 20), `offset`, `search` (title, 1-100 chars), `upcoming=true` |
| POST | `/events` | admin, event_manager | Returns 201 with the event |
| GET | `/events/{id}` | admin, event_manager, security | 404 if missing or deleted |
| PATCH | `/events/{id}` | admin, event_manager | Partial update; only sent fields change |
| DELETE | `/events/{id}` | admin, event_manager | Soft delete, returns 204 |

Event fields: `title` (3-200 chars, one line), `description` (optional, up to 5000), `location` (2-255 chars, one line),
`starts_at` (must be in the future), `ends_at` (optional, not before `starts_at`), `capacity` (integer 1-100000).

Validation rules:

- Datetimes must carry a timezone offset (e.g. `2026-10-20T18:00:00+05:30`); they are stored and returned as UTC.
- Unknown fields (including audit fields like `created_by`) are rejected with 422, so clients cannot mass-assign them.
- Text is trimmed; control characters are rejected. Text is stored as-is and must be escaped by whatever renders it.
- `capacity` must be a real JSON integer (no strings, floats or booleans).

Records are never hard-deleted. Every row carries `created_at/by`, `updated_at/by` and `deleted_at/by`.
Features that must respect capacity (guest registration) should call `EventRepository.get_for_update()` so concurrent
requests cannot overbook an event.

## Auth

`app/modules/auth/dependencies.py` is a stand-in until the auth module lands: it rejects every request with 401,
so no route is reachable without real authentication. Tests override `get_current_user`.

## Guest registration (public, no login)

Guests register through a public form, prove their mobile number with an OTP, and receive a single-use QR pass.

| Method | Path | Notes |
|---|---|---|
| GET | `/public/events/{id}` | Event details for the form, `registration_open` and `seats_left` |
| POST | `/public/events/{id}/registrations` | `guest_name`, `mobile` (Indian numbers only), `consent: true`. Sends an OTP, returns 202 with `registration_id` |
| POST | `/public/registrations/{registration_id}/otp` | Resend the OTP |
| POST | `/public/registrations/{registration_id}/verify` | `code` (6 digits). Returns the pass: `qr_token` and `qr_svg` (data URI) |

- A registration only takes a seat once the mobile is verified; capacity is checked under a row lock on the event.
  Registration closes when the event ends (or at its start time if it has no end).
- Registering again with the same mobile resumes the same registration. Verifying again issues a new pass and voids
  the old QR code, for a guest who lost it. A guest who has already entered cannot get a new pass.
- The QR code holds only a random 256-bit token. The database keeps its SHA-256 hash, never the token.
- The mobile is stored as a keyed hash (lookups), Fernet-encrypted (for sending OTPs) and masked (display).

OTP rules (all configurable, see `app/core/config.py`): 6-digit codes from `secrets`, stored as an HMAC, valid
5 minutes, 5 wrong attempts per code, a new code voids the old one, 60 s resend cooldown, 5 per mobile per hour and
10 per day, 20 per IP per hour, and a daily SMS budget for the whole app (2000). Failed SMS sends don't count against
the limits. Codes are never returned, logged or stored in clear. Errors: 400 wrong/expired code, 409 event full or
closed, 429 with `Retry-After` when throttled, 503 when SMS can't be sent.

SMS: `SMS_PROVIDER=disabled` (default, fails closed with 503) or `console` (prints OTPs to stdout, development only).
A real provider plugs in by implementing `SmsSender` in `app/modules/otp/sms.py`.

Put CAPTCHA in front of the registration form before going live; the caps above limit abuse but don't stop bots.
Behind a reverse proxy, run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>` so per-IP caps see the
real client address.

## Gate scanning

| Method | Path | Roles | Notes |
|---|---|---|---|
| POST | `/gate/events/{id}/scan` | admin, security | `token` from the QR code, optional `gate` name |
| GET | `/gate/events/{id}/entries` | admin, security | Checked-in guests, newest first; `limit`, `offset` |

A scan always returns 200 with a `result` for the scanner to show: `admitted`, `already_checked_in` (with when and
at which gate), `wrong_event`, `invalid`, or `gate_closed` (scanning opens 3 hours before the start and closes at the
end). Only `admitted` lets the guest in. The officer sees the guest's name and masked mobile so they can ask for ID
when a pass looks forwarded.

Check-in is a single `UPDATE ... WHERE status = 'VERIFIED'`, so two gates scanning the same pass at once cannot both
admit it; a unique index on `check_ins.registration_id` backs this up. Every scan, whatever the outcome, is written to
`scan_attempts` (never the token itself).

Officers may only scan for events they are assigned to. Assignments come with the auth module; until they are wired
into `app/modules/gate/access.py`, officers get 404 for every event and only admins can scan.

Production refuses to start with the development `SECRET_KEY` or `PII_ENCRYPTION_KEY`, or with `SMS_PROVIDER=console`.
