# AGENTS.md — Mastek Event Management

## Mandatory project context

Before planning or changing code, read:

1. `docs/PROJECT_INSTRUCTIONS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/BUSINESS_RULES.md`
4. `docs/DATABASE.md`
5. `docs/RBAC.md`
6. `docs/API.md`
7. `docs/SECURITY.md`
8. `docs/DEPLOYMENT.md`

`docs/PROJECT_INSTRUCTIONS.md` is the primary business and engineering specification for this repository.

## Product identity

This repository is for a **Mastek event management web app for events such as Diwali and Navratri, with guest management and security, in Mumbai, India**.

It is **not a generic commercial ERP**.

The core lifecycle is:

`Admin will create an event (navi ratri) → Add basic detail about that event (Guest capacity ) → Generate an form for guest to record the guest entry → Validate the guest with OTP → QR code generation → Security login with OTP → Security officer validate the QR code → Guest entry is register`

## Explicit exclusions

Do not introduce these features unless the user explicitly requests them:

- inventory or stock management
- warehouse management
- vendor management
- purchase orders
- sales orders
- manufacturing
- SKU/product management
- general ledger
- accounts payable
- full accounts receivable ERP
- payroll
- HRMS
- fleet GPS tracking
- route optimization
- LMS / homework / exams
- parent or teacher mobile apps
- multi-tenant SaaS architecture

## Roles

- Staff roles are `admin` and `security_officer` only. There is no event manager role.
- Guests have no accounts; they register through the public form and verify by OTP.
- Security officers see and act only on the events they are assigned to.

## Architecture

- Prefer a modular monolith.
- Preserve the repository's existing technology choices unless a change is justified.
- For greenfield backend work, prefer FastAPI + SQLAlchemy + Alembic + MySQL.
- For greenfield frontend/public-site work, prefer Angular + TypeScript + Tailwind CSS + ui.
- Do not introduce microservices without explicit approval.
- Use backend authorization for all protected operations.
- Use database migrations for every schema change.
- Include soft delete of the records, Avoid permanent deletion of records.
- Timestamp every entry in the DB and include date audit trails.
- Follow SOLID principles while coding and structuring.
- Confirm the technology stack and justify any unresolved stack decisions.
- Define the modular-monolith repository structure.
- Define public website, internal ERP, backend, database, storage, and shared-module boundaries.
- Define frontend architecture, API conventions, error handling, logging, auditing, testing, and configuration.
- Explicitly distinguish public APIs from protected ERP APIs.

## Core modules

Implement incrementally:

1. Authentication & RBAC
2. Admin login (password + 2FA)
3. Guest registration process
4. Guest validation process
5. Security officer login (OTP) and QR validation
6. QR code generation 
7. Dashboard & Reports
8. Notifications
9. Testing & Deployment


## Working rules

Before implementing a task:

1. Inspect the existing repository.
2. Read the project documentation listed above.
3. Search for existing reusable components/services/models/helpers.
4. Identify affected database, API, UI, permission, and test changes.
5. State a concise implementation plan.
6. Implement the smallest complete logical feature.
7. Add/update migrations when schema changes.
8. Add meaningful automated tests.
9. Run relevant tests/lint/type checks.
10. Fix failures caused by the change.
11. Update relevant documentation.
12. Summarize changed files and verification.

Do not:

- rewrite unrelated modules
- rename unrelated files
- reformat the whole repository
- upgrade unrelated dependencies
- replace working libraries without justification
- create duplicate helpers/components/services
- implement multiple business modules in one task unless explicitly requested

## Definition of done

A task is not complete until:

- functionality works
- backend validation exists
- permissions are enforced
- required migration exists
- error handling is implemented
- UI loading/error states are handled where applicable
- meaningful tests exist
- relevant checks pass
- documentation is updated where necessary
- no unrelated functionality is broken

## Git safety

Before starting a substantial task, inspect `git status`.

Do not discard existing user changes.

Work in a feature branch unless the user explicitly instructs otherwise.

Before committing:

- review `git diff`
- run relevant tests/checks
- ensure no secrets or `.env` credentials are included
- ensure generated/build artifacts are ignored where appropriate

Use clear, scoped commit messages.

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->
