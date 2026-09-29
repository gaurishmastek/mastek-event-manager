# Deployment

Status: reflects the repository as of 2026-09-28. `vercel.json` deploys the Angular frontend and
FastAPI backend together on Vercel. MySQL remains an external managed service; there is no
Dockerfile, docker-compose file, or CI/CD workflow in the repository.

## Requirements

- Python 3.11 (`pyproject.toml` targets `py311`)
- MySQL (any recent version reachable via `pymysql`)
- Python packages: `backend/requirements.txt` (runtime) and `backend/requirements-dev.txt`
  (adds `pytest`, `httpx`, for the test suite)

## Configuration

All runtime configuration is a single `pydantic-settings` class,
`app/core/config.py::Settings`, read from environment variables or a local `.env` file
(`backend/.env`, git-ignored). The file is located from the code (`config.py::DEFAULT_ENV_FILE`), not the working
directory, so it is read the same way from `backend/`, the repository root or `backend/api/index.py`; a missing file is
ignored. Environment variables always win over the file, which is how Vercel and any other deployment should set values.
`APP_ENV_FILE` points at a different file, or set it empty to read none (the test suite does). Settings are read once
at import: restart the process after changing `.env` or the environment (`uvicorn --reload` does not watch `.env`).
Key variables:

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` \| `test` \| `production` |
| `DATABASE_URL` | `mysql+pymysql://mastek:mastek@localhost:3306/mastek_events` | |
| `SECRET_KEY` | dev placeholder | Signs staff access tokens; HMAC key for OTP and PII hashes. **Must** be a random ≥32-char value in production |
| `PII_ENCRYPTION_KEY` | dev placeholder | Fernet key for encrypting guest emails at rest. **Must** be set in production |
| `EMAIL_PROVIDER` | `disabled` | `disabled` \| `console` \| `smtp` \| `mailtrap`. `console` prints OTPs to stdout and is refused in production. With `smtp`: set `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_SECURITY` (`starttls`, `ssl`, or `none`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_TIMEOUT_SECONDS` (default 10). With `mailtrap`: set `EMAIL_FROM` and `MAILTRAP_API_TOKEN` (secret), optionally `MAILTRAP_CATEGORY` (default `Mastek Event Manager`); see "Mailtrap" below |
| `OTP_TTL_SECONDS`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN_SECONDS`, `OTP_MAX_PER_EMAIL_PER_HOUR`, `OTP_MAX_PER_EMAIL_PER_DAY`, `OTP_MAX_PER_IP_PER_HOUR`, `EMAIL_DAILY_BUDGET` | see `config.py` | OTP/anti-abuse tuning — see [`SECURITY.md`](./SECURITY.md) |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `OFFICER_SESSION_MINUTES` | `30`, `480` | Admin and officer session lengths |
| `MAX_FAILED_LOGIN_ATTEMPTS`, `LOCKOUT_MINUTES` | `5`, `15` | Admin password lockout |
| `CORS_ORIGINS` | `http://localhost:4200` | Comma-separated frontend origins allowed to call the API |
| `GATE_OPENS_MINUTES_BEFORE_START`, `GATE_CLOSES_HOURS_AFTER_START_IF_NO_END` | `180`, `12` | Gate scanning window — see [`BUSINESS_RULES.md`](./BUSINESS_RULES.md) |

The app **refuses to start** with `ENVIRONMENT=production` if `SECRET_KEY` or
`PII_ENCRYPTION_KEY` are still the checked-in dev defaults, or if `EMAIL_PROVIDER=console` — see
[`SECURITY.md`](./SECURITY.md). `EMAIL_PROVIDER=smtp` requires `SMTP_HOST` and `EMAIL_FROM` at startup; `EMAIL_PROVIDER=mailtrap` requires
`MAILTRAP_API_TOKEN` and `EMAIL_FROM`.

## Running locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# create backend/.env with at least DATABASE_URL pointing at a running MySQL instance
alembic upgrade head
EMAIL_PROVIDER=console uvicorn app.main:app --reload
```

Tests: `pytest` (from `backend/`), configuration in `backend/pytest.ini`. Set `TEST_MYSQL_URL` to a disposable
MySQL database to also run the row-locking and MySQL migration tests. Frontend: `npm run build` and
`npm run test:ci` (from `frontend/`).

## Mailtrap

`EMAIL_PROVIDER=mailtrap` sends OTPs and notifications through the Mailtrap Email API with the official `mailtrap`
SDK (already in `requirements.txt`; `pip install -r requirements.txt` installs it).

1. In Mailtrap, add and verify a sending domain (SPF, DKIM and DMARC records), or use the demo domain Mailtrap gives a
   new account for a first test (it only delivers to the account owner's own address).
2. Create an API token with access to that domain at <https://mailtrap.io/settings/api-tokens>.
3. Set, in `backend/.env` or the deployment's environment (never in code):

   ```text
   EMAIL_PROVIDER=mailtrap
   MAILTRAP_API_TOKEN=<your API token>
   EMAIL_FROM="Mastek Events <no-reply@your-verified-domain>"
   ```

4. Restart the backend, then `python -m app.cli email-config` (shows `mailtrap_api_token_configured: True`, never the
   token) and `python -m app.cli send-test-email --to you@example.com`.
5. Check delivery status for every message in Mailtrap's email logs: <https://mailtrap.io/sending/email_logs>. Mail
   from this app is tagged with the category `MAILTRAP_CATEGORY`.

## Email troubleshooting

When codes don't arrive, the API answers `503` ("could not be sent") and the backend logs one warning per failure:

```text
Mailtrap delivery failed: kind=auth status=401 error=AuthorizationError sender=ev•••@example.com recipient=... reply='Unauthorized'
SMTP delivery failed: kind=auth stage=login code=535 error=SMTPAuthenticationError host=... port=587 security=starttls
sender=ev•••@example.com recipient=as•••@example.com reply='5.7.8 Incorrect authentication data'
```

The log never holds the password, the code, the message body or a full address (provider replies have addresses
replaced by `<address>`). A failed send saves nothing and does not count against the OTP rate limits.

1. **Check the effective settings**: `python -m app.cli email-config` (from `backend/`, or with `PYTHONPATH=backend`
   from the root). It shows the `.env` file used, the provider, host, port, security mode, masked sender and username,
   and whether a password is set. `email_provider: disabled` means the file was not found or the variable is not set;
   the log then says `EMAIL_PROVIDER is disabled`.
2. **Restart** the backend after any change.
3. **Read the `kind`** in the warning:

| kind | Meaning | What to check |
|---|---|---|
| `not_configured` | Provider is `disabled` | `.env` location, `EMAIL_PROVIDER`, restart |
| `dns` | Host name did not resolve | `SMTP_HOST` spelling, DNS |
| `connect` | Refused, reset or closed | Port, firewall, ISP blocking outbound SMTP; `Test-NetConnection <host> -Port 587` (TCP only) |
| `timeout` | No answer in `SMTP_TIMEOUT_SECONDS` | Outbound SMTP blocked, wrong port for the security mode |
| `tls` | STARTTLS missing, or the certificate failed verification | `SMTP_SECURITY` matches the port (587 `starttls`, 465 `ssl`); host name matches the certificate. Verification is never turned off |
| `auth` | Login rejected (usually 535) or no common auth mechanism | Username (often the full mailbox address) and password; rotate and update `.env` |
| `sender_rejected` | `MAIL FROM` refused (often 553/550) | `EMAIL_FROM` must be the authenticated mailbox or an alias it may send as |
| `recipient_rejected` | `RCPT TO` refused | Address exists; provider's relay rules for external recipients |
| `data_rejected` | Message refused after `DATA` (e.g. 554 relay denied, spam, quota); Mailtrap: another 4xx | Provider limits and content policy; the logged `reply` names the field |
| `rate_limited` | Mailtrap answered 429 | Sending too fast or over the plan's limit; wait and retry |

With Mailtrap, `auth` is a 401 (token missing, mistyped or revoked: check `MAILTRAP_API_TOKEN`), `sender_rejected` is
a 403 (the token has no access to the sending domain, or `EMAIL_FROM` is not on a verified domain), and `connect`,
`timeout` and `tls` are network failures reaching `send.api.mailtrap.io` over HTTPS.

4. **Accepted is not delivered.** No warning means the provider accepted the message. If it still does not arrive, it
   was filtered, bounced or put in spam after acceptance: check the recipient's spam folder and the mailbox's bounce
   messages, and make sure the sending domain has SPF, DKIM and DMARC records that cover the SMTP host.
5. A `429` or a `503` with no SMTP warning comes from the OTP limits (resend cooldown, per-address and per-IP caps,
   `EMAIL_DAILY_BUDGET`), not from email delivery.

## Database migrations

Alembic, `backend/alembic/` — see [`DATABASE.md`](./DATABASE.md) for the list.
`20260928_0004_registration_links` gives existing events a random `public_id` and keeps existing registrations and
their passes (they count as a party of one). Every schema change must go
through a migration; there is no `create_all()`/auto-sync path in the app itself.

## Frontend and API on Vercel

`vercel.json` at the repository root defines two builds:

- `backend/api/index.py` uses the Vercel Python runtime and exports the existing FastAPI `app`.
- `frontend/package.json` uses Vercel's static builder and serves Angular's
  `frontend/dist/frontend/browser` output.

Vercel's Python builder finds `backend/pyproject.toml`, uses its PEP 621 `[project]` metadata, and resolves its pinned
dependencies with `uv`. The root `requirements.txt` remains flat because Vercel's legacy requirements parser does not
support nested `-r` includes. `backend/tests/test_deployment.py` keeps both files synchronized with
`backend/requirements.txt`.

Requests under `/api/*` are routed to FastAPI. Static assets are served from the Angular build, and every other path
falls back to `frontend/index.html` so deep links such as `/admin` or `/register/<id>` load the app. The deployment
also sends the `Permissions-Policy: camera=(self)` and `X-Frame-Options: DENY` headers the gate scanner needs (see
below).

Vercel project settings: leave **Root Directory** empty (the repository root) and **Framework Preset** as "Other";
`vercel.json` overrides the build, install and output settings.

The production frontend calls the relative path `/api/v1` (`frontend/src/environments/environment.prod.ts`), so its
requests remain on the same Vercel origin and do not require a production CORS entry. Configure the backend variables
from the table above in every Vercel environment that will run the API. Production startup intentionally fails when
the secret, encryption, or email configuration is unsafe.

Vercel does not provide the MySQL database used by this application. Set `DATABASE_URL` to a network-accessible
managed MySQL instance and run `alembic upgrade head` against that database before directing users to a deployment.
Schema migrations are an explicit release step; the serverless function does not run them during startup.

## HTTPS and the gate camera

The gate scanner uses the phone's camera (`navigator.mediaDevices.getUserMedia`), which browsers only allow on
secure origins: serve the frontend over **HTTPS** in production. `http://localhost` works during development; a phone
opening `http://<laptop-ip>:4200` does not get a camera (the scanner says "Camera needs a secure connection") — use an
HTTPS tunnel or a local certificate for phone testing.

The server that serves the Angular build must send `Permissions-Policy: camera=(self)` and must not add a policy that
blocks the camera. Keep `X-Frame-Options: DENY` (or `frame-ancestors 'none'`): the scanner is never meant to run in a
frame.

Browser support: camera scanning works in current Chrome and Edge (Android, desktop), Safari on iOS 14.3+ and macOS,
and Firefox. Browsers with the native `BarcodeDetector` use it; others load the bundled `@zxing/browser` decoder on
demand. Officers can type or paste a pass code if no camera is available.

## What is missing for a real deployment

None of the following exist in the repository yet:

- A Dockerfile or container image build for non-Vercel deployment.
- A docker-compose (or equivalent) file to run the app alongside MySQL.
- A CI workflow (tests, lint, `pip-audit`, `bandit`, `gitleaks`, dependency updates).
- Reverse-proxy / process-manager configuration (the app currently trusts `request.client.host`
  directly for OTP rate limiting by IP — running behind a proxy needs
  `--proxy-headers --forwarded-allow-ips` on uvicorn, noted as a comment in
  `guests/router.py::_client_ip`, but nothing wires that up yet).
- Custom HTTPS/TLS termination for non-Vercel deployment (Vercel terminates HTTPS for its deployment domains).
- A production mail account. Set `EMAIL_PROVIDER=smtp` with the SMTP settings above (or `mailtrap`, see "Mailtrap"), and add SPF,
  DKIM and DMARC records on the sending domain so codes do not land in spam.
- Email delivery is needed before anyone can sign in outside development: admins and officers
  receive their sign-in codes by email. Create the first admin with
  `python -m app.cli create-admin --email ... --name ...` (optional `--mobile ...` for contact info only).

`docs/event-management.md` describes the intended production posture; this file will be filled
in as deployment tooling actually lands in the repo.
