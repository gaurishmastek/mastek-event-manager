# Architecture

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4). Scope: the event, guest
registration/OTP/QR, and gate-scanning module only. This file did not exist in the repo before.

## Shape

A single FastAPI backend (`backend/app`), modular monolith, one MySQL database. No frontend or
separate services exist yet.

```text
backend/app/
  core/       settings, crypto, mobile-number helpers — shared by every module
  db/         SQLAlchemy base, audit/soft-delete mixin, session factory
  modules/
    auth/     staff sign-in (admin password + SMS code, officer SMS code), tokens, role dependencies
    users/    staff accounts (admins and security officers)
    events/   event CRUD, officer-to-event scoping
    guests/   public registration, OTP verification, QR pass issuance
    otp/      OTP generation, delivery and rate limiting (used by guest registration and staff sign-in)
    gate/     pass scanning and check-in, officer event-scope enforcement
  main.py     FastAPI app, mounts each module's router under /api/v1
```

Each feature module follows the same three layers:

- **`router.py`** — FastAPI routes: request/response models, HTTP status codes, translates
  domain exceptions to `HTTPException`. No business logic.
- **`service.py`** — the business rules (capacity checks, OTP issuing/verification, scan
  outcomes). Raises plain domain exceptions (`EventNotFoundError`, `EventFullError`, etc.);
  never raises `HTTPException` itself.
- **`repository.py`** (events, guests) — SQLAlchemy queries, including officer scoping
  (`WHERE ... IN officer_events`). Keeps query construction out of the service layer.

`gate` also has `access.py` (`EventScopePolicy`), which both the gate service and any future
caller use to decide whether a user may act on a given event — the same officer-assignment check
`events/repository.py` applies to reads.

## Cross-module dependencies

```text
guests/service.py --> otp/service.py   (send + verify OTP)
guests/service.py --> events/repository.py, events/models.py   (capacity, event lookup)
gate/service.py   --> guests/models.py, guests/repository.py   (find registration by QR token hash)
gate/service.py   --> events/repository.py, gate/access.py     (officer scope)
```

`events`, `guests` and `gate` all depend on `auth/dependencies.py` only for `CurrentUser` and
`require_roles(...)` — none of them depend on how a user is authenticated.

## Key design choices

- **Soft delete and audit, uniformly.** `db/mixins.py::AuditMixin` adds
  `created_at/by`, `updated_at/by`, `deleted_at/by` to `Event`, `OfficerEvent`, `Registration`
  and `CheckIn`. Repositories filter out `deleted_at IS NOT NULL` rows; nothing is hard-deleted.
  `OtpChallenge` and `ScanAttempt` are append-only logs instead (see
  [`DATABASE.md`](./DATABASE.md)) and do not carry the mixin.
- **No PII on the wire or in the QR code.** The QR pass encodes only a random opaque token
  (`guests/qr.py::new_pass_token`); the database stores only its SHA-256 hash. Guest mobiles are
  kept three ways — HMAC for lookup/uniqueness, Fernet-encrypted for sending OTPs, and a masked
  copy for display (`core/crypto.py`, `core/mobile.py`).
- **Capacity is enforced with a row lock, not a counter column.** There is no
  `registered_count` column on `events`. Seats taken are computed on demand
  (`RegistrationRepository.count_seats_taken`), and `GuestRegistrationService.verify` takes
  `EventRepository.get_for_update` (`SELECT ... FOR UPDATE`) before re-checking the count, so
  concurrent verifications cannot oversell an event.
- **Officer scope is enforced in the query, not filtered afterwards.** Both
  `events/repository.py` (list/get) and `gate/access.py::EventScopePolicy` restrict by
  `officer_events` membership at the SQL level; an officer asking for an event they are not
  assigned to gets a 404, not a 403, so they cannot tell it exists.
- **Deny by default.** `app/main.py` mounts every router except auth and the public guest routes
  behind `get_current_user`, and `tests/test_app.py` fails if any route outside `PUBLIC_ROUTES`
  answers without a token. Module tests can still override `get_current_user` (the `login_as`
  fixture) to exercise role logic without a sign-in round trip.
