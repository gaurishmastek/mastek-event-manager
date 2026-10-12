# Request logs (admin Logs page)

Admins get a Vercel-style logs page at `/admin/logs`: every API request, with the log lines written while it ran,
stored in MongoDB and searchable by level, status, path, method and time. The code comes from the separate
`fastapi-logs-list` project and is copied in unchanged, so it can be refreshed from there.

## Turning it on

Logs are off until `LOGS_MONGODB_URL` is set. Add these to `backend/.env` (or the deployment's environment):

```
LOGS_MONGODB_URL=<your MongoDB URL>
LOGS_MONGODB_DB=mastek_event_logs
LOGS_SERVICE_NAME=mastek-event-manager
LOGS_ENVIRONMENT=development
LOGS_RETENTION_DAYS=14
```

The URL usually holds a password: keep it in `backend/.env` or the environment, never in code or docs. Restart the
backend, use the app for a moment, then open **Logs** in the admin header. If MongoDB is unreachable the backend still
starts and prints `Could not reach logs MongoDB at startup`.

## How it is wired

| Piece | Where |
|---|---|
| Capture middleware, MongoDB writer, logs API (copied unchanged) | `backend/app/logs_viewer/` |
| Switched on, mounted at `/api/v1/logs` | `backend/app/main.py`, end of `create_app()` |
| Admin-only access | `backend/app/core/logs_auth.py` |
| Tests | `backend/tests/test_logs_viewer.py` (a fake in-memory MongoDB, no server needed) |
| Logs page (copied unchanged apart from its title) | `frontend/src/app/logs/` |
| Route `/admin/logs`, admins only, full screen outside the admin shell | `frontend/src/app/admin/admin.routes.ts` |
| API address and token for the page | `frontend/src/app/app.config.ts` |
| **Logs** link | `frontend/src/app/admin/shell/admin-shell.component.html` |

Ruff skips `app/logs_viewer` (see `pyproject.toml`) so the copy stays identical to its source.

## Security

- Only admins can read logs. Security officers get 403, everyone else 401; the deny-by-default route test still holds.
- The Live stream and downloads are plain browser requests that cannot send the `Authorization` header, so the logs API
  also accepts the access token as `?token=`. Only those two use it: `auth.interceptor.ts` strips it from normal
  requests, which send the header. The logs API's own requests are never recorded.
- `print()` output is never stored, because `EMAIL_PROVIDER=console` prints OTP emails with their codes. Python
  `logging` lines are stored; they already mask emails. In development the console email sender also logs
  `[dev email] To: <masked address> | <subject>`; for code emails it adds the text with the 6-digit code replaced by
  `******`. Other emails (entry passes, which hold names) log only the subject.
- uvicorn's startup lines (`Started server process`, `Application startup complete.`, `Uvicorn running on ...`) are
  stored as their own entries, and each request's access line (`127.0.0.1:5000 - "GET /x HTTP/1.1" 200 OK`) is a
  message on that request. The logs page's own polling is not stored. `LOGS_CAPTURE_SERVER_LOGS=false` turns this
  off. Lines printed before the process starts (`Will watch for changes`, `Started reloader process`) come from
  uvicorn's reloader process and are not captured.
- Stored per request: method, path, query string, status, duration, host, client IP and user agent. Request and
  response bodies are not stored.
- Entries expire after `LOGS_RETENTION_DAYS` (a MongoDB TTL index).

## Versions

Checked on this project's versions: Python 3.11, FastAPI 0.141.1, pydantic-settings 2.15.0, Angular 19.2 with
Tailwind 4. The viewer needs `pymongo==4.18.3` (pinned in all three requirement lists, which the deployment test keeps
in sync); tests also use `mongomock-motor`.

## On Vercel (not yet tried)

The backend runs there as a serverless function, which the viewer was not built for:

- Entries are written by a background task about once a second. A function can be frozen right after it responds, so
  entries may show up late, or be lost when Vercel recycles the instance.
- The MongoDB connection is opened in the app's startup (lifespan) hook; check after deploying that the Logs page shows
  requests.
- A hosted MongoDB (e.g. Atlas) must accept connections from Vercel, which has no fixed IP addresses.
