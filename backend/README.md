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
The `officer_events` table is created here with `officer_id` as a plain integer; the foreign key to `users` and the
admin endpoints to assign officers belong with the users module.
