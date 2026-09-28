# Business rules

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4) — what the code actually enforces
today, not the full target design. Scope: events, guest registration/OTP/QR, gate scanning. This
file did not exist in the repo before. For the intended end-state (event status workflow, party
size, retention job, audit trail) see [`docs/event-management.md`](./event-management.md); this
file calls out where current code differs from that spec.

## Events (`app/modules/events`)

- Fields: `title` (3–200 chars, single line), `description` (optional, ≤5000 chars, multi-line),
  `location` (2–255 chars, single line), `starts_at`, `ends_at` (optional), `capacity`
  (1–100,000). Timestamps must arrive with a timezone offset and are stored as naive UTC.
- `starts_at` must be in the future on create, and on update whenever it is changed.
- `ends_at`, if set, must not be before `starts_at`.
- Soft delete only (`DELETE /events/{id}` sets `deleted_at`/`deleted_by`); deleted events are
  excluded from list/get.
- **Not yet implemented**: an event status field (`DRAFT`/`PUBLISHED`/`CLOSED`/`CANCELLED`), a
  public event id separate from the database id, and a capacity floor tied to seats already
  taken (lowering capacity below registrations is not currently blocked by the events module —
  see [`BUSINESS_RULES.md` → Registration and OTP](#registration-and-otp) for how the guest flow
  handles this instead).

## Registration and OTP (`app/modules/guests`, `app/modules/otp`)

- Public form fields: `guest_name` (2–100 chars), `mobile` (Indian numbers only, normalized to
  `+91XXXXXXXXXX`), and `consent` (must be `true`).
- One registration per `(event, mobile)` pair, enforced by a unique constraint
  (`uq_registrations_event_mobile`); resubmitting the form for the same mobile while still
  `PENDING_OTP` updates the name/consent time and resends an OTP rather than creating a second
  row.
- Registration is only accepted while `now < (event.ends_at or event.starts_at)` — there is no
  separate "registration closes" time or admin action to close registration early yet.
- A seat is **not** held by an unverified registration — capacity is checked before sending the
  first OTP (`_ensure_seat_available`) and re-checked atomically at verification time under a
  row lock on the event, so only OTP-verified guests can fill an event and two concurrent
  verifications cannot oversell it. If the event fills between OTP send and verify, verification
  fails with "event full".
- OTP: 6 digits from `secrets`, stored only as an HMAC, default validity 300s
  (`otp_ttl_seconds`), 5 wrong attempts invalidate the code (`otp_max_attempts`), 60s resend
  cooldown, caps of 5/hour and 10/day per mobile, 20/hour per IP, and a 2000/day app-wide SMS
  budget — all configurable via `Settings` (`app/core/config.py`). A new OTP invalidates any
  earlier unconsumed one for the same subject. Codes are never included in a response, logged,
  or written anywhere but the HMAC.
- **Not yet implemented**: a fixed "registration expires N minutes after submission if not
  verified" timer (today an unverified `PENDING_OTP` row simply never reaches `VERIFIED`; it is
  not auto-expired), party size / multi-guest passes, and CAPTCHA on the OTP-send step.

## QR pass

- Issued only on successful OTP verification (`guests/service.py::verify`). Verifying again
  later (e.g. a guest who lost their pass) issues a fresh token and immediately replaces the
  stored hash — the previous token no longer matches any registration.
- The QR code encodes only a 256-bit random token (`secrets.token_urlsafe(32)`) — no guest name,
  mobile or event id. Only its SHA-256 hash is stored (`registrations.qr_token_hash`, unique).
- **Not yet implemented**: a pass-specific validity window (`valid_from`/`valid_until`); gate
  timing is currently computed per-event, not per-pass (see below).

## Check-in at the gate (`app/modules/gate`)

- A scan is accepted only when: the token hash matches an existing registration, that
  registration belongs to the event being scanned, the officer is admin or assigned to that
  event, and the current time is within the event's gate window. `check_ins.registration_id` is
  unique, so the database is the final guard against double entry even under a race.
- Gate window: opens `gate_opens_minutes_before_start` (default 180 minutes) before
  `starts_at`, and closes at `ends_at`, or `gate_closes_hours_after_start_if_no_end` (default 12
  hours) after `starts_at` when the event has no `ends_at`.
- Scan outcomes returned to the officer: `admitted`, `already_checked_in`, `wrong_event`,
  `invalid`, `gate_closed`. The response is always `200 OK`; only `admitted` means entry is
  allowed. An out-of-scope event yields `404` before a scan outcome is even produced.
- Every scan attempt (including invalid ones) is logged in `scan_attempts`, without the raw
  token. A successful scan also writes a `check_ins` row.
- **Not yet implemented**: an admin manual check-in fallback for when scanning is unavailable
  (`event-management.md` describes this; there is no `manual-check-in` endpoint on `main` yet).

## Soft delete and audit

- `events`, `officer_events`, `registrations` and `check_ins` use `AuditMixin`
  (`created_at/by`, `updated_at/by`, `deleted_at/by`); nothing is hard-deleted. `otp_challenges`
  and `scan_attempts` are append-only logs instead (see [`DATABASE.md`](./DATABASE.md)) and are
  never updated after creation except to record OTP consumption/invalidation.
- **Not yet implemented**: a scheduled retention job to anonymise guest personal data after the
  event (the spec's default is 30 days), and a dedicated `audit_log` table — the current audit
  trail is limited to each table's own `created_by`/`updated_by`/`deleted_by` columns plus the
  `scan_attempts` log.
