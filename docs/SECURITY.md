# Security

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4) — what the code actually does today.
Scope: the event, guest registration/OTP/QR, and gate-scanning module. This file did not exist
in the repo before. The threat model this was built against is
`security-review/SECURITY_DESIGN_REVIEW.md` in the project files; this document tracks what of
it has landed in code, not the full review.

## Staff authentication (`app/modules/auth`)

Staff sign in through `app/modules/auth` (see [`API.md`](./API.md#staff-auth--appmodulesauthrouterpy)):

- **Admin**: email and password (Argon2id, lockout after repeated failures), then a 6-digit code
  texted to their registered mobile.
- **Security officer**: a 6-digit code texted to their registered mobile. Officers have no password.

Both steps return a short-lived JWT access token. `get_current_user()` re-reads the user on every
request, so deactivation, deletion or a role change applies immediately, and `POST /auth/logout`
bumps the user's `session_version`, revoking every earlier token.

- Passwords: Argon2id via `argon2-cffi`, rehashed on login when parameters change; at least 12
  characters, not all letters or all digits.
- Password step: one generic `401` for unknown email, wrong password, locked, disabled or
  non-admin accounts, and a dummy hash check so unknown emails take the same time. The account
  locks for `LOCKOUT_MINUTES` after `MAX_FAILED_LOGIN_ATTEMPTS` wrong passwords.
- The `challenge_id` from the password step is a signed token of a different type from an access
  token, so it cannot be used as one, and it is only redeemable with that login's SMS code.
- Staff mobiles are stored as an HMAC for lookup plus a Fernet-encrypted copy for sending codes.
- `POST /auth/officer/otp` answers the same for unknown numbers and sends nothing to them.
- Deny by default: only routes in `app/main.py::PUBLIC_ROUTES` answer without a token, enforced by
  `tests/test_app.py`.

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
- A Content-Security-Policy and `Permissions-Policy`. `app/main.py` already sets
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Cache-Control: no-store`
  (plus HSTS in production), restricts CORS to `CORS_ORIGINS`, and turns off `/docs` and
  `/openapi.json` in production.
- Refresh tokens: the frontend keeps the access token in memory, so a page reload signs out.
- Per-IP rate limiting on the password step (the per-account lockout is in place); best done at
  the reverse proxy.
- CAPTCHA on public registration/OTP endpoints.
- CI-run `pip-audit`/`bandit`/`gitleaks`, and alerting on OTP failure spikes, SMS spend or
  repeated invalid scans.
- A dedicated `audit_log` table (see [`DATABASE.md`](./DATABASE.md)) — today's audit trail is
  each table's own `created_by`/`updated_by`/`deleted_by` plus the `scan_attempts` log.

All of the above are tracked as intent in `security-review/SECURITY_DESIGN_REVIEW.md` and
`docs/event-management.md`; this file will move items up as they land.
