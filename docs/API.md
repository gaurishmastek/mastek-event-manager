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
| POST | `/auth/login` | `{email, password}` (admins only) | `200 {challenge_id, resend_available_at}`; emails a 6-digit code. `401` for any wrong/unknown/locked/non-admin account |
| POST | `/auth/login/verify` | `{challenge_id, code}` | `200 {access_token, token_type, expires_in, user: {id, role, name}}`; `400` for a bad or expired code |
| POST | `/auth/officer/otp` | `{email}` | `202 {resend_available_at}`, the same for every address: unknown, inactive, deleted, admin and throttled requests all get it and no email is sent to them. A throttled officer gets a later `resend_available_at` instead of a `429`, because only real officers can be throttled. `503` if the email could not be sent |
| POST | `/auth/officer/verify` | `{email, code}` | Same session shape as `/auth/login/verify`, valid for one shift (`OFFICER_SESSION_MINUTES`, default 8 h) |
| POST | `/auth/logout` | none | `204`; revokes every token issued to the user so far |
| GET | `/auth/me` | none | The signed-in user |
| GET, POST | `/users` | `{email, full_name, mobile?, role, password?}` (admin) | Admins must have a password, officers must not; `409` on a duplicate email or mobile. `GET` takes an optional `role` filter (`?role=security_officer`). Responses (`UserRead`): `id, email, full_name, role, is_active, created_at, last_login_at`; never the password hash or mobile |

Sign-in codes use the same `OtpService` as guest registration (purposes `ADMIN_2FA` and
`OFFICER_LOGIN`), so they share its expiry, attempt limit, cooldown, per-email and per-IP caps
and daily email budget (`EMAIL_DAILY_BUDGET`, default 2000).

## Events — `app/modules/events/router.py`

| Method & path | Access | Notes |
|---|---|---|
| `GET /events` | admin: all; officer: assigned only | Query: `limit` (1–100, default 20), `offset` (≥0), `search`, `upcoming` (bool) |
| `POST /events` | admin | Body: `EventCreate`. `201` with the created event. `422` on validation error (e.g. `starts_at` not in the future) |
| `GET /events/{event_id}` | admin; officer if assigned | `404` if missing, soft-deleted, or an officer is not assigned |
| `PATCH /events/{event_id}` | admin | Body: `EventUpdate` (all fields optional; only fields present are changed). `422` if a required field is explicitly set to `null`, or the date rules are violated |
| `DELETE /events/{event_id}` | admin | Soft delete. `204 No Content` |
| `GET /events/{event_id}/officers` | admin | User ids of the officers assigned to the event |
| `PUT /events/{event_id}/officers/{user_id}` | admin | Assign. `204`; idempotent, restores a soft-deleted assignment, and safe when two admins assign at once. `404` for a missing event or a missing, inactive or deleted user; `422` if the user is not a `security_officer` |
| `DELETE /events/{event_id}/officers/{user_id}` | admin | Unassign (soft delete). `204`; `404` if not assigned. The officer loses the event, its scanner and its entry list on their next request |

`EventRead` fields: `id, public_id, title, description, location, starts_at, ends_at, capacity,
max_guests_per_registration, created_at, updated_at, created_by, updated_by, gate_opens_at, gate_closes_at`
(the last two are computed from the gate window settings; see [`BUSINESS_RULES.md`](./BUSINESS_RULES.md)). `EventCreate`/`EventUpdate` accept
`max_guests_per_registration` (whole number 0–10, default 5); `public_id` is server-generated and cannot be sent.

## Event registrations (admin) — `app/modules/guests/admin_router.py`

| Method & path | Access | Notes |
|---|---|---|
| `GET /events/{event_id}/registrations` | admin only (officers `403`, no token `401`) | Query: `limit` (1–100, default 20), `offset`, `search` (employee id or name, wildcards literal), `status` (`PENDING_OTP` \| `VERIFIED` \| `CHECKED_IN` \| `DECLINED`). `404` for a missing or deleted event. `Cache-Control: no-store` |

Each item: `registration_id` (public UUID), `employee_id`, `employee_name`, `email_masked`, `mobile_masked`,
`attending`, `family_attending`, `guest_names` (adult first, then kids), `adult_name`, `kid_names`, `kid_ages`, `food_preference`,
`number_of_guests`, `party_size`, `status`, `verified_at`, `qr_issued`, `qr_issued_at`,
`checked_in_at`, `created_at`. Newest first. Never included: the QR token or its hash, OTP data, and full or
encrypted email/mobile.

## Guest registration (public) — `app/modules/guests/router.py`

No authentication; a verified OTP is the employee's only credential. Events are addressed by their `public_id`
UUID from the registration link, never the numeric id (a non-UUID path segment is `422`). Every response here sets
`Cache-Control: no-store`.

| Method & path | Notes |
|---|---|
| `GET /public/events/{event_public_id}` | Returns `PublicEventInfo`: `public_id`, title, description, location, times, `max_guests_per_registration`, `registration_open` and `seats_left` (people). No internal id. `404` if the event doesn't exist or is deleted (no distinction) |
| `POST /public/events/{event_public_id}/registrations` | Body: `RegistrationCreate` (`employee_id`, `employee_name`, `email`, optional `mobile`, `attending`, and when attending `family_attending`, `accompanying_adult`, `adult_name`, `accompanying_kids`, `kid_names`, `kid_ages`, `food_preference`; `consent: true`). `mobile` may be omitted, null or blank; a provided number must be a valid Indian mobile. Inapplicable fields must be omitted, null, false or empty; see [`BUSINESS_RULES.md`](./BUSINESS_RULES.md#registration-and-otp) for the combinations that are `422`. Creates (or updates, if still `PENDING_OTP`) a registration and emails an OTP. `202 Accepted` with `OtpSent` (includes masked email). `409` if the party doesn't fit, registration is closed, or the employee id/email is taken by another registration; `422` for invalid input or more guests than the event allows |
| `POST /public/registrations/{registration_id}/otp` | Resends an OTP for an existing registration (its `public_id` UUID in the path). `202` with `OtpSent`. `429` with `Retry-After` if throttled |
| `POST /public/registrations/{registration_id}/verify` | Body: `OtpVerify` (`code`, 6 digits). For an employee who is not attending, records the decline and returns `AttendanceDeclined` (`status: "DECLINED"`, `attending: false`, `employee_id`, `employee_name`, `event`, `verified_at`; no seat, no QR). Otherwise reserves seats for the whole party and returns `GuestPass` (`attending: true`, `employee_id`, `employee_name`, `guest_names`, `adult_name`, `kid_names`, `kid_ages`, `food_preference`, `party_size`, `event`, `qr_token`, `qr_svg` data URI, `issued_at`), issuing or replacing the QR pass. `400` if the code is wrong, expired or already used; `409` if the party no longer fits or the registration is already checked in; `422` if the admin has since lowered the guest limit below the party |

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
| `POST /gate/events/{event_id}/scan` | Body: `ScanRequest` (`token`, optional `gate` name; any other field, such as a client check-in time, is `422`). Always `200 OK`; `result` is one of `admitted`, `already_checked_in`, `wrong_event`, `invalid`, `gate_closed`. `guest` is included only for `admitted`/`already_checked_in`: `name` (employee), `contact` (masked), `employee_id`, `guest_names`, `party_size`, `email_masked`, `mobile_masked`; `admitted` returns the server-generated `checked_in_at` and `gate`; `already_checked_in` fills them from the original entry |
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
publish/close/cancel actions, export/stats endpoints, and the audit-log read endpoint
— all described in [`event-management.md`](./event-management.md#4-api) as the target API but
absent from `main`.
