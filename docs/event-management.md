# Mastek Event Manager: product and API spec

Status: draft, 2026-09-28. This is the primary spec for the app. Where it and the code
disagree, the gaps are listed in [Open decisions](#open-decisions).

Mastek runs festival events in Mumbai (Navratri, Diwali and similar). Admins create an event
with a guest capacity, guests register through a public form and verify their mobile with an
OTP, they receive a QR pass, and security officers scan that pass at the gate to record entry.

```text
Admin creates event → sets capacity → public registration form → guest verifies by OTP
→ QR pass issued → officer logs in by OTP → officer scans QR → entry recorded
```

Out of scope: everything in the "Explicit exclusions" list of `AGENTS.MD` (ERP, inventory,
payroll, multi-tenant SaaS and so on). Ticket payments are also out of scope.

## 1. Roles

There are two staff roles with accounts and one anonymous actor.

| Role | How they sign in | What they can do |
|---|---|---|
| **Admin** | Password (Argon2id) plus a second factor (OTP or TOTP) | Everything: events, capacity, officer accounts, officer-to-event assignment, guest lists, reports, exports, audit log, manual check-in |
| **Security officer** | OTP to a pre-registered mobile; no self sign-up | See and scan only the events they are assigned to |
| **Guest** | No account. An OTP-verified session scoped to one registration | Register, verify, view or cancel their own registration and QR pass |

Permission matrix (backend enforced, default deny):

| Capability | Admin | Officer | Guest |
|---|---|---|---|
| Create, edit, cancel, soft-delete events; set capacity | ✅ | ❌ | ❌ |
| Create, deactivate officers; assign them to events | ✅ | ❌ | ❌ |
| List events | all | assigned only | published events via public API |
| View guest list, reports, exports | ✅ | ❌ | ❌ |
| Scan QR and check a guest in | ✅ | assigned events only | ❌ |
| See scanned guest's name and masked mobile | ✅ | on scan only | ❌ |
| Manual check-in (gate fallback) | ✅ | ❌ | ❌ |
| View or cancel own registration and pass | ❌ | ❌ | own only |
| Read audit log | ✅ | ❌ | ❌ |

Rules:
- Every route declares its required role or permission through a FastAPI dependency. A test
  fails any route that has none, unless it is on an explicit public allow-list.
- Officer scope is applied in the query (`WHERE event_id IN (assigned events)`), never by
  filtering afterwards. IDs in URLs are never treated as authorisation.
- Hiding a button in the frontend is not access control.

## 2. Business rules

### Events
- Fields: title, description, location, start and end time (stored as UTC, shown in IST),
  capacity (1 to 100,000), status.
- Status: `DRAFT → PUBLISHED → CLOSED`, or `CANCELLED` from any earlier state. Only
  `PUBLISHED` events accept registrations or appear in the public API.
- Capacity cannot be lowered below the number of seats already taken.
- Registration closes at event end, or earlier if the admin closes it.

### Registration and OTP
- The public form collects the minimum: guest name, Indian mobile (`+91`, 10 digits starting
  6 to 9), party size (default 1, admin-set maximum per event), and a consent checkbox with a
  short privacy notice. Consent time is stored.
- A new registration starts as `PENDING_OTP` and holds no seat. It expires after 10 minutes
  if not verified.
- One active registration per mobile per event.
- OTP: 6 digits from `secrets`, stored only as an HMAC, valid 5 minutes, 5 wrong attempts
  then invalid, 60 second resend cooldown, caps per mobile, per IP and a global daily SMS
  budget. A new OTP invalidates older ones for the same purpose. OTPs are never returned in a
  response, logged or audited.
- CAPTCHA on the "send OTP" step.
- On correct OTP the seat is taken atomically
  (`UPDATE events SET registered_count = registered_count + party_size WHERE id = :id AND registered_count + party_size <= capacity`,
  then check one row changed). If full, the registration fails with a clear "event full" message.

Registration states:

```text
PENDING_OTP → VERIFIED → CHECKED_IN
PENDING_OTP → EXPIRED
VERIFIED    → CANCELLED   (guest or admin; seat released)
```

### QR pass
- Issued only after OTP verification.
- The QR encodes only an opaque random token (`secrets.token_urlsafe(32)`), no personal data
  or IDs. Only the SHA-256 hash is stored.
- The token is bound to one registration and one event, and is valid from a set buffer before
  event start (default 2 hours) until event end.
- Re-issuing a pass (lost phone) needs a fresh OTP and invalidates the previous token.

### Check-in at the gate
- One atomic update: `status = CHECKED_IN` only where the token hash matches, the event is the
  officer's assigned event, and the status is `VERIFIED`. A unique constraint on
  `check_ins.registration_id` is the final guarantee against double entry.
- Scan outcomes shown to the officer: `OK` (with guest name, masked mobile and party size),
  `ALREADY_CHECKED_IN` (with time and gate), `WRONG_EVENT`, `NOT_YET_VALID`, `EXPIRED`,
  `CANCELLED`, `UNKNOWN`.
- Every scan attempt is logged, without the raw token.
- If scanning or SMS is down, the gate fails closed. The fallback is an admin-only manual
  check-in by name and masked mobile, recorded with `method = MANUAL`.

### Data retention and soft delete
- No hard deletes. Every table carries `created_at/by`, `updated_at/by`, `deleted_at/by`, and
  queries exclude soft-deleted rows.
- Guest personal data (name, mobile) is anonymised a set number of days after the event ends
  (default 30). The registration row stays for counts and audit; only the personal fields are
  nulled. This satisfies India's DPDP Act while keeping the "no permanent deletion" rule.
- Mobiles are shown masked (`98•••••210`) everywhere except when sending an OTP.

### Audit trail
Append-only audit entries for: event create, edit, cancel, delete and capacity change;
officer account and assignment changes; logins (success and failure); OTP sends and failures;
every scan outcome; manual check-ins; exports. Each entry records actor, action, target,
outcome, request ID and UTC timestamp. OTPs, QR tokens, passwords, JWTs and full mobiles are
never written to logs or audit.

## 3. Data model

MySQL via SQLAlchemy, every schema change through an Alembic migration. All tables below also
have the audit columns from `app/db/mixins.py::AuditMixin` unless marked append-only.

| Table | Key columns | Notes |
|---|---|---|
| `users` | id, role (`admin`, `security_officer`), name, email (admins), mobile_hash, mobile_enc, password_hash (admins), status (`ACTIVE`, `INACTIVE`, `LOCKED`), failed_logins | Staff only. Guests are not users. |
| `officer_events` | officer_id, event_id | Officer scope. Unique (officer_id, event_id). |
| `events` | id, public_id (UUID), title, description, location, starts_at, ends_at, capacity, max_party_size, registered_count, status | `capacity > 0`, `ends_at >= starts_at`, `registered_count <= capacity`. |
| `registrations` | id, public_id (UUID), event_id, guest_name, mobile_hash, mobile_enc, party_size, status, consent_at, verified_at, expires_at, anonymised_at | Unique (event_id, mobile_hash) for active rows. |
| `qr_passes` | id, registration_id, token_hash (unique), valid_from, valid_until, revoked_at | One active pass per registration. |
| `otp_challenges` | id, purpose (`GUEST_VERIFY`, `OFFICER_LOGIN`, `ADMIN_2FA`), subject_ref, code_hmac, expires_at, attempts, consumed_at | Append-only. |
| `check_ins` | id, registration_id (unique), event_id, officer_id, gate, method (`QR`, `MANUAL`), checked_in_at | Append-only entry log. |
| `scan_attempts` | id, officer_id, event_id, gate, outcome, created_at | Append-only. No raw token. |
| `sessions` | id, user_id, refresh_hash, expires_at, revoked_at | Staff refresh sessions, stored hashed. |
| `audit_log` | id, actor_type, actor_id, action, target_type, target_id, outcome, request_id, created_at | Append-only. |

## 4. API

FastAPI, versioned under `/api/v1`. JSON only. Errors use one envelope:
`{"error": {"code", "message", "request_id"}}`, with `401`, `403`, `404`, `409`, `422` and
`429`, and never a stack trace or SQL. Lists use `limit` (max 100) and `offset` and return
`{items, total, limit, offset}`. Staff routes and public routes are separate groups.

### Staff authentication

| Method and path | Access | Purpose |
|---|---|---|
| `POST /auth/login` | public, rate limited | Admin email and password, then returns a 2FA challenge |
| `POST /auth/login/verify` | public, rate limited | Admin second factor, issues tokens |
| `POST /auth/officer/otp` | public, rate limited | Sends login OTP to a registered officer mobile; same response whether or not the number exists |
| `POST /auth/officer/verify` | public, rate limited | Verifies officer OTP, issues a shift-bound session |
| `POST /auth/refresh` | refresh cookie + CSRF header | Rotates the refresh session |
| `POST /auth/logout` | staff | Revokes the session |
| `GET /auth/me` | staff | Current user and role |

Access tokens are short-lived (≤ 30 min) and kept in memory. Refresh tokens live in a
`Secure; HttpOnly; SameSite=Strict` cookie.

### Staff: users and assignments (admin)

| Method and path | Purpose |
|---|---|
| `GET, POST /users` | List or create officers and admins |
| `GET, PATCH /users/{id}` | Read or edit a staff account |
| `POST /users/{id}/deactivate` | Deactivate and revoke all sessions |
| `GET, PUT /events/{id}/officers` | Read or set officers assigned to an event |

### Staff: events

| Method and path | Access | Purpose |
|---|---|---|
| `GET /events` | admin: all; officer: assigned | List with `search`, `upcoming` |
| `POST /events` | admin | Create (starts as `DRAFT`) |
| `GET /events/{id}` | admin; officer if assigned | Read |
| `PATCH /events/{id}` | admin | Partial update, capacity rule applies |
| `POST /events/{id}/publish`, `/close`, `/cancel` | admin | Status changes |
| `DELETE /events/{id}` | admin | Soft delete |
| `GET /events/{id}/registrations` | admin | Guest list, masked mobiles, filter by status |
| `POST /events/{id}/registrations/{rid}/cancel` | admin | Cancel and release seat |
| `GET /events/{id}/check-ins` | admin | Entry log |
| `GET /events/{id}/stats` | admin; officer if assigned | Capacity, verified, checked in |
| `GET /events/{id}/export.csv` | admin | Export, audited, formula-injection safe |

### Gate (officer)

| Method and path | Access | Purpose |
|---|---|---|
| `POST /gate/scan` | officer (assigned event), admin | Body `{event_id, token, gate}`. Atomically checks in and returns the outcome |
| `POST /gate/manual-check-in` | admin | Fallback by registration, `method = MANUAL` |

### Public (guest)

Rate limited per IP, CAPTCHA on OTP send, `Cache-Control: no-store`.

| Method and path | Purpose |
|---|---|
| `GET /public/events/{public_id}` | Published event details and seats left (no internal IDs) |
| `POST /public/events/{public_id}/registrations` | Create a `PENDING_OTP` registration and send OTP |
| `POST /public/registrations/{public_id}/otp` | Resend OTP (cooldown and caps apply) |
| `POST /public/registrations/{public_id}/verify` | Verify OTP, take seat, issue pass and a guest session |
| `GET /public/registrations/me` | Own registration (guest session) |
| `GET /public/registrations/me/pass` | QR pass image (guest session) |
| `POST /public/registrations/me/cancel` | Cancel own registration |
| `POST /public/registrations/{public_id}/reissue` | Fresh OTP, then new pass; old one revoked |

### Audit

| Method and path | Access | Purpose |
|---|---|---|
| `GET /audit-logs` | admin | Filter by actor, action, target, date |

## 5. Security baseline

The detailed threat model is the security design review
(`security-review/SECURITY_DESIGN_REVIEW.md` in the project files). Must-haves from it:

- QR and OTP rules above, from the first commit.
- Secrets only from environment via `pydantic-settings`; `.env` is git-ignored and the app
  refuses to start in production with missing or default keys.
- Pydantic input models with `extra="forbid"`, length limits and strict types; ORM only, no
  string-built SQL; sort fields from an allow-list.
- CORS with an explicit origin list; HSTS, CSP, `nosniff`, `Referrer-Policy`,
  `Permissions-Policy: camera=(self)`; HTTPS everywhere (the camera scanner needs it).
- FastAPI `/docs` and `/openapi.json` off in production.
- CI runs tests, lint, `pip-audit`, `bandit` and `gitleaks`; Dependabot on.
- Alerts on SMS spend near budget, OTP failure spikes, repeated invalid scans and login
  failure spikes.

## 6. Build order

1. Auth and roles: admin login, officer accounts, officer-to-event assignment, default deny.
2. Events: CRUD, status, capacity (draft PR #1 covers most of the CRUD).
3. OTP service with a dev-only console provider and a real SMS adapter (TRAI DLT registered).
4. Public registration with atomic capacity.
5. QR pass issuance, then gate scanning and check-in.
6. Admin dashboard, reports and export.
7. Retention job, security headers, alerts, deployment.

Frontend: Angular + TypeScript + Tailwind + shadcn/ui, with three areas: public registration,
admin console and a mobile-first gate scanner.

## Open decisions

These are places where current code or earlier docs differ from this spec. The spec's choice
is listed first.

1. **Role names.** Spec: `admin` and `security_officer`. Draft PR #1 also has an
   `event_manager` role and names officers `security`. Proposed: drop `event_manager` and
   align names with the login-and-roles work.
2. **Officer read scope.** Spec: officers see only assigned events. Draft PR #1 lets any
   `security` user list and read all events; this changes once officer assignment lands.
3. **Event status and public ID.** Not in draft PR #1 yet; needed before the public form.
4. **Retention period** for guest personal data: 30 days after the event, to be confirmed.
5. **Admin second factor:** SMS OTP or authenticator app (TOTP). Spec allows either.
6. **Party size:** whether guests can bring companions on one pass, and the default maximum.
