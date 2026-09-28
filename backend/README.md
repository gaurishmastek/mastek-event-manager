# Backend (FastAPI)

## Setup

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set SECRET_KEY and DATABASE_URL (MySQL)
alembic upgrade head
python -m app.cli create-admin --email you@example.com --name "Your Name"
SMS_PROVIDER=console uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Run the tests (SQLite in memory, no MySQL needed): `pytest`. Lint: `ruff check . && ruff format --check .`

## Events API

All routes live under `/api/v1/events` and require an authenticated user. There are two roles: `admin` manages
events, and `security_officer` can only read the events they are assigned to (rows in `officer_events`). Officer
scope is applied inside the SQL query, and an unassigned event returns 404 so IDs can't be probed. Any other role
gets 403.

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/events` | admin (all), security_officer (assigned only) | `limit` (1-100, default 20), `offset`, `search` (title, 1-100 chars), `upcoming=true` |
| POST | `/events` | admin | Returns 201 with the event |
| GET | `/events/{id}` | admin, security_officer (assigned only) | 404 if missing, deleted or not assigned |
| PATCH | `/events/{id}` | admin | Partial update; only sent fields change |
| DELETE | `/events/{id}` | admin | Soft delete, returns 204 |
| GET | `/events/{id}/officers` | admin | User ids of assigned security officers |
| PUT | `/events/{id}/officers/{user_id}` | admin | Assign a security officer, returns 204 |
| DELETE | `/events/{id}/officers/{user_id}` | admin | Soft-unassign, returns 204 |

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

## Auth and roles

| Role               | Signs in with                                        | Can do                                                        |
| ------------------ | ---------------------------------------------------- | ------------------------------------------------------------- |
| `admin`            | Email and password, then a 6-digit code sent by SMS  | Create staff accounts; manage events; assign officers         |
| `security_officer` | A 6-digit code sent by SMS to their registered mobile | View and scan only the events they are assigned to            |

Guests do not get accounts; they register through the public guest form.

Create the first admin with `python -m app.cli create-admin --email ... --name ... --mobile ...`. In development set
`SMS_PROVIDER=console`; sign-in codes are then printed in the backend's terminal.

| Method | Path | Access |
|---|---|---|
| POST | `/api/v1/auth/login` | Public. Admin `{email, password}`; texts a code, returns `{challenge_id, resend_available_at}` |
| POST | `/api/v1/auth/login/verify` | Public. `{challenge_id, code}`; returns `{access_token, token_type, expires_in, user}` |
| POST | `/api/v1/auth/officer/otp` | Public. `{mobile}`; same 202 answer whether or not the number belongs to an officer |
| POST | `/api/v1/auth/officer/verify` | Public. `{mobile, code}`; returns a session like `/login/verify`, valid for one shift (8 hours) |
| POST | `/api/v1/auth/logout` | Signed in. Revokes every token issued to the user so far |
| GET | `/api/v1/auth/me` | Signed in |
| GET, POST | `/api/v1/users` | admin. Officers are created with a mobile and no password |
| GET | `/health` | Public |

Sign-in codes use the same OTP service as guest registration: 5-minute expiry, 5 attempts, a resend cooldown, caps
per number and per IP, and the daily SMS budget.

Security design:

- **Passwords** are hashed with Argon2id (`argon2-cffi`), salted per user, and rehashed on login when the
  recommended parameters change. Minimum 12 characters, not all letters or all digits.
- **Tokens** are short-lived JWT access tokens (HS256; 30 minutes for admins, one 8-hour shift for officers) sent
  as `Authorization: Bearer`. Logging out bumps the user's session version, which revokes every earlier token.
- **Permissions are read from the database on every request**, so deactivating a user, deleting them or changing
  their role takes effect on their next request, even with a still-valid token.
- **Deny by default.** Every router except auth is mounted behind authentication. Only routes in `PUBLIC_ROUTES`
  (`app/main.py`) answer without a token, and `tests/test_app.py` fails if any other route does.
- **Login hardening.** One generic error for unknown email, wrong password, locked or disabled account; a dummy hash
  check keeps timing the same for unknown emails; the account locks for 15 minutes after 5 failed attempts.
- Responses carry `nosniff`, `DENY` framing, `no-referrer` and `no-store` headers (plus HSTS in production), and
  the API docs are off when `ENVIRONMENT=production`.

Not yet covered: refresh tokens (the frontend keeps the access token in memory, so a page reload signs out) and
per-IP rate limiting on the password step, which is best done at the reverse proxy.

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
| POST | `/gate/events/{id}/scan` | admin, security_officer | `token` from the QR code, optional `gate` name |
| GET | `/gate/events/{id}/entries` | admin, security_officer | Checked-in guests, newest first; `limit`, `offset` |

A scan always returns 200 with a `result` for the scanner to show: `admitted`, `already_checked_in` (with when and
at which gate), `wrong_event`, `invalid`, or `gate_closed` (scanning opens 3 hours before the start and closes at the
end). Only `admitted` lets the guest in. The officer sees the guest's name and masked mobile so they can ask for ID
when a pass looks forwarded.

Check-in is a single `UPDATE ... WHERE status = 'VERIFIED'`, so two gates scanning the same pass at once cannot both
admit it; a unique index on `check_ins.registration_id` backs this up. Every scan, whatever the outcome, is written to
`scan_attempts` (never the token itself).

Admins can scan for any event. Security officers can only scan for, and list entries of, events they are assigned
to (see `/events/{id}/officers`); any other event returns 404.

Production refuses to start with the development `SECRET_KEY` or `PII_ENCRYPTION_KEY`, or with `SMS_PROVIDER=console`.
