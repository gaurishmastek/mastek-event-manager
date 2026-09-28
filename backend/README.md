# Backend (FastAPI)

## Setup

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set SECRET_KEY and DATABASE_URL (MySQL)
alembic upgrade head
python -m app.cli create-admin --email you@example.com --name "Your Name"
uvicorn app.main:app --reload
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

| Role            | Can do                                                                              |
| --------------- | ----------------------------------------------------------------------------------- |
| `admin`            | Create staff accounts; create, edit and delete events; assign security officers     |
| `security_officer` | View only the events they are assigned to                                           |

Guests do not get accounts; they register through the public guest form (a later module).

| Method | Path | Access |
|---|---|---|
| POST | `/api/v1/auth/login` | Public. JSON `{email, password}`, returns a bearer token |
| GET | `/api/v1/auth/me` | Signed in |
| GET, POST | `/api/v1/users` | admin |
| GET | `/health` | Public |

Security design:

- **Passwords** are hashed with Argon2id (`argon2-cffi`), salted per user, and rehashed on login when the
  recommended parameters change. Minimum 12 characters, not all letters or all digits.
- **Tokens** are short-lived JWT access tokens (HS256, 30 minutes by default) sent as `Authorization: Bearer`.
  `SECRET_KEY` is required and must be at least 32 characters.
- **Permissions are read from the database on every request**, so deactivating a user, deleting them or changing
  their role takes effect on their next request, even with a still-valid token.
- **Deny by default.** Every router except auth is mounted behind authentication. Only routes in `PUBLIC_ROUTES`
  (`app/main.py`) answer without a token, and `tests/test_app.py` fails if any other route does.
- **Login hardening.** One generic error for unknown email, wrong password, locked or disabled account; a dummy hash
  check keeps timing the same for unknown emails; the account locks for 15 minutes after 5 failed attempts.
- Responses carry `nosniff`, `DENY` framing, `no-referrer` and `no-store` headers (plus HSTS in production), and
  the API docs are off when `ENVIRONMENT=production`.

Not yet covered, planned with the OTP module: a second factor for admin login, the security officer OTP login,
and OTP abuse limits (attempt limit, resend cooldown, per-number and per-IP caps, daily SMS budget). Per-IP rate
limiting on `/auth/login` is best done at the reverse proxy.