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
