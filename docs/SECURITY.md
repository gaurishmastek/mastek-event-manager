# Security

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4) — what the code actually does today.
Scope: the event, guest registration/OTP/QR, and gate-scanning module. This file did not exist
in the repo before. The threat model this was built against is
`security-review/SECURITY_DESIGN_REVIEW.md` in the project files; this document tracks what of
it has landed in code, not the full review.

## Authentication: not implemented — fails closed

`app/modules/auth/dependencies.py::get_current_user` unconditionally raises `401`. No login,
password storage, token issuance or session handling exists yet. This means every route guarded
by `require_roles(...)` is currently unusable end-to-end (see [`RBAC.md`](./RBAC.md)) — the
design deliberately keeps every protected route rejecting by default rather than open, until the
real auth module (admin password + 2FA, officer OTP login) lands.

## Guest OTP (`app/modules/otp`)

- Codes: 6 digits from `secrets.randbelow`, never returned in a response, never logged, stored
  only as `HMAC-SHA256(secret_key, "otp:{purpose}:{subject_ref}:{code}")`
  (`otp/service.py::_code_hmac`, keyed by `Settings.secret_key`).
- Verification uses `hmac.compare_digest` (constant-time comparison).
- Attempt counting is atomic (`UPDATE ... WHERE attempts < max_attempts`), so parallel guesses
  cannot exceed `otp_max_attempts` (default 5).
- Rate limits, all in `otp/service.py::_enforce_limits`: a resend cooldown per subject (default
  60s), a cap per mobile per hour and per day (default 5/10), a cap per IP per hour (default 20),
  and an app-wide daily SMS budget (default 2000) — the last is the defence against SMS pumping
  via the public form. All are configurable via `Settings` (`app/core/config.py`).
- A new OTP invalidates any earlier unconsumed code for the same `(purpose, subject_ref)`.
- **Not yet implemented**: CAPTCHA on the OTP-send step (`event-management.md` calls for one).

## QR pass tokens (`app/modules/guests/qr.py`)

- The token is `secrets.token_urlsafe(32)` — 256 bits of randomness, generated server-side.
- The QR code encodes only that token; no guest name, mobile, event id or database id.
- Only `SHA-256(token)` is stored (`registrations.qr_token_hash`, unique); the plaintext token is
  never persisted, only returned once at issuance.
- Gate lookups go token → hash → registration; a stolen QR image without the underlying secret
  reveals nothing about who it belongs to.

## PII handling (`app/core/crypto.py`, `app/core/mobile.py`)

- Guest mobile numbers are stored three ways: `mobile_hash` (HMAC-SHA256, keyed by
  `secret_key`, for lookup and the uniqueness constraint — not reversible), `mobile_encrypted`
  (Fernet, keyed by `pii_encryption_key`, decrypted only to send an OTP), and `mobile_masked`
  (`98•••••210`, for anything shown to staff). Full mobiles are never returned by any API
  response in this module.
- `keyed_hash` is HMAC (not plain SHA-256) specifically because mobile numbers are low-entropy —
  an unkeyed hash of a 10-digit Indian mobile would be brute-forceable from a leaked table.
- **Not yet implemented**: the scheduled retention job that anonymises `guest_name` and mobile
  fields some time after the event (`event-management.md` default: 30 days). Soft-deleted rows
  currently keep their personal data indefinitely.

## Input validation

- Every request model uses `ConfigDict(extra="forbid", str_strip_whitespace=True)` — unknown
  fields are rejected rather than silently ignored.
- Free-text fields (`title`, `location`, `guest_name`, `gate`) reject control characters and
  embedded newlines (`events/schemas.py::_clean_single_line`), so they can't be used to inject
  log lines or break single-line display contexts.
- `starts_at`/`ends_at` require an explicit timezone offset and are normalized to naive UTC
  server-side — no ambiguous local-time interpretation.
- Mobile numbers are restricted to the Indian numbering plan (`+91`, 10 digits starting 6–9)
  before anything else touches them — this also narrows the attack surface for OTP abuse via
  arbitrary international numbers.
- QR tokens are pattern-validated (`^[A-Za-z0-9_-]{20,128}$`) before a database lookup is even
  attempted.
- All database access goes through SQLAlchemy's ORM/Core query builder — no raw string-built SQL
  in this module.

## Production configuration guard rails (`app/core/config.py`)

`Settings._refuse_unsafe_production_config` makes the app refuse to start when
`environment == "production"` and any of the following still hold:

- `secret_key` is still the checked-in development default, or shorter than 32 characters.
- `pii_encryption_key` is still the checked-in development default.
- `sms_provider == "console"` (which prints OTPs to stdout — `otp/sms.py::ConsoleSmsSender`).

## Not yet implemented

- Any real SMS provider (`otp/sms.py::DisabledSmsSender` is the only non-dev option today — it
  always fails delivery).
- Security response headers (CSP, HSTS, `Referrer-Policy`, `Permissions-Policy`), CORS
  configuration, disabling `/docs`/`/openapi.json` in production — `app/main.py` currently
  mounts the routers with no middleware at all.
- CAPTCHA on public registration/OTP endpoints.
- CI-run `pip-audit`/`bandit`/`gitleaks`, and alerting on OTP failure spikes, SMS spend or
  repeated invalid scans.
- A dedicated `audit_log` table (see [`DATABASE.md`](./DATABASE.md)) — today's audit trail is
  each table's own `created_by`/`updated_by`/`deleted_by` plus the `scan_attempts` log.

All of the above are tracked as intent in `security-review/SECURITY_DESIGN_REVIEW.md` and
`docs/event-management.md`; this file will move items up as they land.
