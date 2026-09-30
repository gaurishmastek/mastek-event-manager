# Business rules

Status: reflects `main` as of 2026-09-28 (PRs #1, #2, #4) — what the code actually enforces
today, not the full target design. Scope: events, guest registration/OTP/QR, gate scanning. This
file did not exist in the repo before. For the intended end-state (event status workflow, party
size, retention job, audit trail) see [`docs/event-management.md`](./event-management.md); this
file calls out where current code differs from that spec.

## Events (`app/modules/events`)

- Fields: `title` (3–200 chars, single line), `description` (optional, ≤5000 chars, multi-line),
  `location` (2–255 chars, single line), `starts_at`, `ends_at` (optional), `capacity`
  (1–100,000, counted in people), `max_guests_per_registration` (accompanying guests one employee may bring, 0–10,
  default 5). Timestamps must arrive with a timezone offset and are stored as naive UTC.
- Every event gets a random `public_id` (UUID4) on creation; clients cannot set or change it. The public
  registration link is `{frontend origin}/register/{public_id}`. The numeric database id is never used in public
  links, so links cannot be guessed or enumerated. Admins copy or open the link from the event list.
- `starts_at` must be in the future on create, and on update whenever it is changed.
- `ends_at`, if set, must not be before `starts_at`.
- Soft delete only (`DELETE /events/{id}` sets `deleted_at`/`deleted_by`); deleted events are
  excluded from list/get.
- **Not yet implemented**: an event status field (`DRAFT`/`PUBLISHED`/`CLOSED`/`CANCELLED`), and a
  capacity floor tied to seats already
  taken (lowering capacity below registrations is not currently blocked by the events module —
  see [`BUSINESS_RULES.md` → Registration and OTP](#registration-and-otp) for how the guest flow
  handles this instead).

## Registration and OTP (`app/modules/guests`, `app/modules/otp`)

- Employees register themselves and their accompanying family from the event's registration link. One registration
  is one **party**: the employee plus `number_of_guests` accompanying guests (the adult and kids below), admitted
  together by one QR pass.
- Public form fields (backend-validated; unknown fields rejected):
  - `employee_id`: 1–30 characters, letters, digits, `-`, `_`, `.`, starting with a letter or digit. Compared
    case-insensitively (stored as entered plus an upper-cased copy for uniqueness).
  - `employee_name`, `adult_name` and each of `kid_names`: 2–100 characters, single line, no control characters.
  - `email`: validated, trimmed, lowercased. OTPs go only here.
  - `mobile`: optional. When provided, it must be a valid Indian mobile number and is normalized to
    `+91XXXXXXXXXX` (`app/core/mobile.py`). Blank, null or omitted values are stored as null. Never messaged.
  - `attending` ("Will you be attending the event on {event date}?"): required `true`/`false` (strict booleans).
    When `false`, every field below except `consent` must be left out (or null/false/empty); sending any of them is
    `422`. A non-attending employee still verifies their email by OTP; the registration then becomes `DECLINED`
    (see below).
  - `family_attending` ("Will you be accompanied by your family members?"): required when attending. When `false`
    the employee attends alone and no family member field may be sent.
  - `accompanying_adult` / `accompanying_kids`: the "Adult" and "Kids" checkboxes. When family is attending, at least
    one must be `true`. At most **one** adult: there is a single `adult_name` field and no list of adults.
  - `adult_name`: required when `accompanying_adult` is `true`, forbidden otherwise.
  - `kid_names`: 1–3 names when `accompanying_kids` is `true`, empty otherwise. More than 3 kids is `422`
    (`MAX_ACCOMPANYING_KIDS`, mirrored by the frontend's `MAX_KIDS`).
  - `kid_ages`: one age per kid, in the same order as `kid_names`: a whole number of years from 0 to 17 (strict
    integers). A missing, extra or out-of-range age is `422`, and ages are forbidden whenever `kid_names` is. The form
    shows an Age field beside every kid's name and clears it together with that name.
  - `food_preference`: `VEG` | `JAIN` | `FAST_FOOD` (shown as Veg, Jain, Fast Food), exactly one, required for every
    attendee; any other value is `422`. Whether an employee attending **alone** must also give one is controlled by
    `FOOD_PREFERENCE_REQUIRED_WHEN_ALONE` in `guests/schemas.py` (currently `True`, mirrored in the frontend's
    `registration-form.ts`); a party with family always must.
  - The party size is derived: `number_of_guests` = (1 if an adult) + number of kids, and must not exceed the event's
    `max_guests_per_registration` (`422`). The old free-form `number_of_guests` / `guest_names` request fields are
    no longer accepted.
  - `consent`: must be `true`.
- The frontend hides and clears every answer that stops applying (`clearInapplicable` in
  `frontend/src/app/public/registration-form.ts`): answering No to attendance clears the family and food answers,
  No to family clears the adult and kids, and unticking Adult or Kids clears those names. The backend rejects any such
  stale value rather than ignoring it, so hidden fields can never be stored.
- One registration per `(event, employee id)` and per `(event, email)`, enforced by unique constraints
  (`uq_registrations_event_employee`, `uq_registrations_event_email`). Submitting an employee id and an email that
  belong to two different registrations is refused with `409`.
- Resubmitting while still `PENDING_OTP` (matched by employee id or email) replaces the details, contacts, answers and
  family list and sends a new OTP, subject to the usual OTP limits. Guest rows beyond the new count are soft-deleted.
- A `DECLINED` registration (verified, not attending) holds no seat and has no QR pass. The employee can change their
  mind by submitting again with the **same** employee id and email: the new answers replace the old ones and the
  registration goes back to `PENDING_OTP` for a fresh OTP. A not-attending submission skips the seat and guest-limit
  checks, so an employee can decline even when the event is full.
- A `VERIFIED` registration is never changed from the public form. Submitting it again with the **same** employee id
  and email only sends a new code (to reissue a lost pass); with only one of the two matching it is refused with
  `409`, without sending a code or revealing the masked address. A `CHECKED_IN` registration gets `409`.
- Registration is only accepted while `now < (event.ends_at or event.starts_at)` — there is no
  separate "registration closes" time or admin action to close registration early yet.
- Capacity counts **people**: seats taken = `sum(1 + number_of_guests)` over `VERIFIED` and `CHECKED_IN`
  registrations. A `PENDING_OTP` registration holds no seats. Whether the whole party fits is checked before sending
  an OTP (`_ensure_seats_available`) and re-checked at verification under a row lock on the event, with locking reads
  of the registration and the seat count so MySQL's REPEATABLE READ snapshot cannot hide a concurrent verification.
  A party that no longer fits is refused whole ("This event does not have enough seats left for your party"); it is
  never partially admitted. If the admin lowered `max_guests_per_registration` below a pending party's size, its
  verification is refused with `422` until the employee resubmits.
- OTP: 6 digits from `secrets`, stored only as an HMAC, default validity 300s
  (`otp_ttl_seconds`), 5 wrong attempts invalidate the code (`otp_max_attempts`), 60s resend
  cooldown, caps of 5/hour and 10/day per email, 20/hour per IP, and a 2000/day app-wide email
  budget (`EMAIL_DAILY_BUDGET`) — all configurable via `Settings` (`app/core/config.py`). A new OTP invalidates any
  earlier unconsumed one for the same subject. Codes are never included in a response, logged,
  or written anywhere but the HMAC.
- **Not yet implemented**: a fixed "registration expires N minutes after submission if not
  verified" timer (today an unverified `PENDING_OTP` row simply never reaches `VERIFIED`; it is
  not auto-expired), and CAPTCHA on the OTP-send step.

## QR pass

- One pass per registration (party), issued only on successful OTP verification (`guests/service.py::verify`).
  It admits the employee and all their registered guests once. Verifying again
  later (e.g. a guest who lost their pass) issues a fresh token and immediately replaces the
  stored hash — the previous token no longer matches any registration.
- The QR code encodes only a 256-bit random token (`secrets.token_urlsafe(32)`) — no guest name,
  email or event id. Only its SHA-256 hash is stored (`registrations.qr_token_hash`, unique).
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
  `invalid`, `gate_closed`. For `admitted` and `already_checked_in` only, the response includes the party: employee
  id and name, guest names, party size, masked email and masked mobile; `already_checked_in` also gives the original
  check-in time and gate. Other outcomes, and officers not assigned to the event (`404`), get no personal details. The response is always `200 OK`; only `admitted` means entry is
  allowed. An out-of-scope event yields `404` before a scan outcome is even produced.
- Every scan attempt (including invalid ones) is logged in `scan_attempts`, without the raw
  token. A successful scan also writes a `check_ins` row with the officer id, event id, gate, method `QR` and a
  server-generated `checked_in_at`; the scan request cannot carry a time. Of two concurrent scans of one pass, the
  atomic `UPDATE ... WHERE status = 'VERIFIED'` lets exactly one win; the other gets `already_checked_in` with the
  winner's time and gate.
- `EventRead.gate_opens_at` / `gate_closes_at` expose this window so the officer's event list can show it; the
  backend still decides every scan.

## Security officers (`app/modules/users`, `app/modules/events`, frontend `/admin/events/:id/security`)

- Admins create officers (full name, email, optional Indian mobile, role `security_officer`, no password) and assign
  them to one or more events. Creating from the event's security page assigns the new officer to that event straight
  away; if the account is created but the assignment fails, the page offers to retry the assignment only.
- An email or mobile already used by any staff account is refused (`409`).
- Officers sign in at `/gate/login` with a code sent to their account email, then choose one of their assigned events
  at `/gate/events` and scan at `/gate/scan/:eventId`. They always choose the event themselves; the app does not jump
  to a scanner automatically, even with one assignment.
- Unassigning takes effect on the officer's next request: the event disappears from their list, and scanning or
  reading its entries returns `404`.

## Gate scanner (frontend `/gate/scan/:eventId`)

- The camera starts only after the officer taps "Allow camera and start scanning", uses the rear camera when there is
  one, and stops when the officer stops scanning, leaves the page, changes event, signs out or the page is hidden.
- QR codes are decoded on the device (native `BarcodeDetector`, or `@zxing/browser` where that is missing). Frames are
  never uploaded or stored. Only a string shaped like a pass token (`[A-Za-z0-9_-]{20,128}`) is sent; anything else is
  shown as an invalid pass without a request.
- One request per pass: frames are ignored while a scan is in flight and while its result is on screen; the officer
  taps "Scan next guest" to continue, and the same pass is ignored for a further 3 seconds.
- Party details (employee id and name, guest names, party size, masked email and mobile, check-in time, gate) are
  shown only for `admitted` and `already_checked_in`.
- **Not yet implemented**: an admin manual check-in fallback for when scanning is unavailable
  (`event-management.md` describes this; there is no `manual-check-in` endpoint on `main` yet).

## Soft delete and audit

- `events`, `officer_events`, `registrations`, `registration_guests` and `check_ins` use `AuditMixin`
  (`created_at/by`, `updated_at/by`, `deleted_at/by`); nothing is hard-deleted. `otp_challenges`
  and `scan_attempts` are append-only logs instead (see [`DATABASE.md`](./DATABASE.md)) and are
  never updated after creation except to record OTP consumption/invalidation.
- **Not yet implemented**: a scheduled retention job to anonymise guest personal data after the
  event (the spec's default is 30 days), and a dedicated `audit_log` table — the current audit
  trail is limited to each table's own `created_by`/`updated_by`/`deleted_by` columns plus the
  `scan_attempts` log.
