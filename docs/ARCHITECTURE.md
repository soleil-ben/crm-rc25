# Architecture

**Status:** Phases 1 to 3 implemented, plus the Phase 4A integration foundation —
foundation and customer CRM; bookings, packages, transport legs, manual operational events
and internal 4 × 6 labels; the public English/Vietnamese tracking page with its own
isolated API; and a provider-neutral durable inbox, job queue, worker, and adapter
contract. **No provider is connected** and no request has ever been made to a carrier or
to ShipStation by this application.
Sources of truth: `CRM.md` for behaviour, `Design.md` for interface.

---

## 1. Shape of the system

```text
frontend/  React 18 + Vite SPA (JavaScript/JSX)   -> browser
   |  fetch, same-origin, HTTP-only session cookie + CSRF header
   v
backend/   FastAPI + Pydantic + SQLAlchemy 2.x    -> single process
   |  SQLAlchemy Core/ORM, short transactions
   v
data/      SQLite file (WAL), outside the source tree, git-ignored
```

One repository, two applications. The React app never opens the database; every read,
write, permission decision, and export goes through the versioned REST API
(`Design.md` section 18).

A separate low-volume worker process backed by durable SQLite job and inbox tables exists
as of Phase 4A (`CRM.md` section 3): `app/workers/integration_worker.py`, run with
`--once` or continuously. **It is not running**, and with an empty adapter registry a pass
claims nothing and reports that honestly. The request process performs no provider work
inline — see section 13.

---

## 2. Backend layering

| Layer | Directory | Responsibility |
|---|---|---|
| API routes | `backend/app/api/v1/routes/` | HTTP shape only: parse, authorize, delegate, commit |
| Presenters | `backend/app/api/presenters.py` | Model to response mapping, batched to avoid N+1 |
| Schemas | `backend/app/schemas/` | Pydantic request/response contracts |
| Services | `backend/app/services/` | **All business rules** |
| Models | `backend/app/models/` | SQLAlchemy tables and relationships |
| Core | `backend/app/core/` | Config, DB engine, security, permissions, enums, normalization |

Route handlers stay thin on purpose. A rule such as "a qualifying shipment requires a
confirmed booking and a first physical handoff" lives in `activity_service.py`, not in a
handler and not in a React component, so the API, the seed command, and the tests all
apply the same definition.

### Service modules

| Module | Owns |
|---|---|
| `auth_service` | Credential verification, session issue/resolve/revoke, staff accounts |
| `customer_service` | Customer validation, create/update/archive, merge, referrals, search |
| `duplicate_service` | Advisory duplicate candidates; never merges |
| `activity_service` | Derived activity, lifecycle status, per-currency financial summary |
| `consent_service` | Append-only consent history, global suppression, eligibility |
| `task_service` | Follow-up rules, derived overdue, retention-rule dedupe |
| `segment_service` | Filter-tree validation, SQL compilation, plain-language description |
| `dashboard_service` | Dashboard aggregates and metric definitions |
| `audit_service` | Redacted audit entries |
| `identifier_service` | `STCA-000001` allocation; the unambiguous alphabet both ID generators share |
| `booking_service` | Route validation, drafts, transactional confirmation, Solaris IDs, cancel-and-rebook |
| `package_service` | Package references, measurement conversion, derived package progress |
| `event_service` | Manual operational events and the derived shipment status |
| `leg_service` | Transport legs, package associations, tracking-reference placeholders |
| `label_service` | 4 × 6 label PDFs, preview metadata, generation records |
| `shipment_service` | Shipment listing, filtering, and exact reference lookup |

---

## 3. Data access and SQLite

`backend/app/core/db.py` applies, on **every** connection:

* `PRAGMA foreign_keys=ON` — enforcement is per-connection in SQLite, so this cannot
  be a one-time setup step;
* `PRAGMA journal_mode=WAL` — readers do not block the writer;
* `PRAGMA busy_timeout` — short writer contention waits instead of failing;
* `synchronous=NORMAL`, `temp_store=MEMORY`.

`commit_with_retry` retries only `database is locked`, with bounded backoff, and rolls
back once the retries are exhausted. Any other `OperationalError` propagates.

The database file lives at `data/solaris_crm.db`, outside `backend/`, and is git-ignored
along with its `-wal` and `-shm` companions.

**Portability.** No PostgreSQL-only types and no SQLite-only SQL in service code. The
dashboard trend buckets rows in Python rather than calling `strftime`, precisely so the
query survives a move to PostgreSQL. Alembic runs with `render_as_batch=True` because
SQLite cannot alter most constraints in place.

**Scaling gate.** SQLite here is a single-server architecture. Multiple independently
writing replicas against one database file are out of scope. The documented threshold
for moving to PostgreSQL is in `docs/OPERATIONS.md`.

---

## 4. Authentication and authorization

* Password hashing: **Argon2** (`argon2-cffi`).
* Session: a random 256-bit token in an **HTTP-only** cookie. Only the SHA-256 digest is
  stored. Sessions carry idle and absolute expiry and can be revoked server-side.
* CSRF: a separate readable cookie whose digest is stored on the session row. Every
  non-safe method must echo it in `X-CSRF-Token`.
* No staff token is ever written to `localStorage`.
* CORS is restricted to the configured frontend origins, with credentials allowed.
* Login is rate limited per IP **and** per email; every failure returns the same message
  so the endpoint cannot enumerate staff accounts.

Authorization is a resource/action matrix in `backend/app/core/permissions.py`, applied
by the `require(...)` dependency on every data route. The frontend receives the caller's
permission list and uses it **only** to decide what to show. Hiding a button is never the
boundary; `backend/tests/test_permissions.py` calls the endpoints directly to prove it,
and `backend/tests/test_route_permissions.py` sweeps **every** guarded route against
**every** role over HTTP, reading the required permissions off the route table itself so
the coverage cannot fall behind a newly added route.

There are **four** roles. `customer_service` was merged into `operations` in September
2026 (DEC-0088); the merged role carries the former Customer service permission set
unchanged, and `financial_cost:read` remains Admin-only.

Exports and cost visibility are separate permissions from record access, so a role can
read a customer without being able to bulk-export contacts or see carrier costs.

---

## 5. Derived versus stored

Nothing about customer activity is a manual counter (`CRM.md` section 4).

| Value | Derivation |
|---|---|
| Total qualifying shipments | `COUNT` of confirmed, handed-off, non-cancelled, non-return shipments |
| First / Last shipment date | `MIN` / `MAX` of `first_handoff_at` over the same set |
| Repeat customer | qualifying count >= 2 |
| Observed primary route | most frequent route group over the same set |
| Lifecycle status | thresholds applied to the qualifying count and last shipment |
| Overdue | open task with `due_at` in the past — never stored |
| Last follow-up | `MAX(completed_at)` over completed tasks |
| Next follow-up | `MIN(due_at)` over open tasks |
| Referral count | distinct referred customers; qualified referrals counted separately |

The lifecycle rule exists twice — once in Python for a single record and once as a SQL
`CASE` for segment and list queries. Both read the same `LifecycleThresholds` and both
compare exact elapsed time rather than truncated days, so they cannot drift apart. This
duplication is deliberate and is covered by tests.

---

## 6. Segments

A saved segment stores a **validated filter tree**, not SQL and not a free-form blob.
`segment_service.validate_definition` checks every field and operator against a
whitelist before anything is compiled, so a stored definition can never become arbitrary
SQL. Compilation produces SQLAlchemy expressions over `Customer` joined to a qualifying
shipment aggregate, which is what makes a segment dynamic.

Marketing eligibility is deliberately **not** a filter field. `Design.md` section 8
requires consent eligibility to remain a separate export filter with its own visible
count, so a segment is never silently treated as an outreach list.

---

## 7. Frontend structure

```text
src/
  api/          client.js (fetch + CSRF + typed errors), endpoints.js
  app/          App.jsx, routes.jsx, SessionContext.jsx
  components/   ui/ (primitives), state/ (async states), layout/ (shell)
  features/     dashboard, customers (+tabs), shipments, segments, followups, settings, auth
  i18n/         translation catalogue and provider
  styles/       tokens.css, base.css
  utils/        format.js
```

The `shipments` feature is split by screen rather than kept in one file:
`ShipmentListPage`, `BookingWizardPage` with `bookingSteps.jsx`, `ShipmentDetailPage` with
`shipmentTabs.jsx`, `LabelPrintDrawer`, and `shipmentTokens.jsx` for the status badges.
Booking state, operational state, payment state, leg status, and tracking source each get
their own badge component with its own colour map, so they can never be read as one
ambiguous status.

Double submission of a booking is guarded on both sides: one idempotency key is generated
per wizard session and reused for every retry, and the confirm button disables while the
request is in flight. The disabled button is convenience; the key is the guarantee.

* Server state lives in TanStack Query. Database records are never copied into an ad hoc
  global store; local state is only for form input and UI toggles.
* `styles/tokens.css` is the single definition of every brand colour, type ramp, spacing
  step, radius, shadow, and duration. Components reference variables; literal brand
  colours appear nowhere else.
* List filters and record tabs are URL-addressable, so a filtered view is shareable and
  survives a reload.
* Every visible string goes through a translation key. `tests/i18n.test.js` fails the
  build if a component references a key the catalogue does not define.

---

## 8. Booking, identity, and concurrency

The Solaris Shipment ID is the one value customers, carriers, and staff all quote, so the
rules around it are the load-bearing part of Phase 2.

* A **draft** has `public_id = NULL`. Nothing customer-facing exists until confirmation.
* **Confirmation** is one transaction that either produces exactly one ID or produces
  nothing. The suffix is 12 characters from a cryptographically secure unambiguous
  alphabet (no I, O, 0, 1), with a database unique constraint and collision retry.
* The **route group and direction lock** at confirmation, because the ID encodes the
  route. Correcting a route is an audited cancel-and-rebook that issues a *new* ID and
  keeps a link in both directions. A cancelled ID is never reused.
* **Package references** (`SX-VCA-…-01`) come from the parent ID plus a stable sequence.
  Sequences are never renumbered, so cancelling a package does not free its number.
* Carrier assignment, relabelling, and transport legs never touch either identifier.

### Why there is no `SELECT ... FOR UPDATE`

SQLite has no row locks. Writing one would look like protection and provide none.
Confirmation is serialized by **database uniqueness** instead (DEC-0031): the first step
inserts a `booking_confirmations` row whose `shipment_id` and `idempotency_key` are both
unique. The loser of a race fails deterministically at flush and is converted into an
idempotent read of the winner's booking. A stored `request_fingerprint` turns "same key,
different data" into a clear 409 rather than a silent return of an unrelated booking.

`commit_with_retry` covers the SQLite `database is locked` window, and `confirm_booking`
retries the whole operation on that error — the retry then finds the winner's row.

---

## 9. Derived status, not stored status

Phase 1 established that customer activity is derived. Phase 2 applies the same rule to
shipments:

| Value | Derivation |
|---|---|
| Package operational state | latest event by `(occurred_at, recorded_at, id)` |
| `delivered_to_recipient_at` | earliest `delivered_to_recipient` event for that package |
| Package progress | counted from package rows — `packages_delivered_count` was removed |
| Shipment operational state | cancelled → all delivered → some delivered → attention → least advanced |
| `first_handoff_at` | earliest event representing real custody |

Package and shipment states are written back so list queries stay cheap, but
`event_service.recompute_status` is their only writer, and it recomputes from events every
time. Three consequences fall out of this rather than needing special cases: one delivered
package of three is Partially delivered; a warehouse receipt is a milestone; and a late
older event is simply not the latest, so it cannot regress a newer state.

---

## 10. Labels

`label_service` produces one 288 × 432 pt portrait page per selected active package with
ReportLab (DEC-0032), embedding a vendored Apache-2.0 Roboto so Vietnamese diacritics
render (DEC-0033). The barcode module width is two printer dots at 203 dpi (DEC-0034), and
identifiers are never shrunk or truncated to fit (DEC-0035). Output is deterministic, so a
reprint has an identical SHA-256.

The service records that a PDF was *generated and downloaded*. It does not claim a printer
produced anything, because nothing reports back.

---

## 11. Phase boundaries

Phase 2 **extended** the Phase 1 `shipments` table through migration `6b767a8a58fe`; the
baseline migration `b39203a50b1e` is untouched and a Phase 1 database upgrades in place.
Tracking assignments to a live provider, webhook inboxes, durable jobs, and integration
health are Phase 4 tables and do not exist yet. `leg_tracking_references` stores what staff
type and, optionally, a validated public carrier link; no provider is ever contacted
(DEC-0041).

The staff portal and the public tracking page are separate shells that share only
approved brand tokens. Public tracking uses its own explicit safe view model rather than
serializing an internal record (`CRM.md` section 10) — see section 12. The seam Phase 2
kept is the one Phase 3 was built on: a manual event's `internal_detail` and its
`public_update_text` are separate columns, and only the latter ever leaves the building.

---

## 12. The public tracking surface (Phase 3)

Two applications share one process and one build, and share nothing else.

```text
  /track, /track/:reference          everything else
          |                                 |
  PublicApp (own QueryClient,        StaffApp (SessionProvider,
   own bilingual i18n)                SessionGate, AppShell)
          |                                 |
  GET /api/v1/public/track/{ref}     /api/v1/... (session + CSRF + permissions)
          |                                 |
  public_tracking_service            booking/package/event/label services
          \                                 /
                    the same SQLite database
```

The separation is structural rather than conventional, in both applications.

### Backend

| Piece | File | Responsibility |
|---|---|---|
| Router | `app/api/public/router.py` | Mounted separately at `/api/v1/public`, so the split is visible in the route table and the OpenAPI document |
| Route | `app/api/public/tracking.py` | Two paths, one `_public_lookup` body: rate limit, then normalize, then validate, then resolve, then one generic failure |
| Dependencies | `app/api/public/deps.py` | A database session and the client key. Nothing that reads a row (DEC-0059) |
| Service | `app/services/public_tracking_service.py` | Every rule about what a stranger may see |
| Schemas | `app/schemas/public_tracking.py` | Standalone response models |
| Reference | `app/core/public_reference.py` | Forgiving normalization, strict validation |

`app/api/public/` imports **none** of the staff request dependencies. It is not a
convention: `tests/test_public_tracking.py` parses the package with `ast` and fails if an
import of `app.api.deps` or `app.api.v1` ever appears, and separately asserts that none of
the staff dependency objects is bound in the module under any alias.

**Phase 3 added no migration.** The `internal_detail` / `public_update_text` split Phase 2
built was the entire seam this needed. The public surface is a read path over the Phase 2
schema, which is why a Phase 2 database upgrades to Phase 3 by doing nothing.

### Why the schemas are standalone

`app/schemas/public_tracking.py` inherits nothing from `ShipmentDetail`, `PackageOut`,
`EventOut`, or `LegOut`, and no model in it sets `from_attributes`. That is a deliberate
structural choice rather than a stylistic one: an internal schema gains fields over time,
and a public model that inherited one would silently begin publishing them the day
somebody added a convenient field upstream. Every value is assigned field by field in
`build_result`, so a field reaches a customer because somebody wrote a line adding it.

`extra="forbid"` closes the other direction: a stray attribute cannot ride along.

### The order of operations, and why it is that order

1. **Derive the client key** from the request scope alone.
2. **Rate limit**, before the reference is looked at and before anything touches the
   database. Validating first would let a caller learn which of their guesses are well
   formed for free, and would let malformed input bypass the limiter entirely.
3. **Return the protected 429 with no query** when the allowance is exhausted.
4. **Normalize**, forgivingly. A scanner wedge, a phone keyboard, and an email client
   each mangle an identifier differently.
5. **Validate**, strictly, against a full-match pattern built from the same route prefixes
   and unambiguous alphabet the generator uses, so the two cannot drift. The
   120-character input bound is part of this step.
6. **Resolve**, exactly. No partial match, ever.
7. **Read the display timezone** — the only settings access on this path, and the last
   thing that happens rather than the first.
8. **Fail identically.** An invalid reference, an oversized one, an empty one, one
   carrying extra separators, an unknown one, a draft, and a demo record in production all
   produce the same status, body, message, and headers.

**This list was wrong in Phase 3, and the correction is why it is now eight steps rather
than five (DEC-0059).** Steps 1 to 3 read the same way before, but two things ran ahead of
them. `reference` was declared `Path(max_length=120)`, and FastAPI validates a path
parameter before the endpoint body, so an oversized reference produced a detailed 422 --
naming the constraint, echoing the value back -- without the limiter running; `/track/`
and `/track/a/b` did not match the route at all and fell through to Starlette's router
404, whose body differs again. And `public_org_settings` was a dependency, so a request
about to be refused had already read a row.

The route now takes a catch-all `{reference:path}` parameter with no framework
constraint, plus a second route for the bare `/track`; both call one `_public_lookup`
body. `app/api/public/deps.py` provides exactly two dependencies -- a session and the
client key -- and imports no model at all. `tests/test_public_boundary.py` asserts the
order by counting statements on the engine, which is the only way to state "no query" as a
fact rather than as an intention.

### Frontend

`src/app/App.jsx` places the public routes **above** the staff providers:

```jsx
<Route path="/track/*" element={<PublicApp />} />
<Route path="*" element={<StaffApp />} />
```

`SessionProvider` is mounted only for the second branch, so the `/auth/me` request it
makes on mount never runs on a customer's page and the staff login screen cannot flash
before a tracking result arrives. A test mounts the real `App` at a public URL and asserts
no staff endpoint is called.

**Both shells are lazily loaded**, and the split is not only a performance choice. Without
it a customer who scanned a parcel label downloaded the entire staff portal — every feature
screen, the booking workflow, the label drawer — to look at one tracking result. None of it
would run and none of it carries data, but shipping the internal application's structure to
anyone who scans a label is not something to do by accident. Measured against the
production build, a public route now fetches nine first-party requests and no `StaffApp`
chunk.

| Chunk | Size | Downloaded on a public route |
|---|---:|---|
| `index` (React, router, query) | 201 kB | yes |
| `PublicApp` + its CSS | 39 kB | yes |
| `StaffApp` + its CSS | 247 kB | **no** |

`PublicApp` creates its `QueryClient` **per mount** rather than as a module singleton. A
singleton would outlive the shell — surviving a navigation out to the staff portal and
back, and living for the lifetime of the tab — which is the wrong lifetime for a tracking
result. With `gcTime: 0` and the normalized reference as the query key, one customer's
result cannot appear under another's reference, and a failed second lookup shows the
failure rather than the previous shipment.

### Fonts and third-party resources

Nothing on either shell requests anything from a third party. Poppins and Inter are
self-hosted `woff2` subsets under `frontend/public/fonts/`, declared in
`src/styles/fonts.css`, with provenance and digests in the README beside them (DEC-0046).

Route-scoped prevention was considered and rejected: both shells are served from one HTML
entry, so a `<link>` in `index.html` loads on every route. Splitting the build to keep one
external font request would have been machinery in service of the thing being removed.

Public headings are set in Inter rather than Poppins because Poppins ships no Vietnamese
subset, so a Vietnamese heading would render half its letters from a fallback face
(DEC-0047).

---

## 13. Integration infrastructure (Phase 4A)

**No provider is connected.** The adapter registry is empty, `connected_api` is still
refused, and no request has ever been made to a carrier or to ShipStation by this
application. What Phase 4A built is the part whose correctness does not depend on which
product the account turns out to hold — because the account's product, API generation,
entitlements, authentication scheme, webhook event types, signature mechanism, rate
limits, external-label tracking support, and resource hosts are all still unverified
(`docs/INTEGRATIONS.md` section 3).

### Shape

```text
  provider (none)                        staff API                  public API
        |                                    |                          |
        v                                    v                          v
  [ inbox ]  --enqueue-->  [ jobs ]  <--read--  /integrations/health   /track/{ref}
        |                      |                                        |
        |                 integration_worker  (--once, or continuous)   |
        |                      |                                        |
        +--> integration_provider_events --> event_service.record_event  |
                                                     |                   |
                                              shipment_events -----------+
                                              (source = 'provider')
```

The right-hand column is the point. A provider event reaches a customer only by becoming
an ordinary `shipment_events` row and passing through the Phase 2 reducer and the Phase 3
public allowlist. There is no second path.

### Modules

| Layer | Where | Responsibility |
|---|---|---|
| Adapter contract | `app/integrations/adapter.py` | What a provider integration must supply, in capabilities rather than assumptions |
| Registry | `app/integrations/registry.py` | **Empty.** Registration refused while the environment is production |
| Resource policy | `app/integrations/resource_policy.py` | HTTPS, exact host and path allowlists, DNS checks, redirect rules. **No network request is made** |
| Redaction | `app/integrations/redaction.py` | What may reach a log, an error column, or an audit row |
| Inbox | `app/services/integration_inbox_service.py` | Durable acceptance, deduplication, the authenticity verdict |
| Queue | `app/services/integration_job_service.py` | Enqueue, atomic claim, lease, retry, operator retry |
| Mapping | `app/services/integration_event_service.py` | Normalized events, applied through the existing reducer |
| Health | `app/services/integration_health_service.py` | Counts and states; nothing it cannot support |
| Worker | `app/workers/integration_worker.py` | `--once` and continuous, with graceful shutdown |
| Staff API | `app/api/v1/routes/integrations.py` | Health, job listing, audited retry, disable |

### The adapter boundary

CRM.md section 9: *the rest of the application must not depend on raw ShipStation status
codes.* The contract asks an adapter to **declare** what it can do rather than assuming
it — whether it verifies signatures, supplies event ids, tracks externally purchased
labels, supports an authenticated read, and which exact hosts and paths a resource fetch
may use.

A capability answered honestly as "no" is the useful case, not the degraded one. If the
provider turns out not to sign its webhooks, `verifies_signatures = False` is what makes
the worker refuse to mutate state from a notification and enqueue an authenticated read
instead. If it cannot track an externally purchased label, saying so is what lets the
interface tell staff the truth rather than showing a permanently empty timeline.

Nothing outside `app/integrations/` imports a provider response structure, status
vocabulary, endpoint, or header name. `tests/test_integration_privacy.py` parses the
source tree with `ast` to assert it, the same way the Phase 3 test parses
`app/api/public/`. Docstrings are excluded from that scan on purpose: several modules
explain at length that the integration is *not* built, which is the honest thing to write
and would fail a naive text search.

The only implementation is a deterministic fake in `backend/tests/fakes/`. It is not
ShipStation and does not model it: its provider key is `fake`, its statuses are invented
words no carrier uses, and its signature scheme was made up in that file. Three
independent things stop it reaching production — it is not packaged, its key is `fake`,
and `AdapterRegistry.register` refuses by environment (DEC-0070).

### Concurrency, and what SQLite can honestly offer

Three guarantees, each enforced by the **database** rather than by application care:

| Guarantee | Mechanism |
|---|---|
| One inbox row per delivered event | `uq_integration_webhook_inbox_dedupe` |
| One active job per deduplication claim | unique nullable `active_dedupe_key` |
| One normalized event per provider event | `uq_integration_provider_events_fingerprint` |

Each service pre-checks as an optimization and catches `IntegrityError` as the guarantee,
because between reading and flushing another session may have inserted. This is the same
reasoning that produced `booking_confirmations` in Phase 2 (DEC-0031): SQLite has no
`SELECT ... FOR UPDATE`, and a lock that does not exist is worse than no lock because it
looks like protection.

Claiming work is a conditional `UPDATE` whose `WHERE` clause is the guard — still pending,
still due, unleased or expired. The database evaluates that predicate while holding the
write lock, so exactly one worker sees `rowcount == 1`.

**What is demonstrated, and what is not.** Two SQLAlchemy sessions on separate connections
against an on-disk database, which is a genuine race. **Not** two operating-system
processes. SQLite is single-writer, this deployment runs one worker, and
`docs/OPERATIONS.md` records that as a constraint rather than implying more.

### The authenticity boundary

Authenticity, deduplication, and processing are three independent axes, and keeping them
independent is what makes replay handling correct (DEC-0063).

Deduplication runs on an **unverified** payload, because a forged replay of a genuine event
is still a replay. Authenticity decides whether anything may be applied; a failure stores
the payload rather than discarding it, because a forged delivery is exactly the thing an
operator later wants to look at. Processing happens later, in a worker, and only for an
item whose authenticity permits it — re-checked at application time rather than trusted
from the enqueue.

Only `signature_valid` or `verified_by_read` may create a normalized provider event. An
unsigned notification may enqueue an authenticated read and nothing else; the *answer* is
what may move a parcel, and the status claimed in the body is ignored entirely.

### Where the public surface fits

**It does not change.** `connected_api` is still absent from the public tracking
vocabulary, no `last_carrier_update` or `last_successful_sync` field exists, and no
automatic-refresh language appears. A provider event moves the derived status exactly as a
staff event does, and reaches the timeline only if a staff member writes and publishes
wording for it — which the worker never does.

`app/api/public/` imports nothing from `app/integrations/`, and
`tests/test_public_contract_unchanged.py` asserts both the import boundary and the exact
field list of `PublicTrackingResult`.

### Phase boundaries, again

Migration `9d7dc78dd25c` adds **five tables and touches nothing else**. No column is added
to `shipments` or any Phase 2 child table, so a Phase 3 database upgrades in place and
downgrades back exactly. The Phase 1 baseline and the Phase 2 revision are unmodified.

Still not built, and deliberately: a ShipStation adapter, a webhook receiving endpoint, a
provider connection, a resource-fetch transport, and `connected_api`. Each of those needs
an answer this project does not have.

---

## 14. Reporting, export, and import (Phase 5A)

Three features that all read the same records and all have the same failure mode: a number
that is quietly wrong, or a field that quietly leaves the building. The structure below is
chosen against those two failures rather than for convenience.

### Shape

```text
app/services/report_service.py          nine reports, one period model, no stored figures
app/services/export_service.py          column allowlists, streaming, formula escaping
app/services/csv_safety.py              the only place an untrusted file becomes rows
app/services/customer_import_service.py preview, classify, commit; writes through customer_service
app/models/imports.py                   two provenance tables, no cell values
app/api/v1/routes/reports.py            report:read; financial gating is structural
app/api/v1/routes/exports.py            one export permission per export type
app/api/v1/routes/imports.py            template / fields / preview / commit / history
```

### Why the report period is a value object

`ReportPeriod` carries the two dates the caller supplied, the timezone they were cut in,
the resulting UTC bounds, and the bucket granularity — resolved once, in one place, and
passed to every report. The alternative, each report computing its own bounds, is how two
reports on the same page end up disagreeing about where September ended.

The bounds are half-open and cut at local midnight in the organization timezone
(DEC-0076). This turned out to be load-bearing in a way that was invisible until Phase 5A:
no timezone database was installed, so `zoneinfo` could not resolve `America/Toronto` and
every "office timezone" conversion in the product had silently been UTC since Phase 1.
`tzdata` is now a declared dependency, `zone()` raises rather than substituting UTC, the
application refuses to start if the configured zone cannot be resolved, and
`office_timezone` is validated before it can be stored.

### Why every metric is reconciled rather than unit-tested

A test that calls the same query the service calls proves the query is deterministic. It
does not catch a wrong *definition* — counting a package as a shipment, counting a
cancelled booking, counting a merged customer twice, cutting a period on the wrong side of
midnight — and a wrong definition is the failure that actually happens in reporting.

So each metric has a test that recomputes it a second way, in plain Python over the fixture
rows, from the definition as written in prose, sharing no helper with the service
(DEC-0077). The fixture is deliberately awkward: a draft, a cancellation, a
cancel-and-rebook pair, a return, a merged customer, a three-package two-leg shipment,
three currencies, and two shipments straddling local midnight.

### Why exports use an allowlist

An exclusion list is wrong the moment somebody adds a column, and the person adding a
column is not the person thinking about exports. Phase 2 added address snapshots to
`shipments`; Phase 4A added a payload column to a new table. Under an exclusion list both
would have appeared in an export by default. The allowlist fails the other way — a new
column is invisible until somebody adds it deliberately — and that is the safe direction
(DEC-0080).

Export permission is checked **independently of record access**, because reading one
customer and extracting the whole book are different acts. Both dependencies are declared
on the route, and the tests call the HTTP endpoint rather than the service, because a
service-level test would pass just as happily against a route that forgot to declare one.

Exports stream. The generator pages the query in bounded batches, so memory does not grow
with the size of the customer list, and nothing is written to disk — there is no export
file to find later.

### Why the import is staged, and why the preview writes nothing

The workflow is select → parse → review → decide → commit, and only the last step writes.
The preview performs **no write of customer data at all**: not a staging row, not a draft
customer, not a tag. A staging table holding un-reviewed personal data would be a second
copy of the customer database with none of its access controls (DEC-0078).

The consequence is that the file has to arrive twice. The commit re-uploads it, verified by
a digest of its bytes so the operator cannot preview one file and commit another, and
**re-parses and re-validates from scratch** rather than trusting a classification that
travelled through a browser. The only thing it takes from the operator is decisions: which
probable duplicates to create, and how to treat rows it has seen before.

Imported customers are created through `customer_service.create_customer`, never by
inserting a model row, so they go through the same normalization, validation, identifier
allocation, and audit as a customer typed into the drawer.

### Transaction boundaries

Validation decides membership; the transaction is all-or-nothing over the members
(DEC-0079). A row that fails validation is excluded *before* the transaction opens — it was
never a candidate, and it does not stop the rest committing. A row that fails *during* the
transaction means the database disagrees with what validation concluded, which means the
validation was wrong, and committing a partial result on top of a wrong premise leaves the
operator unable to tell what landed.

### The untrusted-file boundary

`csv_safety` is the only place an uploaded file becomes rows, and it is deliberately
unfriendly: bounded bytes, rows, columns, cell length and parse time; archives, compressed
files, spreadsheet binaries, PDFs and images refused by inspecting the leading bytes rather
than trusting the filename; NUL bytes refused; UTF-8 only, with anything else refused with
an instruction rather than guessed at; strict quoting so a malformed file fails loudly
instead of silently shifting every column.

It never evaluates a formula, resolves a path, fetches a URL, runs SQL, or interprets
markup. A cell is text. The one transformation anywhere in the import is normalization of
the *header* row, matched against a fixed allowlist.

### What Phase 5A did not touch

The Phase 4A integration seam, entirely. No report, export, or import module imports
anything from `app.integrations` or `app.workers`, names a provider product, or imports an
HTTP client — asserted per module by `tests/test_phase5a_integration_seam.py`, which also
checks that exercising the whole Phase 5A surface creates no integration row and opens no
socket.

Reporting is the feature most likely to erode that boundary quietly, because a report wants
a column for every dimension and an empty column reads as a bug rather than a truth. Two
rules were applied: no report displays a freshness, last-update, or last-successful-sync
figure, because no such value exists; and the shipment-exception report groups by tracking
source showing only `manual`, `external_link` and `none`, because rendering an empty
`connected_api` column would imply a mode that could have data in it (DEC-0075).

---

## 15. Approved public wording (Phase 5A1)

A customer-facing milestone is stored as a **key**, not a sentence.

```
backend/app/content/public_update_templates.json     one catalogue, owned by the backend
   |                                               (ships with the API that validates it)
   +-- app/services/public_update_templates.py     load, validate at import, render
   |      +-- event_service                        accepts a key; enforces exclusivity
   |      +-- public_tracking_service              publishes the key + an English fallback
   |      +-- shipment_presenters                  renders for the staff timeline
   |
   +-- frontend/src/shared/publicUpdateTemplates.js   via the `@templates` Vite alias
          +-- features/shipments/shipmentTabs.jsx     the picker, defaults, bilingual preview
          +-- public/TrackResultPage.jsx              renders in the reader's language
```

**One file, two runtimes.** The catalogue lives in the backend package so it ships with
the API that validates against it, and the frontend imports that same file through a Vite
alias rather than keeping a copy. Two copies of customer-facing wording drift, and the
copy that drifts is the one a customer is reading. The cost is that the frontend build
reads a path outside its own root, which is why `server.fs.allow` names the repository
root; production builds bundle the JSON and never serve it.

**Why a key and not a sentence.** The public tracking page is bilingual with a live
language switch. Rendering the sentence server-side would force a full refetch of the
tracking result on every switch — defeating the page's deliberate no-refetch design and
spending the customer's rate-limit allowance on a language button. Holding the catalogue
client-side makes the switch free (DEC-0084).

**Validation runs at import, not at request.** `check_catalogue` is called when the module
loads, so a catalogue missing a translation, naming an unknown event type, or carrying an
unreachable template stops the application from starting. The alternative is a staff
member discovering it by clicking publish.

**The exclusivity rule lives in `event_service`,** alongside the rule it extends: wording
without the publish flag is already refused, and now so is a key without the flag, a key
for the wrong event type, and a key together with free text.

---

## 16. The Customer Account surface (Phase 9)

**Status: the identity foundation is implemented. Nothing else on this surface is.** A
customer can register, confirm their address, sign in, see the state of their own
application, and recover a lost password. They cannot see a shipment, cannot see a customer
record, and cannot be approved — approval and linking are staff acts and are Phase 10.

**Registration is not production-ready and is blocked from launching.** OD-34 selects no
email provider and OD-37 supplies no approved legal text; both are enforced rather than
noted (section 16.7).

### 16.1 Three surfaces, one process, nothing shared

| | Staff Portal | Public Tracking | Customer Account |
|---|---|---|---|
| Prefix | `/api/v1` | `/api/v1/public` | `/api/v1/account` |
| Authentication | session cookie | none | session cookie, **different realm** |
| Session cookie | `solaris_session` | — | `solaris_account_session` |
| CSRF cookie / header | `solaris_csrf` / `X-CSRF-Token` | — | `solaris_account_csrf` / `X-Account-CSRF-Token` |
| Identity table | `users` | — | `customer_identities` |
| Session table | `user_sessions` | — | `customer_sessions` |
| Resolver | `auth_service.resolve_session` | — | `customer_auth_service.resolve_session` |
| Dependencies | `app/api/deps.py` | `app/api/public/deps.py` | `app/api/account/deps.py` |
| Authorization | role → permissions | none | **identity state; no role, no permission** |
| Rate-limit keys | `login:*` | `public:*` | `account:*` |
| Error body | `code`, `message`, `field`, `detail` | `code`, `message` | `code`, `message`, `field` |
| Correlation header | echoed | **not echoed** | **not echoed** |

A cookie from one realm presented to another authenticates nothing — not because a check
rejects it, but because the code that would resolve it reads a different table. That is the
distinction worth holding onto: the separation is structural, so it survives somebody adding
a route without reading this document (DEC-0090, T-01).

Three things *are* shared, deliberately: the database engine, `app.core.normalization`, and
the policies in `app.core.security` — the Argon2 hasher, the session-token digest, the
constant-time comparison and the sliding-window limiter. Two hashers would mean one of them
was weaker. What is not shared is the limiter's **key space**: a customer-side flood must not
consume the staff login allowance during exactly the incident operations needs to respond to.

### 16.2 The eight routes

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/register` | none | Generic response always |
| `POST` | `/verify-email` | token | Single-use, expiring, purpose-bound |
| `POST` | `/verification/resend` | none | Generic response, rate limited |
| `POST` | `/sign-in` | none | Generic failure text; rotates the session |
| `POST` | `/sign-out` | identity | Server-side revocation |
| `POST` | `/password/forgot` | none | Generic response always |
| `POST` | `/password/reset` | token | Revokes every session for the identity |
| `GET` | `/me` | identity | Account state only. No customer or shipment data |

Not built in Phase 9, and each recorded rather than omitted: change-password (DEC-0095),
profile read and edit, the marketing-consent route, and anything that reads a shipment.
`backend/tests/test_account_boundary.py` asserts the route inventory is exactly these eight.

### 16.3 Handler ordering, and why the bodies are parsed by hand

Every public handler takes the raw `Request` and parses the body itself. This looks like a
step backwards from a declared body model and is not:

```
origin check → per-IP limit → read body → validate → per-address limit → service
```

A FastAPI body model is validated **before** the endpoint function runs. A malformed request
would therefore answer with a detailed 422 naming the constraint and would never touch the
limiter — so anybody wanting unlimited attempts would simply send invalid JSON. Phase 3
corrected the same mistake on the public surface, where a `Path(max_length=...)` constraint
was producing a detailed error before the rate limiter ran (DEC-0059).

Two consequences are asserted rather than described: a malformed body still spends an
attempt, and a refused request issues **zero** database statements. Both are measured with an
engine listener in `backend/tests/test_account_rate_limits.py`.

### 16.4 Identity states

| State | Can sign in | Sees own state | Sees shipment history |
|---|---|---|---|
| `pending_verification` | no | — | no |
| `pending_approval` | yes | yes | **no** |
| `active` | yes | yes | not in Phase 9 — no route serves it |
| `rejected` / `suspended` / `deactivated` | no | — | no |

**Phase 9 never writes `active`.** It is reachable only through an explicit staff approval
with a link, which is Phase 10 (OD-24). `pending_approval` is a real signed-in state on
purpose: a customer waiting for review needs to be told where their application stands, and
telling them requires authenticating them.

Every refusal — wrong password, unknown address, unverified, suspended, rejected, deactivated,
locked — produces the **same sentence**. The distinctions matter to the audit log and to
nobody else.

The session row holds no role, no permission and no linked-customer id, so authorization
re-reads the identity on every request. A suspension therefore takes effect on the **next
request**, not at the next sign-in — the property Phase 7 established for staff roles, kept
deliberately.

### 16.5 Registration writes no canonical row

Registration creates a pending identity and a pending **proposal**, and touches no canonical
table — not `customers`, not `customer_addresses`, not `consent_events`, not even when the
submitted email matches an existing customer exactly (OD-23, DEC-0092).

This is the most important structural property of the surface: a bug anywhere in
customer-facing code cannot corrupt the CRM. The worst outcome available to it is a bad
proposal that a person then declines.

Submitted data lands as typed rows against a 43-key allowlist
(`app/core/account_fields.py`), each carrying what the person typed **and** what
`app.core.normalization` made of it — the same `email_normalized`, `phone_e164` and
`name_match_key` the Staff Portal produces, which is what makes "the same customer" mean the
same thing on both surfaces. What this surface may never do is *report* the result: a score,
a match or a count is staff-facing only (T-02).

Three values have no canonical column and are carried as proposal fields only: a display
name, a legal name distinct from it, and a billing address role (DEC-0096).

### 16.6 Tokens and sessions

| | Construction | Why |
|---|---|---|
| Session token | SHA-256 digest, stored | The staff construction. 32 random bytes; a key buys nothing |
| CSRF token | SHA-256 digest, on the session row | Double-submit, bound to this row (DEC-0005) |
| Verification / reset token | **keyed** HMAC-SHA256 over `purpose:token` | Purpose binding by construction, and deployment binding (DEC-0097) |
| Address key | keyed HMAC-SHA256 | So limiter memory and audit rows hold no address list |

A verification link presented to the reset endpoint matches no stored row even if a query
forgot its `WHERE purpose` clause. Consumption is a conditional `UPDATE … WHERE consumed_at
IS NULL` whose row count is checked, so two simultaneous redemptions resolve to exactly one
success on a database with no `SELECT … FOR UPDATE`.

A completed password reset consumes the token, replaces the password, revokes **every**
Customer Account session and invalidates every other outstanding reset token — together or
not at all. Staff sessions are untouched, because there is no code path from here to
`user_sessions`.

### 16.7 Email: a seam, a capture, and two launch blockers

One `EmailTransport` interface and three transports, selected by configuration. The set is
closed and there is deliberately no value meaning "production if configured, capture
otherwise" — a silent fallback is how a deployment writes verification links to a directory
while customers wait for mail nobody sent (DEC-0094).

| Transport | Behaviour |
|---|---|
| `null` | Records that a send was requested. Produces nothing. The default, including in tests |
| `capture` | Writes to the git-ignored development data directory. **Opens no socket.** Refused at startup in production |
| `production` | **Not written.** Selecting it fails at startup, because OD-34 has selected no provider |

A caller passes a **template key** and a bounded parameter map, never a rendered body and
never HTML from a request. The catalogue is in the repository and is reviewed as copy.

**No HTTP route returns captured mail**, and that is asserted over the whole route table: a
route that did would be a way to read anybody's recovery link.

**The two production blockers are controls, not notes.** In production, with no production
transport configured, `/register`, `/verification/resend` and `/password/forgot` refuse at
the route with a 503 whose body says nothing about why. Registration additionally refuses
while the terms and privacy version identifiers are still the marked placeholders (OD-37).
The rest of the application still starts and still serves: blocking the Staff Portal and
Public Tracking over a surface that has not launched would be the wrong trade.

### 16.8 What this phase did not change

The Public Tracking boundary is unmoved: `PublicTrackingResult` is still exactly 24 fields,
the public error body is still two keys, and the public surface still returns no correlation
header. The Customer Account is held to the same correlation rule for a sharper reason — its
registration and recovery responses must be byte-identical whether or not an address has an
account, and a per-request header is by definition a value that differs between two
responses. **No public correlation header was added**, so the boundary DEC-0085 drew is the
same boundary it was.

Staff authentication, the permission matrix and the guarded route table are untouched. No
provider adapter exists, both resource allowlists are still empty, `connected_api` is still
absent from the public vocabulary, and nothing in this phase opens a socket.


## 17. Customer Account approval and linking (Phase 10)

Phase 9 built an identity that could register, verify, sign in and wait. Phase 10 is the
phase a person decides about it. Everything here is backend and staff API; the Staff Portal
screen is Phase 12, because `IMPLEMENTATION_PLAN.md` section 1 makes Phases 9–11
backend-first on purpose — every boundary in the threat model is a server-side property,
and a screen built against a boundary that does not yet hold teaches the wrong habit.

### 17.1 Two permissions, and why neither is `duplicate:review`

`customer_account:review` reads the queue, one application, its duplicate candidates and a
preview. `customer_account:approve` acknowledges, approves, links and rejects. **Every
mutating route requires both**, so the power to activate an account cannot be held without
the power to look at what is being activated. Admin and Operations hold both (OD-24);
Marketing, the read-only manager, an unauthenticated caller and a Customer Account session
hold neither and reach nothing.

`duplicate:review` is deliberately not sufficient. Marketing and the read-only manager
already hold it. Deciding whether two *records* are one person and deciding whether a
living person holding a password may read a customer's shipment history from now on are
related powers and different ones, and the route table says so by name.

### 17.2 The three canonical gaps, closed

`FIELD_MATRIX.md` section 6 named a display name, a legal name distinct from it, and a
billing address role as things the CRM had no column for. Phase 9 deliberately did not add
them (DEC-0096) — nothing in that phase could *apply* a proposal, so a column added then
would have been a column with no writer. Phase 10 applies one, so this is where they land.

`customers.legal_name` and `customers.display_name` are nullable, undefaulted and
unbackfilled: every existing row keeps exactly what it had and `full_name` keeps exactly
what it meant. The billing role is a fourth `AddressRole` member and needed no DDL at all.
The precedence between the four name concepts is decided once, in
`app/core/account_field_mapping.py` and in `DATA_DICTIONARY.md`.

### 17.3 Where a proposal goes, and who writes it

`app/core/account_fields.py` says what a customer may *submit*; `account_field_mapping.py`
says where an approved submission *goes*. They are the two halves of one allowlist and a
test asserts they name the same 43 keys, so a field added to one without the other fails.

The mapping produces **payloads**, not rows. The writing is done by
`customer_service.create_customer` and by `customer_address_service`, which is what makes a
customer created by an approval indistinguishable from one a staff member typed: same
validation, same normalization, same `public_id` allocation, same `customer.create` audit
row. `customer_address_service` is new only in the sense of being extracted — it is the
address normalization that lived inside the engagement route, lifted so that two callers
read one implementation rather than two that drift.

### 17.4 The preview, and what a fingerprint is for

A reviewer decides using figures the server computed. Between reading them and pressing
approve there is a window, and the world can move in it: a customer is edited or merged, a
shipment is booked or cancelled or rebooked, the applicant submits a replacement, another
reviewer decides first, another identity takes the customer.

So the preview carries a **fingerprint** — a keyed digest over every fact that, if it
changed, would make the earlier decision the wrong decision. At approval time the service
recomputes all of them and compares. A mismatch is `409 preview_stale`: the acknowledgement
is not reusable, and the reviewer must take a fresh preview and agree again. **No count,
date, classification or ownership relationship is ever read from a request body.**

The acknowledgement is a row rather than a flag, because the approval that checks it is a
later request: a flag would record that somebody clicked, and the row records what they
agreed to (OD-29).

The preview carries the disclosure figures and no shipment detail. It cannot carry one: the
calculation behind it returns a count, two dates and two booleans, and never loads a
shipment row.

### 17.5 Two paths, and the one that writes nothing

**Create-new** writes, in one transaction: the idempotency claim, a `customers` row, its
address rows, a `consent_events` row *only* when marketing was explicitly chosen and the
address is not suppressed, the proposal's status and per-field `applied` flags, the link
row, the identity's status, and the audit rows. A failure anywhere leaves none of it.

**Link-existing** writes the same **minus the canonical customer and its addresses, and
minus the consent event**. Differences between the submission and the record are reported
as field keys and left `applied = false`. That is OD-28 read literally: a person filling in
a registration form is not thereby editing a customer record somebody else maintains, and
an approval that quietly applied their version would make registration a write path into
the CRM under another name.

A merged or archived customer is refused as a link target. A merged reference resolves
through the existing alias chain **only to name the surviving record** — retargeting the
link silently would be the implicit closest-match selection OD-28 forbids.

### 17.6 How the guards work, given SQLite

There is no useful `SELECT … FOR UPDATE` here, so every guard is a conditional write, a
unique constraint or a claim. No decorative row-lock code was written.

| Guard | Mechanism | Decides |
|---|---|---|
| Idempotency | unique `idempotency_key_digest` on `customer_account_approval_attempts` | a retry replays instead of approving twice; one key reused for a different action or target is a conflict |
| Approval happens once | `UPDATE … WHERE status = 'pending_approval'`, row count checked | approve vs approve, and approve vs reject |
| One active link per identity | partial unique index (Phase 9) | two reviewers on one application |
| One active identity per customer | partial unique index (Phase 9) | two applications for one customer — the case an application check loses |

The link row is inserted **before** the status flip, so an index refusal leaves an identity
that is still pending rather than one that is active with no link. Both are in one
transaction, so the ordering is a second line of defence rather than the only one.

### 17.7 The activation invariant, and where it actually lives

Two functions assign the active status: the approval service, performing transition 4 of
`STATE_MACHINES.md`, and `customer_identity_service.reinstate`, performing transition 7. A
third is a defect, and a source scan over the parsed AST is the test that would catch it.

Phase 10 found transition 7 unsafe as written. It tested `approved_at is not None`, which
stays true forever, so an account that was approved, suspended and then unlinked would have
returned to `active` with **no active link** — an identity in the one state that reaches
shipment data, with no customer to reach it through. It now checks the live link.

The cross-table invariant — an `active` identity has exactly one active link, and anything
else has none — is **not** expressible as a SQLite constraint: there is no cross-table
`CHECK`, and a trigger would be a fifth mechanism in a codebase that states its guards in
four. The cost is stated rather than hidden: the guarantee lives in the transaction
ordering above and in a sweep that walks the whole database after every decision the test
suite makes.

### 17.8 Rejection

No customer, no link, and the credential stops working on the **next request** rather than
at the next sign-in: every session is revoked and every outstanding verification and reset
token invalidated, because either would otherwise be a way back into a declined account.
The reason code is bounded and never reaches the customer — a reason that said "duplicate
of an existing customer" would confirm that an existing customer exists.

Re-registration with the same address creates nothing and returns the generic response,
exactly as for any already-registered address. The documented way back is transition 9,
**Admin reinstatement**, which this phase's scope does not include and which is recorded as
a deferral rather than a permanent ban.

### 17.9 What this phase did not change

`PublicTrackingResult` is still exactly 24 fields. No Customer Account route reads a
shipment; `GET /api/v1/account/me` now reports `linked` truthfully and still reports
`shipment_history_available: false`, hard-coded rather than derived, because reporting
"available" while every path returns 404 would be the response telling a lie a screen would
repeat. No provider adapter exists, both resource allowlists are still empty,
`connected_api` is still absent from the public vocabulary, integration health is still
`not_configured`, and nothing in this phase opens a socket.

---

## 18. Authenticated shipment history (Phase 11)

Two read routes, and the whole of this section is about what stands in front of them.

### 18.1 The route inventory

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/api/v1/account/shipments` | active identity + effective link | 18-field list (DEC-0160), status/date/route/exact-reference filters and the `q` keyword search, which also matches the shipment's own package references (DEC-0156, DEC-0161), bounded paging |
| `GET` | `/api/v1/account/shipments/{reference:path}` | same | 25-field detail (the public 24 plus `booking_reference`, DEC-0163), addressed by Solaris Shipment ID only |

Both live in `app/api/account/shipments.py`, a separate module from `routes.py` because
they are the first routes on this surface that read customer data and the first that carry
an authorization step. **No mutation route exists**: Phase 11 adds no `POST`, `PATCH`,
`PUT` or `DELETE`, and `test_account_shipment_authorization.py` asserts that by walking the
route table rather than by saying so. `test_account_boundary.py` now names ten routes.

`{reference:path}` is a catch-all, and the reason is Phase 3's (DEC-0059). A plain
`{reference}` does not match a value containing a separator, so `/shipments/a/b` and
`/shipments/` miss the route entirely and fall through to Starlette's router 404 —
`{"detail": "Not Found"}`, a second failure shape on a surface whose design is that there
is one. The first version of this file had exactly that defect and the equivalence test
found it.

### 18.2 The authorization chain, evaluated on every request

```
valid Customer Account session          app.api.account.deps.current_account_session
  -> identity.status == 'active'        customer_account_link_policy
  -> exactly one effective link         customer_account_link_policy
  -> linked customer not archived,      customer_account_link_policy
     not merged, not a tombstone
  -> shipments.customer_id = <that>     in the SQL, on both routes
```

Five gates, re-read from the database on **every** request. Nothing is cached on the
session row, which is what makes a suspension, a deactivation, a link revocation or a
customer archive take effect on the *next* request rather than the next sign-in (T-14,
AC-CA-8.5). The cost is four of the nine statements a list request runs, and it is the
right cost.

The `status == 'active'` predicate is written once, in
`customer_account_link_policy.EFFECTIVE_LINK_STATUSES`. Phase 10 asks that module "is this
*customer* linked?"; Phase 11 adds the mirror question, "which customer may this
*identity* read?", to the same module rather than to a route (DEC-0113).

**`effective_links_for_identity` returns a list**, although a partial unique index permits
at most one row. The index is the guarantee; reading more than one is how the guarantee
gets checked rather than assumed. Two active links means a database that has stopped
enforcing its own constraint, and the right answer to that is to refuse — not to take the
first one and carry on reading somebody's shipments.

**Nothing on this path writes.** A read does not retarget, repair or infer a link, and it
does not touch `customers` or `shipments`. The only write either route performs is one
`audit_events` row on a refusal.

### 18.3 What is never an authorization input

Not an email address, not a phone number, not recipient information, not address
similarity, not possession of a public tracking reference, not a customer id supplied by a
browser, not frontend filtering, not proposal contents, not historical audit text, and not
an external carrier tracking number (OD-29, OD-30, T-04).

The audit-text exclusion is worth stating rather than assuming, because
`audit_events.entity_id` is intentionally free text and 104 historical synthetic rows still
name entities the cleanup removed. No authorization path reads that table at all.

### 18.4 One inclusion rule, shared with the disclosure preview

```
shipments.customer_id = <effective linked customer>
  AND shipments.booking_state != 'draft'
  AND shipments.is_demo_record = 0
```

`customer_account_disclosure_service.qualifying_conditions`, used by the staff preview that
a reviewer acknowledges *before* approving and by the list and detail queries a customer
then reads. One definition, because the direction those two could drift in is the one where
a reviewer authorized less than was disclosed. A test asserts the preview count and the list
total agree over the same data.

Consequences, each tested: drafts and demo records are invisible; cancelled and rebooked
shipments stay visible with safe states; a rebooked shipment does **not** disclose its
replacement's reference; a return is visible only through its own `customer_id`, with no
return-specific linking while OD-22 is open; shipments booked long before the account
existed are visible, because that is what OD-29 authorizes.

### 18.5 Two standalone schemas

`AccountShipmentListItem` is 18 fields (17 until UAT round 11 added `booking_reference`, DEC-0160) and `AccountShipmentDetail` is 25 (24 until UAT round 12 added `booking_reference`, DEC-0163) — the same field
names and semantics the Phase 8 specification approved for the public contract, **declared
independently**. Neither inherits a public or staff model, neither is an alias for one,
neither sets `from_attributes`, both set `extra="forbid"`, and the tracking-state and
data-mode enums are re-declared so widening the public vocabulary does not widen this one.
`PublicTrackingResult` is untouched and still exactly 24 fields.

What *is* shared is policy, not shape. The publication gate (`public_events`) and the
carrier-link safety check (`public_carrier_link`) are promoted to public names in
`public_tracking_service`, and the Customer Account service builds its own objects from what
they return. Sharing a predicate means two surfaces cannot disagree about a fact; sharing a
model would mean neither could change without the other (DEC-0113).

### 18.6 One failure, and one 403

A malformed reference, an unknown one, another customer's, a merged or alias identifier, and
an ineligible one all produce the same 404: same status, same body, same headers, same
statements in the same order. An unauthorized *account* — pending approval, no link, an
archived or merged linked customer — gets a 403 instead, with one sentence for every reason.
That distinction is safe and the other would not be: 403 is a fact about the caller's own
account, which they already know, while separating "no such shipment" from "not yours" is an
oracle for other people's parcels (T-03, T-17).

### 18.7 Ordering, paging and the two filters

The order is `booking_date DESC NULLS LAST, public_id ASC` — total, not merely
deterministic, so a page boundary can neither duplicate nor skip a row. Nulls are sorted
explicitly rather than left to SQLite's default, which would put the least identifiable rows
at the top of the first page.

Paging is offset/limit with a server-enforced maximum of 50. Under a concurrent insert the
window shifts and a row can appear on two consecutive pages; nothing is ever skipped, which
is the property that would leave a gap in somebody's history. That behaviour is documented
and tested rather than described as a cursor it is not.

The filters are **status group** and **date range**, which is what `SHIPMENT_ALLOWLISTS.md`
§3.2 approves and is narrower than the Phase 11 instruction's illustrative list: there is no
route filter and no reference search, because §3.2 declines free-text search in release 1 in
as many words. Both absences are asserted by test. Date boundaries are cut at local midnight
in the organization's configured timezone and then converted to UTC, the same rule every
report boundary uses (DEC-0076).

There is **no sort parameter**, so there is no column a caller can name and no
sort-injection surface to defend. The status group is a key into a dictionary of constants,
so no client value reaches a query.

### 18.8 Cost

Nine statements for a list request, whatever the page size: five for the authorization chain
and the display timezone, then a `COUNT(*)`, a page of rows, and one grouped aggregate
against each of `shipment_packages` and `shipment_events`. Grouped rather than joined,
because a join to `shipment_packages` would multiply a three-package shipment into three
list rows and a `DISTINCT` to undo that would break the `LIMIT`.

No cache was added. None is warranted by those numbers, and any future one would have to be
isolated by Customer Account identity *and* canonical customer.

### 18.9 Rate limiting, audit and logs

`account:read:identity:<public_id>`, 300 requests per 5 minutes, its own bucket in the
`account:` namespace — separate from staff login, Customer Account sign-in, registration,
password reset and Public Tracking, each asserted by flooding one and using another. Keyed
by the account rather than the address because the attack being bounded is scraping through
a compromised session, and an attacker changes address more easily than they change whose
history a cookie opens. It runs before the reference is parsed and before any ownership
query, so a refused request does no further database work and a malformed reference cannot
buy unlimited attempts.

**Denials are audited; successes are logged.** That asymmetry is the approved granularity: a
row per successful read would grow the audit table with ordinary browsing and build a second
copy of a customer's history in summaries, and what the threat model actually watches is
not-found *rates* per identity. T-03's audit line asks for the requested reference; the
Phase 11 instruction forbids a raw reference in an audit payload, and the stricter rule wins
— a keyed digest is recorded instead, the same construction the public surface already uses.

Neither artefact carries a raw reference, a carrier tracking number, an email or phone
number, recipient information, a session or CSRF value, a response payload or a financial
figure. The log line carries a **digest** of the account reference rather than the `CA-`
reference itself: an audit row is staff-facing and access-controlled, while a log line
travels to a shipper and possibly a search index. Four new field names were added to
`app.core.logging.SAFE_FIELDS`, which drops anything not on it.

### 18.10 Headers

Both routes apply the authenticated privacy header set, `Cache-Control: no-store` among
them, and the `security_headers` middleware repeats it for the shipment prefix so a refusal
raised before the handler still carries it. That repetition is not redundant: a 404, a 403
and a 429 are all raised before the handler returns, and without it an authenticated result
carried one value while the refusal after it carried another — a weaker guarantee on the
failure path and a difference between two responses that are meant to be
indistinguishable.

It is scoped to `/api/v1/account/shipments` rather than the whole account surface, because
the Phase 9 routes' headers are asserted byte for byte and widening them would be a Phase 9
contract change Phase 11 has no reason to make. **No cookie is set by either route.**

### 18.11 What this phase did not change

`PublicTrackingResult` is still exactly 24 fields and its tests are untouched. There is no
Customer Account frontend, no mutation route, no migration, no new table and no schema
change — `alembic check` is green at the same head. No provider adapter exists, both
resource allowlists are still empty, `connected_api` is still absent from every vocabulary,
integration health is still `not_configured`, and nothing in this phase opens a socket.
`GET /api/v1/account/me` now reports `shipment_history_available` truthfully, answered by
the same helper the routes use so the two cannot disagree; it is the only Phase 9 or Phase
10 response field Phase 11 changes.
