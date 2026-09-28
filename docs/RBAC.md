# Roles and access control

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4). Scope: the event, guest
registration/OTP/QR, and gate-scanning module only. This file did not exist in the repo before.

## Roles

Defined in `app/modules/auth/dependencies.py`:

- `admin` (`ROLE_ADMIN`)
- `security_officer` (`ROLE_SECURITY_OFFICER`)

There is no `event_manager` role and guests have no account or role — the public guest endpoints
require no authentication at all, only a verified OTP (see [`API.md`](./API.md)).

## Authentication

Staff sign in through `app/modules/auth` (see [`API.md`](./API.md#staff-auth--appmodulesauthrouterpy)):

- **Admin**: email and password (Argon2id, lockout after repeated failures), then a 6-digit code
  emailed to their account email.
- **Security officer**: a 6-digit code emailed to their account email. Officers have no password.

Both steps return a short-lived JWT access token. `get_current_user()` re-reads the user on every
request, so deactivation, deletion or a role change applies immediately, and `POST /auth/logout`
bumps the user's `session_version`, revoking every earlier token.

Every router except auth and the public guest routes is mounted behind authentication in
`app/main.py`. Only routes listed in `PUBLIC_ROUTES` answer without a token, and
`tests/test_app.py` fails if any other route does.

## Officer scope

A security officer only acts on events they are assigned to, via the `officer_events` table
(`officer_id`, `event_id`, unique pair). Admins manage it with `GET/PUT/DELETE
/events/{id}/officers[/{user_id}]`; only active `security_officer` users can be assigned, and
unassigning is a soft delete.

Enforcement points:

| Module | Enforcement |
|---|---|
| `events/repository.py` | `list()`/`get()` take an `officer_id`; when set, results are filtered to `officer_events` rows for that officer. `events/service.py` passes the viewer's id only when `viewer.role == ROLE_SECURITY_OFFICER`. |
| `guests/admin_router.py` | `require_roles(admin)` on `GET /events/{id}/registrations`; the Angular `/admin/events/:id/registrations` route guard is only a convenience. |
| `gate/access.py::EventScopePolicy` | `allows(user, event_id)` — `True` for any admin; for an officer, `True` only if `officer_events` has a row for `(officer_id, event_id)`. Used by both `POST /gate/events/{id}/scan` and `GET /gate/events/{id}/entries`. |

An officer requesting an event (read, or gate scan/entries) they are not assigned to gets a
`404`, the same as a nonexistent event — the API never reveals that an out-of-scope event exists.

## Permission matrix (current code)

| Capability | Admin | Security officer | Guest (no account) |
|---|---|---|---|
| `GET /events` | all events | assigned events only | — |
| `GET /events/{id}` | any | assigned only (else 404) | — |
| `POST /events`, `PATCH /events/{id}`, `DELETE /events/{id}` | ✅ | ❌ (403) | — |
| `POST /gate/events/{id}/scan` | any event | assigned events only (else 404) | — |
| `GET /gate/events/{id}/entries` | any event | assigned events only (else 404) | — |
| `GET/PUT/DELETE /events/{id}/officers...` | ✅ | ❌ (403) | — |
| `GET /events/{id}/registrations` (registrations list, masked contacts) | ✅ | ❌ (403, even for assigned events) | — |
| `GET/POST /users` (staff accounts) | ✅ | ❌ (403) | — |
| `/auth/login`, `/auth/login/verify`, `/auth/officer/otp`, `/auth/officer/verify` | public | public | — |
| `GET /auth/me`, `POST /auth/logout` | ✅ | ✅ | — |
| Public registration/OTP/verify endpoints (`/public/...`, by event `public_id`) | n/a | n/a | ✅, no login |

Not yet built: editing or deactivating staff accounts via the API, an audit-log read API, and admin
manual check-in (fallback for when scanning is unavailable) — see `event-management.md`'s
"Open decisions" and "Build order" for what is still planned.
