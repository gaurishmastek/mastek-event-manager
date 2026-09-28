# Deployment

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4). This file did not exist in the repo
before. There is currently **no deployment tooling in the repository** — no Dockerfile, no
docker-compose, no CI/CD workflow. This document covers what exists today (how to run the
backend locally) and what is still missing before it could be deployed.

## Requirements

- Python 3.11 (`pyproject.toml` targets `py311`)
- MySQL (any recent version reachable via `pymysql`)
- Python packages: `backend/requirements.txt` (runtime) and `backend/requirements-dev.txt`
  (adds `pytest`, `httpx`, for the test suite)

## Configuration

All runtime configuration is a single `pydantic-settings` class,
`app/core/config.py::Settings`, read from environment variables or a local `.env` file
(`backend/.env`, git-ignored). Key variables:

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` \| `test` \| `production` |
| `DATABASE_URL` | `mysql+pymysql://mastek:mastek@localhost:3306/mastek_events` | |
| `SECRET_KEY` | dev placeholder | HMAC key for OTP hashes, mobile/IP hashes. **Must** be a random ≥32-char value in production |
| `PII_ENCRYPTION_KEY` | dev placeholder | Fernet key for encrypting guest mobiles at rest. **Must** be set in production |
| `SMS_PROVIDER` | `disabled` | `disabled` \| `console`. `console` prints OTPs to stdout and is refused when `ENVIRONMENT=production` |
| `OTP_TTL_SECONDS`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN_SECONDS`, `OTP_MAX_PER_MOBILE_PER_HOUR`, `OTP_MAX_PER_MOBILE_PER_DAY`, `OTP_MAX_PER_IP_PER_HOUR`, `SMS_DAILY_BUDGET` | see `config.py` | OTP/anti-abuse tuning — see [`SECURITY.md`](./SECURITY.md) |
| `GATE_OPENS_MINUTES_BEFORE_START`, `GATE_CLOSES_HOURS_AFTER_START_IF_NO_END` | `180`, `12` | Gate scanning window — see [`BUSINESS_RULES.md`](./BUSINESS_RULES.md) |

The app **refuses to start** with `ENVIRONMENT=production` if `SECRET_KEY` or
`PII_ENCRYPTION_KEY` are still the checked-in dev defaults, or if `SMS_PROVIDER=console` — see
[`SECURITY.md`](./SECURITY.md).

## Running locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# create backend/.env with at least DATABASE_URL pointing at a running MySQL instance
alembic upgrade head
uvicorn app.main:app --reload
```

Tests: `pytest` (from `backend/`), configuration in `backend/pytest.ini`.

## Database migrations

Alembic, `backend/alembic/`, two migrations so far (`create_events`,
`guest_passes_and_gate` — see [`DATABASE.md`](./DATABASE.md)). Every schema change must go
through a migration; there is no `create_all()`/auto-sync path in the app itself.

## What is missing for a real deployment

None of the following exist in the repository yet:

- A Dockerfile or container image build.
- A docker-compose (or equivalent) file to run the app alongside MySQL.
- A CI workflow (tests, lint, `pip-audit`, `bandit`, `gitleaks`, dependency updates).
- Reverse-proxy / process-manager configuration (the app currently trusts `request.client.host`
  directly for OTP rate limiting by IP — running behind a proxy needs
  `--proxy-headers --forwarded-allow-ips` on uvicorn, noted as a comment in
  `guests/router.py::_client_ip`, but nothing wires that up yet).
- Any HTTPS/TLS termination, CORS or security-header configuration (see
  [`SECURITY.md`](./SECURITY.md)).
- A real SMS provider integration — `SMS_PROVIDER` only supports `disabled` (delivery always
  fails) and `console` (dev-only, prints to stdout).
- Deployment of the auth module — since it does not exist yet, there is no way to actually sign
  in as an admin or officer once deployed (see [`RBAC.md`](./RBAC.md)).

`docs/event-management.md` describes the intended production posture; this file will be filled
in as deployment tooling actually lands in the repo.
