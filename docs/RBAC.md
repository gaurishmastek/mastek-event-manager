# Roles and access control

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4). Scope: the event, guest
registration/OTP/QR, and gate-scanning module only. This file did not exist in the repo before.

## Roles

Defined in `app/modules/auth/dependencies.py`:

- `admin` (`ROLE_ADMIN`)
- `security_officer` (`ROLE_SECURITY_OFFICER`)

There is no `event_manager` role and guests have no account or role — the public guest endpoints
require no authentication at all, only a verified OTP (see [`API.md`](./API.md)).

## Authentication: not implemented yet

`get_current_user()` in `auth/dependencies.py` unconditionally raises `401 Not authenticated`.
No login, token issuance or session exists on `main`. Every route that depends on
`require_roles(...)` is therefore currently unreachable in a real deployment; the events and
gate test suites cover the role logic by overriding `get_current_user` with a fake `CurrentUser`.
This is intentional — it is a fail-closed placeholder until the real auth module (admin
password + 2FA, officer OTP login) lands, per `docs/event-management.md` section 1.

## Officer scope

A security officer only acts on events they are assigned to, via the `officer_events` table
(`officer_id`, `event_id`, unique pair). There is currently no API to manage that table — rows
must be inserted directly (e.g. by a future admin/users module or a migration/seed script).

Enforcement points:

| Module | Enforcement |
|---|---|
| `events/repository.py` | `list()`/`get()` take an `officer_id`; when set, results are filtered to `officer_events` rows for that officer. `events/service.py` passes the viewer's id only when `viewer.role == ROLE_SECURITY_OFFICER`. |
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
| Public registration/OTP/verify endpoints (`/public/...`) | n/a | n/a | ✅, no login |

Not yet built: officer/admin account management endpoints, an audit-log read API, and admin
manual check-in (fallback for when scanning is unavailable) — see `event-management.md`'s
"Open decisions" and "Build order" for what is still planned.
