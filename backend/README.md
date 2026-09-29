# Backend (FastAPI)

## Setup

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set DATABASE_URL (MySQL); leave SECRET_KEY and PII_ENCRYPTION_KEY empty in dev
alembic upgrade head
python -m app.cli create-admin --email you@example.com --name "Your Name"
EMAIL_PROVIDER=console uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Settings are read from `backend/.env` wherever the process is started (the backend folder, the repository root or the
Vercel entry point), and real environment variables override it. A variable set on the command line wins too, so
`EMAIL_PROVIDER=console uvicorn ...` prints codes even when `.env` says `smtp`; drop the prefix to use `.env`. Settings
are read once at startup and `--reload` does not watch `.env`, so **restart the backend after editing `.env`**. Check
what the backend will use, with the password hidden and addresses masked (nothing is sent):
`python -m app.cli email-config`.

Run the tests (SQLite in memory, no MySQL needed): `pytest`. Tests never read `backend/.env` (`APP_ENV_FILE` is set
empty in `tests/conftest.py`). The row-locking and MySQL migration tests in
`tests/guests/test_capacity_mysql.py` run only when `TEST_MYSQL_URL` points at a disposable database, e.g.
`TEST_MYSQL_URL=mysql+pymysql://root:pw@127.0.0.1:3306/events_test pytest`. Lint: `ruff check . && ruff format --check .`

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
| `admin`            | Email and password, then a 6-digit code sent by email| Create staff accounts; manage events; assign officers         |
| `security_officer` | A 6-digit code sent by email to their account email  | View and scan only the events they are assigned to            |

Guests do not get accounts; they register through the public guest form.

Create the first admin with `python -m app.cli create-admin --email ... --name ...` (optional `--mobile ...` for contact info only). In development set
`EMAIL_PROVIDER=console`; sign-in codes are then printed in the backend's terminal.

| Method | Path | Access |
|---|---|---|
| POST | `/api/v1/auth/login` | Public. Admin `{email, password}`; emails a code, returns `{challenge_id, resend_available_at}` |
| POST | `/api/v1/auth/login/verify` | Public. `{challenge_id, code}`; returns `{access_token, token_type, expires_in, user}` |
| POST | `/api/v1/auth/officer/otp` | Public. `{email}`; same 202 answer whether or not the address belongs to an officer |
| POST | `/api/v1/auth/officer/verify` | Public. `{email, code}`; returns a session like `/login/verify`, valid for one shift (8 hours) |
| POST | `/api/v1/auth/logout` | Signed in. Revokes every token issued to the user so far |
| GET | `/api/v1/auth/me` | Signed in |
| GET, POST | `/api/v1/users` | admin. Officers are created with an email and no password |
| GET | `/health` | Public |

Sign-in codes use the same OTP service as guest registration: 5-minute expiry, 5 attempts, a resend cooldown, caps
per email and per IP, and the daily email budget.

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

## Employee registration (public, no login)

Every event has a random `public_id` (UUID4). Admins share its registration link, `/register/{public_id}`, from the
event list. Employees register themselves and their accompanying guests, prove their email with an OTP, and receive
one single-use QR pass that admits the whole party once.

| Method | Path | Notes |
|---|---|---|
| GET | `/public/events/{public_id}` | Event details for the form, `max_guests_per_registration`, `registration_open` and `seats_left` (people) |
| POST | `/public/events/{public_id}/registrations` | `employee_id`, `employee_name`, `email`, `mobile` (Indian, stored as `+91XXXXXXXXXX`), `number_of_guests`, `guest_names` (exactly that many), `consent: true`. Emails an OTP, returns 202 with `registration_id` |
| POST | `/public/registrations/{registration_id}/otp` | Resend the OTP |
| POST | `/public/registrations/{registration_id}/verify` | `code` (6 digits). Returns the pass: party details, `qr_token` and `qr_svg` (data URI) |

- A party takes `1 + number_of_guests` seats, and only once the email is verified. At verification the event row is
  locked and the seat count re-read with a locking read, so a party is admitted whole or not at all and concurrent
  verifications cannot oversell. Registration closes when the event ends (or at its start time if it has no end).
- One registration per employee id (case-insensitive) and per email per event. Registering again while still pending
  updates the details and guests and sends a new code. A verified registration is never changed from the form;
  registering again with the same employee id and email only sends a code, and verifying it issues a new pass that
  voids the old QR code. An employee whose party has already entered cannot get a new pass.
- The QR code holds only a random 256-bit token. The database keeps its SHA-256 hash, never the token.
- The email and mobile are each stored as a keyed hash, Fernet-encrypted and masked. OTPs go to the email only.

OTP rules (all configurable, see `app/core/config.py`): 6-digit codes from `secrets`, stored as an HMAC, valid
5 minutes, 5 wrong attempts per code, a new code voids the old one, 60 s resend cooldown, 5 per email per hour and
10 per day, 20 per IP per hour, and a daily email budget for the whole app (2000). Failed email sends don't count against
the limits. Codes are never returned, logged or stored in clear. Errors: 400 wrong/expired code, 409 event full or
closed, 409 for a duplicate employee id or email, 422 when the party is larger than the event allows, 429 with
`Retry-After` when throttled, 503 when email can't be sent.

Email: `EMAIL_PROVIDER=disabled` (default, fails closed with 503), `console` (prints OTPs to stdout, development only),
`smtp` (requires SMTP server credentials), or `mailtrap` (Mailtrap Email API). A real SMTP provider is configured with
`EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, and `SMTP_PASSWORD`; Mailtrap with `EMAIL_FROM`
and `MAILTRAP_API_TOKEN` (see "Mailtrap" in `docs/DEPLOYMENT.md`). `python -m app.cli send-test-email --to ...` sends one
test message through whichever provider is set. See "Email troubleshooting" in `docs/DEPLOYMENT.md` when codes
don't arrive.

Put CAPTCHA in front of the registration form before going live; the caps above limit abuse but don't stop bots.
Behind a reverse proxy, run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>` so per-IP caps see the
real client address.

## Gate scanning

| Method | Path | Roles | Notes |
|---|---|---|---|
| POST | `/gate/events/{id}/scan` | admin, security_officer | `token` from the QR code, optional `gate` name |
| GET | `/gate/events/{id}/entries` | admin, security_officer | Checked-in guests, newest first; `limit`, `offset` |

An admitted or already-used scan returns the party: employee id and name, guest names, party size, masked email and
mobile (and, for a used pass, when and at which gate it entered). Invalid and wrong-event scans return none of it.

## Registrations (admin)

`GET /events/{id}/registrations` (admin only): `limit`, `offset`, `search` (employee id or name), `status`. Returns
each registration's employee, masked contacts, guests, party size, status and pass/check-in times. It never returns
the QR token or hash, OTP data, or full or encrypted contact details.

A scan always returns 200 with a `result` for the scanner to show: `admitted`, `already_checked_in` (with when and
at which gate), `wrong_event`, `invalid`, or `gate_closed` (scanning opens 3 hours before the start and closes at the
end). Only `admitted` lets the guest in. The officer sees the guest's name and masked email so they can ask for ID
when a pass looks forwarded.

Check-in is a single `UPDATE ... WHERE status = 'VERIFIED'`, so two gates scanning the same pass at once cannot both
admit it; a unique index on `check_ins.registration_id` backs this up. Every scan, whatever the outcome, is written to
`scan_attempts` (never the token itself).

Admins can scan for any event. Security officers can only scan for, and list entries of, events they are assigned
to (see `/events/{id}/officers`); any other event returns 404.

Production refuses to start with the development `SECRET_KEY` or `PII_ENCRYPTION_KEY`, or with `EMAIL_PROVIDER=console`.
