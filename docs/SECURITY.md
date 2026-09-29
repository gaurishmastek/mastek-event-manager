# Security

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4) — what the code actually does today.
Scope: the event, guest registration/OTP/QR, and gate-scanning module. This file did not exist
in the repo before. The threat model this was built against is
`security-review/SECURITY_DESIGN_REVIEW.md` in the project files; this document tracks what of
it has landed in code, not the full review.

## Staff authentication (`app/modules/auth`)

Staff sign in through `app/modules/auth` (see [`API.md`](./API.md#staff-auth--appmodulesauthrouterpy)):

- **Admin**: email and password (Argon2id, lockout after repeated failures), then a 6-digit code
  emailed to their account email.
- **Security officer**: a 6-digit code emailed to their account email. Officers have no password.

Both steps return a short-lived JWT access token. `get_current_user()` re-reads the user on every
request, so deactivation, deletion or a role change applies immediately, and `POST /auth/logout`
bumps the user's `session_version`, revoking every earlier token.

- Passwords: Argon2id via `argon2-cffi`, rehashed on login when parameters change; at least 12
  characters, not all letters or all digits.
- Password step: one generic `401` for unknown email, wrong password, locked, disabled or
  non-admin accounts, and a dummy hash check so unknown emails take the same time. The account
  locks for `LOCKOUT_MINUTES` after `MAX_FAILED_LOGIN_ATTEMPTS` wrong passwords.
- The `challenge_id` from the password step is a signed token of a different type from an access
  token, so it cannot be used as one, and it is only redeemable with that login's email code.
- Staff emails are the primary sign-in destination; staff mobiles are optional contact info only (stored as HMAC + Fernet-encrypted).
- `POST /auth/officer/otp` answers `202` with the same body for unknown, inactive, deleted and admin addresses and
  sends nothing to them. A throttled request for a real officer also gets `202` (with a later
  `resend_available_at`) rather than a `429`, since only real officers can be throttled and a `429` would reveal the
  account. An email outage still returns `503` for a real officer, which does reveal the account while the mail
  provider is down or the daily budget is spent.
- The officer sign-in page keeps the code only in component memory: it is not put in the URL, browser storage or logs.
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
  60s), a cap per email per hour and per day (default 5/10), a cap per IP per hour (default 20),
  and an app-wide daily email budget (default 2000) — the last is the defence against inbox flooding
  via the public form. All are configurable via `Settings` (`app/core/config.py`).
- A new OTP invalidates any earlier unconsumed code for the same `(purpose, subject_ref)`.
- A failed send rolls back the new challenge (and a new registration), so it neither leaves a usable code nor counts
  against the limits above. The API answers a generic `503`; the SMTP failure kind, stage and numeric code go to the
  log only, with the recipient and sender masked and addresses stripped from the provider's reply
  (`notifications/email.py`). STARTTLS and implicit TLS always verify the server certificate.
- **Not yet implemented**: CAPTCHA on the OTP-send step (`event-management.md` calls for one).

## Registration links

- Public links use the event's `public_id`, a random UUID4 generated server-side (122 bits), never the sequential
  database id, so registration pages cannot be enumerated. The public API accepts only a UUID-shaped id and returns no
  internal id, audit or staff fields.
- A pending registration can be edited by anyone who submits its employee id or email again, because nothing is
  verified yet; a verified registration can only be re-verified (pass reissue) by submitting both its employee id and
  its email, and then only through a code sent to that email. Mismatches get a generic `409` without the masked
  address.

## QR pass tokens (`app/modules/guests/qr.py`)

- The token is `secrets.token_urlsafe(32)` — 256 bits of randomness, generated server-side.
- The QR code encodes only that token; no guest name, email, event id or database id.
- Only `SHA-256(token)` is stored (`registrations.qr_token_hash`, unique); the plaintext token is
  never persisted, only returned once at issuance.
- Gate lookups go token → hash → registration; a stolen QR image without the underlying secret
  reveals nothing about who it belongs to.
- One pass per party. Party details (employee id and name, guest names, party size, masked email and mobile) are
  returned only to an admin or an assigned officer, and only for `admitted` or `already_checked_in` scans.

## Gate camera (frontend `gate/camera.ts`, `gate/scanner.component.ts`)

- The camera is requested only after an explicit tap, and only in a secure context (HTTPS, or `localhost` in
  development); browsers refuse `getUserMedia` elsewhere. All tracks are stopped when scanning stops, on leaving the
  page, on sign-out and when the page is hidden.
- QR decoding runs in the browser. No frame is uploaded or stored; only the decoded token is sent, after a format
  check. The QR holds nothing but the opaque token, so nothing in it is trusted: the backend decides the outcome.
- Party details are shown only for `admitted` and `already_checked_in` responses; wrong-event, invalid, gate-closed
  and out-of-scope scans show none.

## PII handling (`app/core/crypto.py`)

- Guest email addresses are stored three ways: `email_hash` (HMAC-SHA256, keyed by
  `secret_key`, for lookup and the uniqueness constraint — not reversible), `email_encrypted`
  (Fernet, keyed by `pii_encryption_key`, decrypted only to send an OTP), and `email_masked`
  (`as•••@example.com`, for anything shown to staff). Full emails are never returned by any API
  response in this module.
- Employee mobile numbers get the same treatment: `mobile_hash` (HMAC), `mobile_encrypted` (Fernet) and
  `mobile_masked` (`98•••••210`). Nothing decrypts them today; OTPs go by email only.
- The admin registrations list returns only masked email and mobile, never the QR token or hash, OTP data or
  ciphertext. Guest names and employee ids are stored in clear, as the gate and admins need to read them.
- `keyed_hash` is HMAC (not plain SHA-256) specifically because emails are relatively low-entropy —
  an unkeyed hash would be brute-forceable from a leaked table.
- **Not yet implemented**: the scheduled retention job that anonymises names, guest names, email and mobile
  fields some time after the event (`event-management.md` default: 30 days). Soft-deleted rows
  currently keep their personal data indefinitely.

## Input validation

- Every request model uses `ConfigDict(extra="forbid", str_strip_whitespace=True)` — unknown
  fields are rejected rather than silently ignored.
- Free-text fields (`title`, `location`, `employee_name`, guest names, `gate`) reject control characters and
  embedded newlines (`events/schemas.py::_clean_single_line`), so they can't be used to inject
  log lines or break single-line display contexts.
- `starts_at`/`ends_at` require an explicit timezone offset and are normalized to naive UTC
  server-side — no ambiguous local-time interpretation.
- Guest email addresses are validated with `pydantic.EmailStr` before anything else touches them.
- Employee ids are limited to letters, digits, `-`, `_` and `.`; mobiles must be valid Indian numbers; the guest
  count must be a whole number (booleans and strings are rejected) that matches the number of guest names.
- QR tokens are pattern-validated (`^[A-Za-z0-9_-]{20,128}$`) before a database lookup is even
  attempted.
- All database access goes through SQLAlchemy's ORM/Core query builder — no raw string-built SQL
  in this module.

## Production configuration guard rails (`app/core/config.py`)

`Settings._refuse_unsafe_production_config` makes the app refuse to start when
`environment == "production"` and any of the following still hold:

- `secret_key` is still the checked-in development default, or shorter than 32 characters.
- `pii_encryption_key` is still the checked-in development default.
- `email_provider == "console"` (which prints OTPs to stdout — `notifications/email.py::ConsoleEmailSender`).

## Not yet implemented

- SPF, DKIM and DMARC on the sending domain. `EMAIL_PROVIDER=smtp` sends over STARTTLS or implicit
  TLS (`SMTP_SECURITY=none` is refused in production), and `EMAIL_PROVIDER=mailtrap` over HTTPS with a verified
  certificate, but deliverability depends on the domain's DNS. `MAILTRAP_API_TOKEN` is a secret like `SMTP_PASSWORD`:
  environment only, never logged (`email-config` reports only whether it is set).
- A Content-Security-Policy. `app/main.py` sets `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Cache-Control: no-store` and `Permissions-Policy: camera=(self), microphone=(), geolocation=()`
  (plus HSTS in production), restricts CORS to `CORS_ORIGINS`, and turns off `/docs` and `/openapi.json` in
  production. The web server that serves the Angular app must send the same `Permissions-Policy` (see
  [`DEPLOYMENT.md`](./DEPLOYMENT.md)); the API's header does not cover the app's own pages.
- Refresh tokens: the frontend keeps the access token in memory, so a page reload signs out.
- Per-IP rate limiting on the password step (the per-account lockout is in place); best done at
  the reverse proxy.
- CAPTCHA on public registration/OTP endpoints.
- CI-run `pip-audit`/`bandit`/`gitleaks`, and alerting on OTP failure spikes, email send failures or
  repeated invalid scans.
- A dedicated `audit_log` table (see [`DATABASE.md`](./DATABASE.md)) — today's audit trail is
  each table's own `created_by`/`updated_by`/`deleted_by` plus the `scan_attempts` log.

All of the above are tracked as intent in `security-review/SECURITY_DESIGN_REVIEW.md` and
`docs/event-management.md`; this file will move items up as they land.
