# API

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4). Scope: the event, guest
registration/OTP/QR, and gate-scanning routers only. This file did not exist in the repo before.
FastAPI, all routes mounted under `/api/v1` (`app/main.py`). JSON only. Validation errors return
`422` (Pydantic); all request models use `extra="forbid"`.

Routes marked "admin" or "officer" need `Authorization: Bearer <access_token>` from the staff
auth endpoints below; see [`RBAC.md`](./RBAC.md) for who can call what.

## Staff auth — `app/modules/auth/router.py`

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/login` | `{email, password}` (admins only) | `200 {challenge_id, resend_available_at}`; texts a 6-digit code. `401` for any wrong/unknown/locked/non-admin account |
| POST | `/auth/login/verify` | `{challenge_id, code}` | `200 {access_token, token_type, expires_in, user: {id, role, name}}`; `400` for a bad or expired code |
| POST | `/auth/officer/otp` | `{mobile}` | `202 {resend_available_at}`, the same whether or not the number belongs to an officer; `429` with `Retry-After` when throttled |
| POST | `/auth/officer/verify` | `{mobile, code}` | Same session shape as `/auth/login/verify`, valid for one shift (`OFFICER_SESSION_MINUTES`, default 8 h) |
| POST | `/auth/logout` | none | `204`; revokes every token issued to the user so far |
| GET | `/auth/me` | none | The signed-in user |
| GET, POST | `/users` | `{email, full_name, mobile, role, password?}` (admin) | Admins must have a password, officers must not; `409` on a duplicate email or mobile |

Sign-in codes use the same `OtpService` as guest registration (purposes `ADMIN_2FA` and
`OFFICER_LOGIN`), so they share its expiry, attempt limit, cooldown, per-number and per-IP caps
and daily SMS budget.

## Events — `app/modules/events/router.py`

| Method & path | Access | Notes |
|---|---|---|
| `GET /events` | admin: all; officer: assigned only | Query: `limit` (1–100, default 20), `offset` (≥0), `search`, `upcoming` (bool) |
| `POST /events` | admin | Body: `EventCreate`. `201` with the created event. `422` on validation error (e.g. `starts_at` not in the future) |
| `GET /events/{event_id}` | admin; officer if assigned | `404` if missing, soft-deleted, or an officer is not assigned |
| `PATCH /events/{event_id}` | admin | Body: `EventUpdate` (all fields optional; only fields present are changed). `422` if a required field is explicitly set to `null`, or the date rules are violated |
| `DELETE /events/{event_id}` | admin | Soft delete. `204 No Content` |

`EventRead` fields: `id, title, description, location, starts_at, ends_at, capacity, created_at, updated_at, created_by, updated_by`.

## Guest registration (public) — `app/modules/guests/router.py`

No authentication; a verified OTP is the guest's only credential. Every response here sets
`Cache-Control: no-store`.

| Method & path | Notes |
|---|---|
| `GET /public/events/{event_id}` | Returns `PublicEventInfo`: event basics plus `registration_open` and `seats_left`. `404` if the event doesn't exist or is deleted (no distinction) |
| `POST /public/events/{event_id}/registrations` | Body: `RegistrationCreate` (`guest_name`, `mobile`, `consent: true`). Creates (or resumes, if still `PENDING_OTP`) a registration and sends an OTP. `202 Accepted` with `OtpSent`. `409` if the event is full or registration is closed |
| `POST /public/registrations/{registration_id}/otp` | Resends an OTP for an existing registration (its `public_id` UUID in the path). `202` with `OtpSent`. `429` with `Retry-After` if throttled |
| `POST /public/registrations/{registration_id}/verify` | Body: `OtpVerify` (`code`, 6 digits). On success returns `GuestPass` (includes `qr_token` and `qr_svg`, a data URI) and issues/replaces the QR pass. `400` if the code is wrong, expired or already used; `409` if the event filled in the meantime or the registration is already checked in |

`registration_id` in the path is validated as a UUID (`^[0-9a-f]{8}-...$`) before it reaches the
service layer.

**Not yet implemented**: a guest-facing "my registration" / "my pass" lookup endpoint, a cancel
endpoint, and a separate reissue endpoint (verifying again already reissues the pass — see
[`BUSINESS_RULES.md`](./BUSINESS_RULES.md)).

## Gate — `app/modules/gate/router.py`

Access: admin (any event) or security officer assigned to the event (`404` otherwise — see
[`RBAC.md`](./RBAC.md)). Every response sets `Cache-Control: no-store`.

| Method & path | Notes |
|---|---|
| `POST /gate/events/{event_id}/scan` | Body: `ScanRequest` (`token`, optional `gate` name). Always `200 OK`; `result` is one of `admitted`, `already_checked_in`, `wrong_event`, `invalid`, `gate_closed`. `guest` (name + masked mobile) is included only for `admitted`/`already_checked_in` |
| `GET /gate/events/{event_id}/entries` | Query: `limit` (1–100, default 50), `offset`. Returns the check-in log for the event: guest, `checked_in_at`, `gate`, `officer_id` |

**Not yet implemented**: `POST /gate/manual-check-in` (admin fallback for when scanning is
unavailable) — described in `event-management.md` but not on `main` yet.

## Errors

Route-level handlers translate domain exceptions to HTTP status codes per module (see each
router's `_to_http`/exception mapping); there is no app-wide error envelope yet (the
`{"error": {code, message, request_id}}` shape in `event-management.md` is a target, not current
behaviour) — FastAPI's default `{"detail": "..."}` body is what callers get today.

## Not yet implemented anywhere

Refresh tokens (`/auth/refresh`), editing or deactivating staff accounts, event
publish/close/cancel actions, guest-list/export/stats endpoints, and the audit-log read endpoint
— all described in [`event-management.md`](./event-management.md#4-api) as the target API but
absent from `main`.
