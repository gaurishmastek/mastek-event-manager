# Mastek Event Manager: project instructions

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4). This file did not exist in the repo
before; it is created here as a short entry point. The full product spec is
[`docs/event-management.md`](./event-management.md) — read that first for rules, data model and
API detail. This file only orients a new contributor.

## What this is

A backend for running festival events (Navratri, Diwali and similar) in Mumbai: an admin creates
an event with a guest capacity, guests register on a public form and verify their email with OTP,
a QR pass is issued, and a security officer scans that pass at the gate to record entry.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2.x + Alembic + MySQL (`pymysql`), Python 3.11, `pydantic` v2
  for request/response validation, `cryptography` (Fernet) for PII at rest, `segno` for QR
  generation. See `backend/requirements.txt`.
- **Frontend**: Angular in `frontend/` (public registration, admin console, gate scanner).

## What is implemented on `main`

| Area | State |
|---|---|
| Event CRUD | Implemented — `app/modules/events` |
| Officer-to-event scoping | Implemented — `officer_events` table, managed through `/events/{id}/officers` |
| Guest registration, OTP, QR pass | Implemented — `app/modules/guests`, `app/modules/otp` |
| Gate scanning / check-in | Implemented — `app/modules/gate` |
| Admin login, officer login, sessions | Implemented — `app/modules/auth`, `app/modules/users`: admin password + email code, officer email code, JWT access tokens, logout. No refresh tokens yet. |

See [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md), [`docs/BUSINESS_RULES.md`](./BUSINESS_RULES.md),
[`docs/DATABASE.md`](./DATABASE.md), [`docs/RBAC.md`](./RBAC.md), [`docs/API.md`](./API.md),
[`docs/SECURITY.md`](./SECURITY.md) and [`docs/DEPLOYMENT.md`](./DEPLOYMENT.md) for what each of
those currently covers.

## Decisions already settled (see event-management.md "Open decisions" for history)

- Staff roles are `admin` and `security_officer` only — no `event_manager` role.
- Security officers see and scan only the events they are assigned to (`officer_events`).
- Guests have no accounts; a verified OTP is their only proof of identity.
