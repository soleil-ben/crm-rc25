# Decisions

Reversible implementation decisions made during the build, and the assumptions behind
them. A decision here is a default, not a business confirmation. Items marked
**Needs business confirmation** should be reviewed by the owner.

---

### DEC-0001 — Repository layout is one repo with `backend/` and `frontend/`

**Decision.** Single repository, two applications, shared `docs/` and `scripts/`.
**Why.** Required by `CRM.md` section 3 and the build prompt. Keeps the API contract and
its consumer versioned together.
**Reversible.** Yes; splitting later is mechanical.

### DEC-0002 — Dependency versions are resolved and locked, not hand-picked

**Decision.** `pyproject.toml` and `package.json` carry minimum constraints; the exact
resolved versions are committed in `backend/requirements.lock.txt` and
`frontend/package-lock.json`.
**Resolved at build time:** FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.2,
Pydantic 2.13.5, argon2-cffi 25.1.0, phonenumbers 9.0.38, pytest 9.1.1, ruff 0.16.6;
React 18.3.1, Vite 6.4.3, React Router 6.30.6, TanStack Query 5.102.8,
React Hook Form 7.87.0, Vitest 2.1.9, ESLint 9.39.5.
**Why.** Reproducible installs without pinning the project to versions that go stale.

### DEC-0003 — Argon2 for password hashing

**Decision.** `argon2-cffi` with library defaults, plus `check_needs_rehash` on each
successful sign-in so parameters can be raised later without a mass reset.
**Why.** `CRM.md` section 3 asks for a maintained Python security library. Passlib's
maintenance history made it the weaker choice.

### DEC-0004 — Opaque session cookie, not a JWT

**Decision.** A random token in an HTTP-only cookie; only its SHA-256 digest is stored;
the session row carries idle expiry, absolute expiry, and a revocation timestamp.
**Why.** `CRM.md` section 11 requires session revocation. A stateless JWT cannot be
revoked without a server-side denylist, which is the session table with extra steps.

### DEC-0005 — Double-submit CSRF with a server-stored digest

**Decision.** A readable CSRF cookie is issued alongside the session; its digest is
stored on the session row; every non-safe method must echo it in `X-CSRF-Token` and the
value is compared with `hmac.compare_digest`.
**Why.** Cookie authentication needs CSRF protection. Binding the token to the session
row is stronger than a plain double-submit cookie.

### DEC-0006 — In-process rate limiting

**Decision.** A sliding-window limiter in application memory guards login (per IP and
per email).
**Why.** Correct and dependency-free for the documented single-server deployment.
**Limitation.** Counters are per-process and reset on restart. Running multiple worker
processes requires moving this to a shared store. Recorded in `docs/OPERATIONS.md` as a
production gate.

### DEC-0007 — Client IP is the direct peer only

**Decision.** `X-Forwarded-For` is **not** trusted.
**Why.** No trusted reverse proxy is configured yet; honouring the header now would let
a caller spoof the rate-limit key.
**Follow-up.** Revisit when the production proxy is chosen.

### DEC-0008 — Lifecycle thresholds are configurable settings, defaulted to the brief

**Decision.** New 30 days, Active 60 days, At risk 90 days, stored on the settings row
and editable by an administrator. Each status ships with a visible definition.
**Why.** `CRM.md` section 4 states these are initial business assumptions, not universal
benchmarks.
**Needs business confirmation.**

### DEC-0009 — Phase 1 ships a minimal `shipments` table

**Decision.** Phase 1 creates `shipments` with only the columns the Phase 1 rules need:
customer, route group, direction, service type, transport mode, three independent state
fields, booking/handoff/delivery/cancellation timestamps, package count, return and
rebooking links, and the optional financial columns.
**Why.** Customer activity, lifecycle status, segments, and the dashboard are all defined
in terms of qualifying shipments. Without this table those Phase 1 features would be
untestable, and a stubbed counter would violate the "derive, never store" rule.
**Not included.** Packages, transport legs, tracking assignments, tracking events, label
records — those are Phase 2-4 tables. Phase 2 extends this table rather than replacing it.

### DEC-0010 — Suppression is global to a channel and address, not customer-scoped

**Decision.** `contact_suppressions` is keyed on `(channel, address_value)`. Recording a
consent event cannot clear it; releasing one is a separate admin-only audited action.
**Why.** `CRM.md` section 11 requires suppression to survive imports and merges and
forbids staff overriding it accidentally. Customer-scoped suppression would be lost the
moment two records merged.

### DEC-0011 — Marketing eligibility is not a segment filter field

**Decision.** Segments cannot filter on consent. Eligibility is reported as a separate
count next to the member count, with a warning when they differ.
**Why.** `Design.md` section 8 requires consent eligibility to stay a separate export
filter so a segment is never silently treated as an outreach list.

### DEC-0012 — Duplicate confidence is advisory only

**Decision.** Candidates are scored (email 60, phone 55, name 25, capped at 99) and
always returned as "requires review". No score triggers an automatic merge, and a merge
requires typing the source customer ID to confirm.
**Why.** `CRM.md` section 13: families legitimately share a phone or an email.
**Needs business confirmation** of the weights if staff find the ordering unhelpful.

### DEC-0013 — Merge keeps the source record as a tombstone

**Decision.** The source is marked `merged_into_customer_id`, archived, and made
read-only. Its public ID is kept as a searchable alias, and looking it up resolves to the
surviving record.
**Why.** Preserves the audit trail and keeps old paperwork working. Deleting the row
would break foreign keys into shipment history.

### DEC-0014 — Archiving never cascades into shipment history

**Decision.** `shipments.customer_id` uses `ON DELETE RESTRICT`. Archiving sets a flag.
**Why.** `CRM.md` section 15 explicitly forbids cascade-deleting shipment history because
a customer is archived.

### DEC-0015 — Operations sees customers but not consent, segments, or money

**Decision.** The operations role holds customer read, address read, interactions, tasks,
and shipments, but not consent, segment authoring, financials, or exports.
**Why.** `CRM.md` section 11: "only customer details necessary for the task."
**Needs business confirmation** once real operational workflows are observed.

### DEC-0016 — Marketing can update a customer profile but cannot create or archive one

**Decision.** Marketing holds customer read and update, consent, tags, segments, tasks,
and the marketing-segment export; not create, archive, merge, financials, or the
operational export.
**Why.** `CRM.md` section 11 grants marketing "authorized customer profiles, segments,
consent and follow-up management" while withholding credentials, unrestricted
operational exports, and carrier costs.
**Needs business confirmation.**

### DEC-0017 — Financial visibility splits revenue from cost

**Decision.** `financial:read` exposes recorded revenue; `financial_cost:read` is admin
only and gates carrier and direct costs. Gross profit is returned only when both sides
are recorded for the same currency, otherwise `null` meaning Unknown.
**Why.** `CRM.md` section 12 forbids treating missing costs as zero and requires cost
visibility to be restricted separately.

### DEC-0018 — Currencies are never combined

**Decision.** Financial summaries return one bucket per currency with its own totals and
coverage counts. No cross-currency total is produced anywhere.
**Why.** `CRM.md` section 12 and AC-17. No dated FX rate mechanism exists yet.

### DEC-0019 — Text wordmark only; no invented logo

**Decision.** The portal renders "Solaris **Express**" as text, with `Express` in
Solaris Orange. No symbol, monogram, or logo file ships.
**Why.** `CRM.md` section 14 and `Design.md` section 3 forbid inventing an official mark.
**Follow-up.** Replace when an approved asset is supplied.

### DEC-0020 — Poppins and Inter loaded from Google Fonts with real fallbacks

**Decision.** `index.html` loads Poppins and Inter; every token declares
`Inter, ui-sans-serif, system-ui, sans-serif` fallbacks so the UI degrades cleanly.
**Why.** `Design.md` section 3 calls these a provisional starting point.
**Needs business confirmation** that these are the approved brand faces. Self-hosting is
the better production choice and is listed in `docs/OPERATIONS.md`.

### DEC-0021 — Charts are hand-rolled inline SVG

**Decision.** The trend line and route bars are inline SVG with an accessible table
alternative, rather than a charting dependency.
**Why.** Two simple charts do not justify a library, and inline SVG makes the
"never rely on colour alone" and table-alternative requirements straightforward.
**Reversible.** Yes; the chart components have narrow interfaces.

### DEC-0022 — Dashboard trend buckets in Python, not SQL

**Decision.** The trend query returns rows and buckets them in Python; buckets are daily
up to 14 days and weekly beyond.
**Why.** `strftime` is SQLite-only. `CRM.md` section 3 asks that a PostgreSQL migration
stay practical.

### DEC-0023 — Comparison figures are omitted rather than invented

**Decision.** A KPI card returns `comparison_value: null` unless genuine prior-period
data exists, and the dashboard says so in a data note.
**Why.** `CRM.md` section 12 and `Design.md` section 5 forbid fabricated percent changes.

### DEC-0024 — Deferred phases get honest routes, not empty feature pages

**Decision.** Shipments and Reports are in the navigation (`Design.md` section 4
specifies the order) but each states which phase owns it and what exists today.
**Why.** `CRM.md` section 14 asks to avoid empty future-feature tabs, while `Design.md`
specifies the navigation. An honest placeholder satisfies both better than a hidden item
that reappears later and changes the layout.

### DEC-0025 — Lead and marketing attribution fields are deferred, with an extension point

**Decision.** No Lead Source, Acquisition Channel, First Contact Method, Campaign, or
Interested Service fields exist. `customers.source_system` and `source_record_id` are
present for import idempotency only.
**Why.** The owner marked this "Chưa cần bây giờ — not needed now" (`CRM.md` section 2).

### DEC-0026 — Demo data is guarded at three levels

**Decision.** The seed command refuses to run when `ENVIRONMENT` is production or
`ALLOW_DEMO_SEED` is false; `get_settings` raises at startup if production is configured
with demo seeding enabled; every seeded row carries `is_demo_record`, and the UI shows a
persistent demo banner plus a per-record notice.
**Why.** `CRM.md` section 3 forbids seeding fake customers into production.

### DEC-0027 — Demo identities use the reserved `example.com` domain

**Decision.** Seeded emails are `<name>@demo.example.com`. Names are clearly fictional
and suffixed "(demo)".
**Why.** `.test` addresses are rejected by the email validator as special-use, and
`example.com` is IANA-reserved for documentation, so no real mailbox can be reached.

### DEC-0028 — Test isolation uses `create_all`; the migration is tested separately

**Decision.** Unit and API tests build the schema from SQLAlchemy metadata for speed.
A dedicated test runs `alembic upgrade head` against a clean database and asserts the
tables exist.
**Why.** Keeps the suite fast without letting the committed migration drift untested.

### DEC-0029 — Screenshots are review artifacts, not application assets

**Decision.** `frontend/scripts/capture_screenshots.mjs` drives Playwright against the running
demo stack and writes to `artifacts/screenshots/`, which is git-ignored.
**Why.** The build prompt requires screenshots compared against `Design.md`. The PNG
mockup and these captures are review inputs; neither ships in the UI.

---

## Phase 2 decisions

### DEC-0030 — Package progress is derived; the stored counter is removed

**Decision.** The Phase 2 migration drops the unused `shipments.packages_delivered_count`
column. Delivered progress is computed from `shipment_packages` rows on read, exactly as
customer activity is computed from shipments. `shipments.package_count` is kept, but only
as a denormalized count of *active* packages that `package_service.refresh_package_count`
rewrites inside the same transaction as every package change.
**Why.** Two sources of truth for "1 of 3 delivered" would eventually disagree, and the
one that disagreed would be the one shown to a customer. The Phase 1 column was never
read by any code (verified before removal), so dropping it costs nothing.
**Reversible.** Yes; the migration's downgrade restores the column with a server default.

### DEC-0031 — Confirmation is serialized by database uniqueness, not row locks

**Decision.** A `booking_confirmations` row is inserted as the first step of confirming a
booking. `shipment_id` and `idempotency_key` are both unique, and the row also stores a
`request_fingerprint` of the material booking data.
**Why.** SQLite has no `SELECT ... FOR UPDATE`. Writing one would look like a lock and do
nothing, which is worse than not writing it. Uniqueness is enforced by the database at
flush time regardless of engine, so the loser of a race fails deterministically and is
converted into an idempotent read of the winner's booking.

* Two concurrent confirmations of the same draft: `shipment_id` uniqueness means exactly
  one wins; the loser returns the winner's shipment or a clear conflict.
* A retried request with the same key: found by `idempotency_key`, returns the original.
* The same key reused for different data: the fingerprint differs, so it is a 409 rather
  than a silent return of an unrelated booking.

`tests/test_booking.py::test_concurrent_confirmations_on_separate_connections_produce_one_id`
runs two genuinely separate sessions on separate connections against an on-disk database.

### DEC-0032 — ReportLab for label PDFs

**Decision.** `reportlab` (BSD) generates the 4 × 6 label PDFs. It provides exact page
sizing, Code 128, QR, and TrueType embedding in one dependency.
**Why.** The alternatives needed three libraries for the same job. `invariant=1` is set on
the canvas so regenerating the same packages produces byte-identical output, which is what
makes the recorded `document_sha256` a usable check that a reprint really is the same
label.
**Reversible.** Yes; `label_service` is the only module that imports it.

### DEC-0033 — Roboto is vendored into the repository, not installed

**Decision.** `Roboto-Regular.ttf` and `Roboto-Bold.ttf` (Apache 2.0) are committed under
`backend/app/assets/fonts/` with their licence and SHA-256 digests.
**Why.** Vietnamese diacritics are a hard requirement and the fonts bundled with ReportLab
are missing 14 of the codepoints in a name like *Nguyễn Thị Bích Hạnh Đặng*. The files came
from the PyPI package `font-roboto`, which repackages the Google release; vendoring the
exact bytes keeps label output deterministic and reviewable rather than depending on a
small third-party package staying available. Apache 2.0 permits redistribution and
embedding. `tests/test_labels.py` asserts the coverage so a future font swap cannot
silently regress it. Full provenance is in `backend/app/assets/fonts/README.md`.

### DEC-0034 — Barcode module width is two printer dots at 203 dpi

**Decision.** The Code 128 module width is `72/203 × 2 ≈ 0.709 pt` (about 0.25 mm), with
0.25 inch quiet zones on each side.
**Why.** A fractional module width makes a thermal head round some bars up and some down,
which is the usual cause of a label that scans on one printer and not another. Two dots is
an exact whole number at 203 dpi and almost exactly three at 300 dpi. It is also at the
0.25 mm figure the GS1 general specification uses as a practical minimum.
**Validated.** `tests/test_labels.py` rasterizes the generated pages at 203 and 300 dpi and
decodes both symbols. A physical print-and-scan check remains a production gate.

### DEC-0035 — An identifier is never shrunk or truncated to fit

**Decision.** Names and addresses wrap and, past two lines, ellipsize. The Solaris Shipment
ID and the package reference shrink only as far as a readable floor and are never
shortened; if a reference could not be encoded at a scannable module width the service
raises rather than emitting a smaller symbol.
**Why.** A truncated name is a legible inconvenience. A truncated identifier is a parcel
nobody can find.

### DEC-0036 — Only a recipient-delivery event can complete a package

**Decision.** `ShipmentEventType.DELIVERED_TO_RECIPIENT` is the single event type that sets
`delivered_to_recipient_at`. Warehouse receipt, arrival at destination, and collection-point
handover are separate types, and the service rejects an attempt to flag any of them as a
final delivery.
**Why.** CRM.md sections 7 and 10 are explicit that a UPS delivery to the Solaris Canadian
warehouse is a milestone on a Vietnam-bound shipment, and that a collection point is not
confirmed final-recipient delivery unless the business defines it as such — which it has
not. Making the distinction structural means it cannot be lost in a status mapping later.

### DEC-0037 — Package state is the latest event by occurred time

**Decision.** A package's operational state is the event with the greatest
`(occurred_at, recorded_at, id)`. States are never ranked against each other to decide
whether an update may be applied.
**Why.** Ranking is what produces the classic bug where a late "In transit" scan regresses
a delivered parcel. Taking the latest by occurred time means an out-of-order arrival simply
is not the latest, and `occurred_at` and `recorded_at` are stored separately so a late
entry is visible as one. Rank ordering is used only to pick the most representative state
*across* several packages, where no regression question arises.

### DEC-0038 — Cancel-and-rebook produces a draft, not a confirmed shipment

**Decision.** Rebooking cancels the original and creates a linked replacement **draft**.
Confirming that draft issues a new Solaris ID.
**Why.** It keeps one rule: an ID is issued by confirmation and only by confirmation. Staff
can also correct the copied details before the new ID exists. Both records keep a link to
each other (`rebooked_from_shipment_id` / `rebooked_to_shipment_id`) so the correction is
traceable, and the original ID keeps its original meaning forever.

### DEC-0039 — Two new permissions: `shipment:cancel` and `label:generate`

**Decision.** Cancelling or rebooking is gated by `shipment:cancel` (admin and customer
service). Generating labels is gated by `label:generate` (admin, customer service,
operations). `tracking:write` gates carrier association and manual events.
**Why.** CRM.md section 11 gives operations "shipments, package handling, labels, carrier
mappings, operational milestones" but retiring a customer-facing Solaris ID is a different
weight of action. The existing six controls the brief names — shipment read/write,
financial read, carrier-cost read, financial write, audit, settings/integration — are
unchanged.
**Needs business confirmation** that operations should not cancel bookings.

### DEC-0040 — Financial visibility is expressed in the response shape

**Decision.** `ShipmentDetail.financials` is `null` without `financial:read`, and
`financials.costs` is `null` without `financial_cost:read`. The cost keys are not present
in the payload at all for a role that may not see them.
**Why.** Nulling a field still ships the key and invites a client to render Unknown as
zero. `tests/test_shipment_permissions.py` asserts the literal absence of
`shipping_cost` from the serialized response.

### DEC-0041 — Tracking references are placeholders; no provider is contacted

**Decision.** `LegTrackingReference` accepts `manual` and `external_link` only.
`connected_api` is refused by the service until Phase 4 verifies a real account. A public
carrier link is validated for scheme and host but is **never fetched**.
**Why.** CRM.md section 9: receiving a tracking number or URL does not authorize or enable
API tracking, and a selectable carrier name must not imply an integration exists. The UI
states this on every leg panel.

### DEC-0042 — Direction is inferred for a two-way route group when the addresses settle it

**Decision.** `XUS` accepts an explicit direction; when none is supplied and the sender and
recipient countries uniquely determine one (CA → US or US → CA), that direction is used.
Otherwise the request is rejected as needing an explicit direction.
**Why.** The addresses are the ground truth the direction is validated against anyway, so
requiring staff to restate it would be a second chance to disagree with them. US → US is
still rejected outright and named in the error.

### DEC-0043 — Decoding tools are an optional dev extra, and their absence is visible

**Decision.** `pypdf` and `fonttools` are required dev dependencies; `pymupdf`,
`zxing-cpp`, and `pillow` live in a separate `verify` extra. The decoding tests
`pytest.importorskip` with an explicit message.
**Why.** `pymupdf` is AGPL-3.0. It is used only by the local test suite to rasterize a page,
is never imported by the application, and is not part of the shipped product; keeping it
out of the default install keeps that boundary obvious. Skipping loudly matters more than
the licence though: a decoding check that silently passed because the tool was missing
would be worse than no check at all.

### DEC-0044 — The screen label preview does not draw a barcode

**Decision.** The 4 × 6 on-screen preview keeps the exact aspect ratio and the same content
in the same order, but shows a placeholder where the Code 128 symbol goes.
**Why.** A screen barcode invites someone to scan the monitor. Nothing about the on-screen
rendering — module width, quiet zones, contrast — has been validated for scanning, and the
PDF is the artifact that was. Design.md section 10 explicitly allows the preview to
simplify visual detail.

### DEC-0045 — Identical shipment-wide events are grouped in the timeline display

**Decision.** Recording one shipment-wide milestone writes a row per active package,
because per-package state is what package progress derives from. The timeline groups rows
that match on type, occurred time, recorded time, location, and wording, and lists the
affected package references instead.
**Why.** Storage needs per-package rows; a human reading a three-package shipment does not
need to read the same milestone three times. The grouping is display only — nothing is
hidden, and a per-package event still appears on its own.

---

## Phase 3 decisions

### DEC-0046 — Fonts are self-hosted; no third-party request from either shell

**Decision.** The Google Fonts `<link>` is removed from `index.html`. Inter and Poppins
are vendored as `woff2` subsets under `frontend/public/fonts/` (latin, latin-ext, and —
for Inter — vietnamese), declared in `src/styles/fonts.css`, with provenance, sizes, and
SHA-256 digests in `frontend/public/fonts/README.md` and the SIL Open Font License in
`OFL.txt` beside them. 180 KB in total; a browser fetches only the subsets a page needs.

**Why.** A tracking reference is privacy-sensitive (`CRM.md` section 10). A font requested
from `fonts.gstatic.com` tells that server, from the request alone, that a browser at a
given address opened a Solaris tracking page. That is a small disclosure and not one a
customer checking on a parcel agreed to; `Design.md` section 14 says the public page
carries no third-party anything, and DEC-0020 already recorded self-hosting as the better
production choice.

**Why not route-scoped.** Both shells are served from one HTML entry, so a `<link>` in
`index.html` loads on every route including `/track`. Splitting the build to keep one
external font request would have been a lot of machinery in service of the thing being
removed. The requests are gone globally instead, and the staff portal gets the same
benefit. `tests/publicTracking.test.jsx` fails if `index.html` regains any absolute
`http(s)` URL, and the end-to-end suite fails if the browser requests any non-first-party
host.

**Reversible.** Yes. Replacing the faces is four steps, listed in the fonts README.

### DEC-0047 — Public headings are set in Inter, not Poppins

**Decision.** The public shell sets `--public-heading-font` to the body face. The staff
portal is unchanged and still uses Poppins for headings.

**Why.** Google Fonts serves Poppins in `devanagari`, `latin`, and `latin-ext` only.
Vietnamese precomposed characters live in `U+1EA0–1EF9`, which is the `vietnamese` subset,
so a Poppins heading in Vietnamese renders its accented letters from whatever face the
browser falls back to — a heading in two typefaces. *Theo dõi lô hàng* would have had
"Theo d" in one face and "õ" in another.

Vietnamese is a first-class language on this page, not a fallback, and `Design.md`
section 15 requires diacritics to be preserved in the UI. `Design.md` section 3 calls
Poppins and Inter "a provisional starting point … verify supplied assets before
finalizing", so this is an interim choice within an unconfirmed brand direction rather
than a rejection of it.

**Needs business confirmation** alongside the logo and the brand faces. If Poppins is
confirmed, a Vietnamese-covering companion face is needed for the public shell.

### DEC-0048 — A forwarding header is not believed, and that is enforced in the application

**Decision.** `trust_proxy_headers` defaults to **false**. While it is false, any public
request carrying `X-Forwarded-For`, `X-Real-IP`, `Forwarded`, or `X-Client-IP` is keyed
into **one shared rate-limit bucket** rather than a bucket derived from the header. The
documented run command also passes `--no-proxy-headers`.

**Why this is not just DEC-0007 restated.** DEC-0007 said the application does not read
the header. The Phase 3 end-to-end suite proved that was not protection. Uvicorn enables
`--proxy-headers` by default and trusts `127.0.0.1`, so it rewrites `request.client` from
`X-Forwarded-For` *before the application runs*. The application was declining to read a
header whose value it was already being handed as the peer address, and a caller on
loopback got a fresh rate-limit bucket per request simply by changing the header — which
is to say, no rate limit at all.

Two mechanisms now, because one of them depends on deployment configuration and the other
does not:

* `--no-proxy-headers` on the server, which is correct and documented;
* the shared-bucket rule in `public_client_key`, which holds whatever the ASGI server did
  to the scope.

A spoofer can exhaust the shared forwarded bucket and no more. A direct caller — who sends
no such header — keeps their own bucket and is unaffected. Six tests cover it, plus an
end-to-end test that sends a different forged address on every request and asserts the
limit still engages.

**Follow-up.** When a production proxy is chosen, set `TRUST_PROXY_HEADERS=true` **and**
configure the ASGI server to trust that proxy's address specifically. Both halves, or
neither. Recorded as a gate in `docs/OPERATIONS.md`.

### DEC-0049 — The public API is a separate router with its own dependencies

**Decision.** `app/api/public/` has its own `deps.py` — a database session, the client
key, and the settings row read only for its timezone — and imports none of the staff
request dependencies. It is mounted as its own router at `/api/v1/public` rather than as a
prefix inside the staff router.

**Why.** A public route that reached for `CurrentUser` or `require(...)` would be a
one-line mistake with a very quiet failure mode, and `app/api/deps.py` is the obvious
place to import from. Making the public package unable to see those dependencies is
cheaper than remembering not to use them. `tests/test_public_tracking.py` parses the
package with `ast` and fails on any import of `app.api.deps` or `app.api.v1`, and
separately asserts none of the staff dependency objects is bound under any alias.

Mounting separately also puts the split in the route table and the OpenAPI document, so
"this path has no security dependency" is visible rather than inferred.

### DEC-0050 — Public schemas are standalone and never built from an ORM object

**Decision.** `app/schemas/public_tracking.py` inherits nothing from `ShipmentDetail`,
`PackageOut`, `EventOut`, or `LegOut`. No model sets `from_attributes`; every model sets
`extra="forbid"`. `public_tracking_service.build_result` assigns each field explicitly.

**Why.** Inheritance is the mechanism by which a public response quietly grows. An
internal schema gains fields over time — that is what internal schemas do — and a public
model that inherited one would start publishing them the day somebody added a convenient
field upstream, with no diff on the public file to review. Explicit assignment means a
field reaches a customer because somebody wrote a line adding it, which is a much better
default than a field appearing because nobody remembered to remove it.

`test_the_public_schemas_do_not_inherit_an_internal_schema` walks the public module and
fails on any class whose MRO intersects the internal schema module.

### DEC-0051 — One failure response, and the rate limit runs before validation

**Decision.** An invalid reference, a well-formed unknown one, a draft, and a demo record
in production all produce the same 404 with the same two-key body and the same headers.
The rate limiter runs **before** the reference is normalized or validated.

**Why the single response.** `CRM.md` section 10 requires that an invalid lookup reveal no
customer data, and the high-entropy identifier is the only thing protecting a shipment. A
response that distinguished "not a valid format" from "no such shipment" would confirm
which guesses are well formed, which is most of the work of enumerating.

**Why the limiter runs first.** Validating first would let an attacker learn the format for
free at any rate, and would let malformed input bypass the limiter entirely — so a
guessing attack would simply send garbage between real attempts.

**Known limit.** The two paths differ in *timing*: an unknown-but-valid reference reaches
a database lookup, a malformed one does not. Closing that would mean a constant-time
lookup, which SQLite cannot offer honestly. Given the rate limit and a 32^12 identifier
space, the residual signal is not a practical enumeration route. Recorded rather than
papered over.

### DEC-0052 — A cancelled booking returns the cancellation and nothing else

**Decision.** For a cancelled shipment the public response carries the identifier, route,
coarse origin and destination, the Cancelled status, package counts, and `cancelled_at`.
No timeline, and no carrier link.

**Why.** `CRM.md` section 10 permits only "the safe public Cancelled state" for a
cancelled confirmed ID. Replaying the journey of a booking that was withdrawn invites a
customer to believe a parcel is moving, and the cancellation reason is internal. The
identifier still resolves, because it may be on paperwork the customer holds and a blank
answer would be worse than an honest one.

### DEC-0053 — A public carrier link is judged more strictly than a stored one

**Decision.** `leg_service._validate_public_url` decides what staff may **store**;
`public_tracking_service.is_safe_public_carrier_url` decides what a stranger may **see**,
and is strictly narrower. A link is shown only when it is HTTPS, carries no credentials,
no fragment and no port, and its host is on a configured allowlist of recognized public
carrier sites (`PUBLIC_CARRIER_LINK_HOSTS`), with any host that parses as a private,
loopback, link-local, or reserved address refused outright. The source mode must be
`external_link`; a `manual` reference never becomes a public link.

The URL is **never fetched**. Not to validate it, not to check it resolves, not to preview
it. When safety cannot be established the link is dropped whole rather than rewritten —
stripping a parameter from somebody's URL is a good way to produce a link that no longer
works.

**Why an allowlist rather than a scheme check.** "Is this HTTPS" does not distinguish a
carrier's public tracking page from a private ShipStation dashboard, and `CRM.md`
section 10 forbids exposing the latter. An empty allowlist means no carrier link is ever
shown, which is the safe default for a deployment that has not thought about it.

### DEC-0054 — Public update text is shown verbatim and is not translated

**Decision.** The page is fully bilingual — statuses, routes, labels, dates, error states,
and every fixed string. `public_update_text` is not: it is shown exactly as the staff
member wrote it.

**Why.** It is free text typed by a person. Machine-translating it would put words in
Solaris's mouth that no one approved, and a mistranslation of "held pending paperwork"
is a customer service problem rather than a cosmetic one. `CRM.md` section 10 requires
public updates to carry explicit staff approval; that approval is of specific wording.

**Consequence for staff**, recorded in `docs/STAFF_GUIDE.md`: a customer who reads the
page in Vietnamese sees the surrounding page in Vietnamese and the update sentence in
whatever language it was written. Staff serving Vietnamese-speaking customers should write
the public wording in Vietnamese.

### DEC-0055 — The public query cache is created per mount and keeps nothing

**Decision.** `PublicApp` creates its `QueryClient` inside the component with
`useState(() => createPublicQueryClient())`, configured `gcTime: 0`, `staleTime: 0`,
`retry: false`, and no background refetching. The query key is the normalized reference.

**Why.** A module-level client would outlive the public shell: it would survive a
navigation out to the staff portal and back, and live for the lifetime of the tab. That is
the wrong lifetime for a tracking result. The failure this prevents is concrete — two
people sharing a phone, or one person checking two parcels — and the symptom would be one
customer's shipment appearing under another's reference, or a failed lookup still showing
the previous result.

`retry: false` also matters: retrying a 404 three times against a rate-limited endpoint
spends a customer's allowance on a question already answered.

### DEC-0056 — The in-process limiter is bounded, and how

**Decision.** `SlidingWindowRateLimiter` prunes expired buckets on an amortized sweep (at
most once a minute) and evicts least-recently-touched entries above a 20,000-bucket
ceiling. The key just touched is protected from eviction.

**Why.** Login is keyed by a finite set of staff addresses and emails. The public endpoint
is reachable by anyone, so its key space is "every address that has ever made a request" —
unbounded, and a plain dictionary would grow for the life of the process.

Dropping a bucket can only ever *forget* hits, never invent them, so the worst case is
that an address which stopped long enough to be pruned gets a fresh allowance — which is
what the sliding window would have given it anyway. Protecting the current key is what
stops eviction from becoming a bypass.

**Limitation unchanged.** This is still in-process, still per-worker, and still resets on
restart. Running more than one worker requires a shared store. Recorded in
`docs/OPERATIONS.md` as a gate.

### DEC-0057 — The reference is never logged; only an outcome and a keyed digest

**Decision.** `public_tracking_service.log_lookup` records an outcome category (`found`,
`not_found`, `malformed`, `rate_limited`), a truncated HMAC-SHA-256 digest of the
normalized reference keyed with `SECRET_KEY`, and the client key. The reference itself
reaches no application log.

**Why.** Logging a tracking identifier puts it in a file, a log shipper, and quite
possibly a third-party log search index — exactly what `CRM.md` section 10 forbids. The
digest is enough to notice that one reference is being probed repeatedly, and cannot be
reversed into an identifier without the application secret.

**What this does not cover.** The reference travels in the request **path**, so a reverse
proxy will write it to an access log unless configured not to. That is a deployment
concern the application cannot fix, and it is recorded as a production gate in
`docs/OPERATIONS.md` with an example redaction.

### DEC-0058 — The sample labels encode the real public path

**Decision.** `scripts/render_sample_labels.py` uses `https://track.example.test/track` as
its demonstration tracking base. The host stays a reserved `.test` placeholder; the path
is the real route.

**Why.** Phase 2 used `/t`, which was arbitrary and became wrong the moment Phase 3
registered `/track/:reference`. The sample PDFs are a listed deliverable, and a QR that
opens nothing is worse than no sample. Three tests now tie the label builder, the
configured default, and this script to the public route, because nothing else connects
them and a label lives on a parcel for weeks.

The **host** is still not confirmed. `TRACKING_BASE_URL` remains a deployment setting and
the tracking domain remains an open business decision (`docs/OPERATIONS.md`).

---

## Phase 3 correction

### DEC-0059 — The public boundary is the application, not the framework

**The defect.** An independent review found that
`GET /api/v1/public/track/{121-character value}` returned FastAPI's 422 path-validation
response, because the route declared `reference: str = Path(min_length=1, max_length=120)`.
Path validation runs *before* the endpoint body, so:

* the public rate limiter never ran, and the probe was free;
* the response differed from the generic 404 in status, body, and shape;
* the body named the constraint (`string_too_long`, `max_length`) and echoed the
  submitted value back;
* the claimed order "rate limit → normalize → validate → resolve" was not what the
  request actually did.

Reproducing it turned up two more shapes that never reached the route at all.
`/api/v1/public/track/` and `/api/v1/public/track/SX-CAV-.../01/02` did not match
`/track/{reference}`, so Starlette's router answered `{"detail": "Not Found"}` — a
different body again, also free of charge. Three distinguishable answers on a surface
whose entire design is that every failure is the same failure.

A second, independent ordering problem sat beside it. `public_org_settings` was a FastAPI
dependency that read the organization settings row for its display timezone. Dependencies
resolve before the endpoint body, so a request the limiter was about to refuse had
*already* queried the database. The limiter call was the first statement in the handler
and still ran second.

**Decision.** The reference is now a catch-all path parameter, `{reference:path}`, with no
framework constraint, and a second route answers the bare `/track` path. Both call one
`_public_lookup` body, which is the only public policy boundary:

1. derive the client key (request scope only);
2. rate limit;
3. return 429 with no query when the allowance is exhausted;
4. normalize and validate in application code;
5. one generic 404 for every invalid or unknown form;
6. only then resolve, and only then read the display timezone.

The 120-character bound did not disappear — it moved into `parse_public_reference` as
`is_within_input_bound`. Exceeding it is not a distinguishable outcome; it is one more way
of not being a Solaris reference.

`public_org_settings` and `PublicOrgSettings` are **deleted** rather than left unused, and
`app/api/public/deps.py` no longer imports `OrganizationSettings` at all. The read lives in
`public_tracking_service.display_timezone`, called from `build_result`, which is reached
only after a shipment has resolved. Leaving the dependency in place and merely not
declaring it would have been a one-line mistake away from returning.

**Why refuse rather than truncate.** `normalize_public_reference` already clipped to 120
characters, so an oversized value *could* have been silently truncated into the generic
404 path with a one-word change. Truncation is a quiet way for a valid identifier followed
by noise to become a successful lookup if the noise ever landed past the cut. Refusing
outright cannot do that.

**Why a catch-all is safe here.** The greedy parameter is scoped to `/track/` inside a
router mounted at `/api/v1/public`, so the only paths it can swallow are ones that would
otherwise 404. Nothing else is registered underneath it, the staff API is a sibling rather
than a descendant, and `tests/test_public_boundary.py` walks the real route table — which
this FastAPI version does not expose through a flat scan of `app.routes` — to assert both.

**Why `_MalformedReference`.** The route needs to record `malformed` and `not_found` as
separate *metric* categories without them being separate *answers*. It is a subclass of
`NotFoundError` carrying the identical message and no extra field, so the two are
byte-identical to a caller and distinguishable only to `outcome_for`.

**What did not change.** The single failure message, the privacy headers, the log
redaction, the per-mount query cache, and the public response allowlist are all untouched.
DEC-0051's known timing difference also stands unchanged: a well-formed unknown reference
still reaches a database lookup and a malformed one still does not, and
`test_public_boundary.py` now asserts both halves of that explicitly rather than leaving
it as prose.

**Validation.** 41 new tests in `backend/tests/test_public_boundary.py`. Run against the
pre-correction code, 23 of them fail; against the correction, all 41 pass, and the 108
existing Phase 3 tests are unchanged and still pass.

---

## Phase 4A decisions

Phase 4A builds the integration infrastructure whose correctness does not depend on which
provider is chosen. **No provider is connected, no adapter is registered, and no request
has ever been made to a carrier or to ShipStation by this application.**

### DEC-0060 — Deduplication is a database constraint, not an application check

**Decision.** Three uniqueness guarantees, each enforced by the database:

| Guarantee | Constraint |
|---|---|
| One inbox row per delivered event | `uq_integration_webhook_inbox_dedupe` on `(provider_key, connection_key, dedupe_key)` |
| One active job per deduplication claim | `uq_integration_jobs_active_dedupe_key` on `active_dedupe_key` |
| One normalized event per provider event | `uq_integration_provider_events_fingerprint` on `(provider_key, connection_key, provider_event_fingerprint)` |

Each service also performs a cheap pre-check. The pre-check is an optimization; only the
constraint is a guarantee, because between reading and flushing another session may have
inserted. `IntegrityError` is caught and converted into an idempotent acknowledgement of
the winner.

**Why.** SQLite has no `SELECT ... FOR UPDATE`, the same constraint that produced
`booking_confirmations` in Phase 2 (DEC-0031). AC-9 requires that duplicate webhooks do
not create duplicate timeline events, delivered counts, revenue, or follow-up tasks, and
"the application checks first" is not a mechanism that survives two callers.

**`dedupe_basis` is deliberately not part of the key.** Including it would let one event
arrive twice — once carrying a provider event id, once without — and insert twice. It is
stored as information about which basis was used, and nothing more.

**An `IntegrityError` is not assumed to be the deduplication constraint.** Foreign keys
are enforced on every connection, so a job naming a missing tracking assignment also
raises one. Swallowing that as "already queued" would silently drop real work while
telling the caller it was in hand; the table is re-read after the rollback and the error
propagates when there is no winner. Found while writing `test_integration_queue.py`.

### DEC-0061 — The job claim is a conditional UPDATE, and leases expire

**Decision.** `claim_next` selects a candidate id, then issues an `UPDATE ... WHERE` that
repeats every condition: still pending, still due, and unleased or expired. Exactly one
worker sees `rowcount == 1`. A lease carries an expiry; `reclaim_expired` returns rows
whose lease has passed, and a **live** lease cannot be stolen because the same predicate
refuses it.

**Why time-based recovery.** A worker that dies cannot report that it died, so nothing but
a clock can notice. The alternative — an administrator spotting a stuck row — is not a
recovery mechanism, and "stranded forever" for a delivery notification means a customer
never sees a delivery.

**Reclaiming does not reset the attempt count.** A job that keeps killing its worker must
still exhaust its attempts and reach the review queue, or a poison payload becomes an
infinite loop.

**What is demonstrated.** Two SQLAlchemy sessions on separate connections against an
on-disk database, which is a genuine race at the database. **Not** two operating-system
processes: SQLite is single-writer, this project runs one worker, and `docs/OPERATIONS.md`
says so rather than implying more.

### DEC-0062 — `active_dedupe_key` is nullable and unique; `dedupe_key` is permanent

**Decision.** Two columns. `dedupe_key` is the job's permanent identity, kept for audit.
`active_dedupe_key` holds the same value while the job is pending or running and is set to
NULL the moment it stops — succeeded, terminally failed, or cancelled.

**Why.** CRM.md section 9 requires at most one pending refresh per assignment, so
concurrent visitors cannot each trigger a chargeable provider call. A permanent unique key
on the claim would deliver that and then make the *second* legitimate refresh of an
assignment impossible forever — a worse bug than the duplicate it prevented. NULLs are
distinct in a unique index on both SQLite and PostgreSQL, so terminal rows stop
constraining while two live enqueues still collide.

### DEC-0063 — Authenticity, deduplication, and processing are three independent axes

**Decision.** An inbound notification is judged on three separate columns.
`verification_state` says what can be established about where it came from; `dedupe_key`
says whether it has been seen; `processing_state` says what has been done about it.

**Why they must not be collapsed.** Deduplication runs on an *unverified* payload, because
a forged replay of a genuine event is still a replay — and if replay detection depended on
authenticity, the deduplication table would become a place an attacker could write into. A
forged payload is stored rather than discarded, because a forged delivery is exactly the
thing an operator later wants to look at.

The rules that follow:

* a signature-capable adapter **must** reject a missing, malformed, or invalid signature,
  and such an item creates **no job at all** — no number of attempts turns an invalid
  signature into a valid one, and a retryable forgery would be a way to keep the queue
  busy;
* a provider with no signature mechanism produces `unsigned_untrusted`. The **only** thing
  such a notification may cause is an authenticated read, and the *answer* is what may
  move a parcel. The claim in the body is ignored entirely;
* only `signature_valid` or `verified_by_read` may create a normalized provider event, and
  the worker re-checks that at application time rather than trusting the enqueue;
* an adapter that does not declare `verifies_signatures` is never asked to verify. Asking
  would produce an answer, and any answer would be a claim the provider does not support.

**No signature algorithm has been invented.** The fake adapter's HMAC scheme exists in
`backend/tests/fakes/fake_provider_adapter.py` and is not a model of anything.

### DEC-0064 — `integration:read` is separate from `integration:manage`

**Decision.** A new `integration:read` permission gates the health surface, held by admin
and read-only manager. `integration:manage` remains admin-only and gates the retry and
disable actions.

**Why.** CRM.md section 12 wants integration health and stale-tracking warnings visible to
authorized staff, while section 11 keeps API credentials away from most roles. Health
carries counts and states and no secret, so it can be read more widely than the
integration can be changed. Customer service, operations, and marketing hold neither.

**Needs business confirmation** that operations should not see integration health. The
argument for granting it is that operations does carrier mappings; the argument against is
that they cannot act on what they would see.

### DEC-0065 — Stale-assignment count is `null`, not zero

**Decision.** `integration_health.stale_assignment_count` is `None`, with a
`stale_rule_description` explaining why.

**Why.** A freshness threshold needs a provider's documented update cadence, and there is
no provider. Reporting `0 stale` is not a neutral placeholder: it asserts that everything
is fresh, which is a **stronger and falser** statement than "we cannot tell". `Design.md`
section 5 makes the same point about KPI comparisons — an unavailable figure is omitted,
never fabricated. The same reasoning keeps `provider_api_version`, `last_success_at`, and
the worker heartbeat absent until something real fills them.

### DEC-0066 — A provider event never overwrites a manual one

**Decision.** `event_service._SOURCE_TIE_RANK` breaks a tie at an identical `occurred_at`
in favour of a manual event. Provider events are applied through
`event_service.record_event` with `source="provider"`, and nothing in
`integration_event_service` voids, edits, or deletes an existing event.

**Why the tie-break is needed at all.** Occurred-time ordering alone does not deliver the
rule: a provider event stamped at the same instant as a staff correction is *recorded*
later and would win on `recorded_at`. A staff member who has looked at the parcel is the
better authority when the two disagree about the same moment.

**This changes nothing about Phase 2.** Every event written before Phase 4A has
`source = "manual"`, so the rank is constant across them. It is also **not** a status
ranking: it settles a tie at an identical occurred time and never decides whether a newer
event may overwrite an older one, which remains occurred time alone (DEC-0037).

The ranking was initially written the wrong way round — `max()` selects the *highest*
tuple, so manual needed the higher rank — and a test caught it.

### DEC-0067 — Provider events are applied through the existing reducer, never around it

**Decision.** `integration_event_service` writes a `shipment_events` row through
`event_service.record_event` and lets `recompute_status` run. It re-implements no status
rule.

**Why.** Every Phase 2 invariant lives in that function: only `delivered_to_recipient` can
complete a package, a warehouse receipt and a collection-point handover cannot be flagged
as final delivery, a future occurred time is refused, and public wording needs its own
explicit flag. A second write path would be a second place for those to be forgotten, and
the failure would be a customer told their parcel was delivered when it reached a
warehouse.

Three consequences fall out rather than needing special cases: one delivered package of
three is Partially delivered; an intermediate warehouse receipt is a milestone; and an
older In Transit event is simply not the latest, so it cannot regress Delivered.

**A provider event never carries public wording.** `is_public_update` is false and
`public_update_text` is null; the provider's description goes to `internal_detail`, where
a staff note goes. A provider sentence is not approved public wording (CRM.md section 10).

### DEC-0068 — A missing occurred time is refused, never replaced by the received time

**Decision.** A normalized event with no `occurred_at` is stored and marked `REJECTED`
with `occurred_time_provenance = missing`. It is not applied.

**Why.** `received_at` is when a message arrived, not when anything happened. Putting a
delivery time on a parcel because that is when a webhook landed is a fabricated milestone,
and the customer plans around it. A wall-clock time with no zone is recorded as
`local_no_timezone` rather than assumed to be UTC, which CRM.md section 9 requires
explicitly — a four-hour error in a delivery time is a customer complaint.

### DEC-0069 — The resource-fetch policy is built and tested; no request is made

**Decision.** `app/integrations/resource_policy.py` implements the full rule set — HTTPS,
exact host allowlist, exact path-prefix allowlist, no URL credentials, no fragment,
approved ports, DNS checks rejecting loopback, private, link-local, multicast, reserved
and unspecified destinations for both address families, revalidation after resolution and
on every redirect, a strict hop limit, credential stripping across origins, and response
size, timeout, and content-type limits. The DNS resolver and the transport are
**injected**, and production supplies no transport, so `fetch_guarded` refuses.

**Why build it now.** These rules are much easier to get right written calmly against a
test suite than written in a hurry beside a first real integration. The tests cover
`localhost`, `127.0.0.1`, IPv6 loopback, RFC1918 and link-local, the numeric and
hexadecimal host forms, user-info URLs, host-suffix confusion, unapproved paths, unsafe
redirects, DNS rebinding, and credential stripping — none of which can be demonstrated
against real DNS and a real server.

**Exact host matching, never a suffix.** `provider.example.test.attacker.test` ends with
an allowed host and is a completely different server.

**A URL from an unverified payload is refused before anything else is checked.** No amount
of host validation makes it sensible to act on an instruction from an unauthenticated
stranger.

**The production allowlist is empty and a test asserts it stays empty.** The hosts and
paths a real fetch would need are unverified (`docs/INTEGRATIONS.md` section 3), and a
plausible guess in an allowlist is worse than an empty one.

**A note for whoever writes the first real allowlist.** RFC 5737 documentation addresses —
`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32` — are classified as
non-global by Python's `ipaddress` module, and this policy correctly refuses them. A test
fixture written against one of those will fail, and the fix is the fixture, not the policy.

### DEC-0070 — The only adapter is a fake, and it lives in the test suite

**Decision.** `PRODUCTION_ADAPTERS` is empty. `AdapterRegistry.register` raises while
`settings.is_production`. The only implementation is
`backend/tests/fakes/fake_provider_adapter.py`, whose provider key is `fake` and whose
statuses are invented words no carrier uses.

**Why not a ShipStation adapter.** The account's product, API generation, entitlements,
authentication scheme, webhook event types, signature mechanism, rate limits,
external-label tracking support, and resource hosts are all unverified. An adapter built
on guessed fixtures would encode every one of those assumptions, and a passing test suite
would then read as evidence that the integration works.

**Three independent reasons it cannot reach production**, because the cost of being wrong
is a synthetic provider answering a real customer: it is not packaged, its key is `fake`,
and registration is refused by environment. The environment check is on the *environment*
rather than on the adapter deliberately — recognizing a fake reliably is the harder
problem, and getting it wrong is the expensive one.

### DEC-0071 — The Settings panel is titled "Integration infrastructure"

**Decision.** The Settings tab describes the durable inbox, the job queue, and the worker.
It shows "No provider account is connected", "Automatic tracking is unavailable", and a
note that manual milestones and external links continue to work. There is **no Connect
button and no Verify button**, and no endpoint behind either.

**Why not a provider card.** `Design.md` section 13 asks for provider cards showing
source, version, connection state, last successful sync, last error, and pending or failed
jobs. There is no provider, so a card shaped like one would be a card about nothing, and
the fields would all read as empty rather than as inapplicable.

**Why no Connect button.** It could not perform a real operation. CRM.md section 9 is
explicit that receiving a tracking number or a URL does not authorize or enable API
tracking; a button implying otherwise is the interface making that mistake on the
customer's behalf. The Disable action exists in the API, answers 404 with no connections,
and is not rendered while there is nothing to disable.

### DEC-0072 — Error summaries are categories, and redaction is the second line

**Decision.** A stored `error_code` is always a `ProviderErrorKind` value, never a provider
status code. A stored `error_summary` is a short phrase the adapter chose, passed through
`redaction.safe_summary` on the way to the database even when the caller believes it is
already safe. `safe_exception_summary` returns the exception *type name* rather than
`str(error)`.

**Why not the exception text.** A provider client raises exceptions whose message contains
the request URL, and sometimes the request headers — which is how a credential reaches a
log without anybody deciding to put it there.

**What the patterns cover, and why two of them exist.** URLs keep only scheme, host, and a
digest; emails, Solaris references, long digit runs, and long base64-shaped runs are
replaced. Two more were added because tests caught what length-based rules missed: an
authorization value (`Bearer super-secret-token` is eighteen characters of token and
sailed past a 24-character threshold) and a reference-shaped token (`FAKE-TRACK-0001` and
`1Z999AA10123456784` are neither long digit runs nor Solaris identifiers). Short numbers
survive on purpose — an over-redacted log is a useless log, and attempt counts and seconds
are not identifiers.

**Headers are dropped rather than masked.** A masked entry still records that a request
carried a particular header, and the stored value has no use that justifies keeping even
that. Four diagnostic headers are kept by allowlist.

### DEC-0073 — The inbox link to a normalized event is stored once, on the event

**Decision.** `integration_provider_events.inbox_item_id` is the only stored link between
the two, with a unique constraint and a SQLAlchemy relationship navigable from either
side. `IntegrationWebhookInboxItem.normalized_event` and `resulting_shipment_event_id`
read through it.

**Why.** A column on both tables would be a circular foreign key. SQLite tolerates one at
the SQL level, but SQLAlchemy's metadata sort raises `CircularDependencyError` and the
`use_alter` workaround emits an `ALTER TABLE ADD CONSTRAINT` that SQLite cannot execute.
One stored link also cannot disagree with itself, which two columns eventually would.

### DEC-0074 — An oversized payload is refused, not truncated

**Decision.** A body over `INTEGRATION_WEBHOOK_MAX_BYTES` is stored as a digest with
`payload_omitted = true` and no body, and is rejected. An unexpected content type is
rejected rather than parsed. Both are stored rather than discarded.

**Why refused rather than truncated.** A truncated payload parses into something the
provider did not send, which is worse than having nothing at all. The digest is over the
exact bytes received, so a redelivery of the same oversized payload is still recognized.

**Why stored rather than discarded.** An operator investigating "the provider says it sent
us this" needs something to look at, and a provider retrying an oversized payload forever
would otherwise leave no evidence of why.

---

## Phase 5A decisions

Phase 5A implements reporting, CSV export, and CSV customer import. It changes no
integration file.

### DEC-0075 — ShipStation and all live-provider work is deferred to the final phase

**Decision.** The owner has deferred automatic provider synchronization until the end of
the project. Phase 4B is not implemented in Phase 5A. No production provider adapter is
created or registered, `PRODUCTION_ADAPTERS` stays empty, no request is made to
ShipStation, ShipEngine, a carrier, or any other external provider, no webhook endpoint
for a real provider exists, the production resource host and path-prefix allowlists stay
empty, `connected_api` stays refused, no carrier freshness or last-successful-sync value
is fabricated, and integration health remains `not_configured`.

**Why this is recorded as a decision rather than a limitation.** Phases 1 through 4A
described the missing provider as a *blocker*: something that would be resolved as soon as
nine questions were answered. It is now a *schedule choice*. The distinction matters,
because a reader who believes the integration is imminent will interpret an empty
allowlist or a `not_configured` health panel as an unfinished edge. It is neither
unfinished nor an edge — it is the specified state of the system until the final phase.

**What is preserved, deliberately.** Manual milestone tracking and verified external-link
tracking are the two modes the business actually uses today, and they are untouched. So is
every part of the Phase 4A seam: the durable inbox, the job queue, leases, retries, the
worker, the adapter contract, the mapping layer, and the SSRF resource policy. That seam
was built provider-neutral precisely so a deferral would cost nothing, and this decision
is the first real test of that claim. Adding a verified provider later remains one adapter
file, one registry entry, and one webhook endpoint.

**What Phase 5A must therefore not do.** No report may display a carrier freshness figure,
a last-update time, or a last-successful-sync time, because no such value exists and a
plausible-looking one would be a fabrication. The shipment-exception report groups by
tracking source mode and shows `manual`, `external_link`, and `none` — it does not render
an empty `connected_api` column, because a column implies a mode that could have data.

**Reversal.** Reversing this decision means executing the five steps in
`docs/INTEGRATIONS.md` section 9 ("What must happen before anything is described as
live"). Nothing in Phase 5A makes any of those steps harder.

### DEC-0076 — Report periods are bounded, half-open, and cut in the organization timezone

**Decision.** A report period is `[start, end)`. The caller supplies two dates; the start
is midnight at the beginning of `from` in `organization_settings.office_timezone` and the
end is midnight at the beginning of the day after `to` in the same timezone, both
converted to UTC before they reach a query. A period is refused unless `from <= to`, the
span is at most 731 days, and neither date is more than 50 years from today.

**Why the organization timezone rather than UTC.** A parcel handed over at 23:30 on 30
September in Mississauga is September business. Cutting on UTC midnight would move it into
October for four hours of every day, and the operator reading the report would have no way
to tell which figures had been shifted. `America/Toronto` also observes daylight saving,
so the offset is not a constant and cannot be hard-coded; the boundary is computed through
`zoneinfo` for the specific date.

**Why half-open.** An inclusive end would either drop the last day's evening or
double-count a shipment sitting exactly on a boundary between two adjacent periods. A
half-open interval tiles without gaps or overlaps, which is the property that makes
adjacent periods sum to the whole.

**Why bounded.** An unbounded range is a table scan the operator did not intend, and 731
days is two years plus a leap day — enough for any year-over-year question the launch
business has, and small enough that the query stays predictable.

### DEC-0077 — Every metric is reconciled against an independent calculation in tests

**Decision.** Each report metric has a test that recomputes the same figure directly from
the database by a different route — usually a plain Python loop over the fixture rows —
and asserts the two agree. The service and the test do not share a helper.

**Why.** A test that calls the same query the service calls proves only that the query is
deterministic. The failure mode that actually matters in a reporting feature is a *wrong
definition*: counting a package as a shipment, counting a cancelled booking, counting a
merged customer twice, or cutting a period on the wrong side of midnight. Only an
independent calculation catches that, and it catches it at the point where the definition
is written down rather than months later when somebody notices the totals disagree with
the shipment list.

### DEC-0078 — Import provenance is a source key, and the raw upload is never persisted

**Decision.** Customer import idempotency is keyed on `(source_system, source_record_id)`,
enforced by a unique index. `source_record_id` is the CSV's own `source_record_id` column
when the file supplies one; otherwise it is a deterministic digest over the row's
normalized identity fields. The uploaded file itself is parsed in memory and never written
to disk, and no table stores an imported cell value.

**Why a digest fallback.** Most real customer lists exported from a spreadsheet have no
stable key. Without one, a second import of the same file would create a second copy of
every customer, which `CRM.md` section 13 forbids. A digest over the normalized email,
phone, and name gives the same row the same identity across imports without inventing a
column the operator has to fill in.

**Why the raw upload is not persisted.** `CRM.md` section 11 asks for privacy-minimal
collection, and a staging table holding un-reviewed personal data is a second copy of the
customer database with none of its access controls. The preview is computed and returned;
the commit re-uploads and re-validates the same file, verified by a content digest so the
operator cannot preview one file and commit another. The cost is one extra upload of a
bounded file; the benefit is that a preview that is abandoned leaves nothing behind.

### DEC-0079 — A preview writes nothing, and a commit is one transaction

**Decision.** The preview stage performs no write of customer data at all. The commit
stage runs inside a single transaction: either every accepted row is created and the batch
record is written, or nothing is. Rows that failed validation at preview are not part of
the commit and do not prevent the accepted rows from committing.

**Why row-level rejection but batch-level atomicity.** These sound contradictory and are
not. A row that fails validation is *excluded* before the transaction opens — it was never
a candidate. A row that fails *during* the transaction indicates the database disagrees
with what validation concluded, which means the validation was wrong, and committing a
partial result on top of a wrong premise leaves the operator with no way to know what
landed. So: validation decides membership, and the transaction is all-or-nothing over the
members. The completion summary reports both counts separately.

### DEC-0080 — Exports stream, and every export has a column allowlist

**Decision.** Every export is a `StreamingResponse` over a generator that pages the query
in bounded batches. Every export type declares an explicit list of columns; the serializer
reads only from that list and has no path that reflects over a model.

**Why an allowlist rather than an exclusion list.** An exclusion list is wrong the moment
somebody adds a column. Phase 4A added a `payload_text` column to a new table and Phase 2
added address snapshots to `shipments`; under an exclusion list each of those would have
appeared in an export by default, and the person adding the column is not the person
thinking about exports. The allowlist fails the other way — a new column is invisible
until somebody adds it deliberately — and that is the safe direction.

**Why streaming.** `CRM.md` section 13 does not set a row limit on exports and the
business expects to export its whole customer list. Materializing that into one string in
memory is fine at ten customers and is not fine later; the generator holds one batch at a
time regardless of the total.

### DEC-0081 — A formula-injection guard covers the newline prefixes too

**Decision.** `escape_csv_value` prefixes a value with an apostrophe when it begins with
`=`, `+`, `-`, `@`, tab, carriage return, **or newline**.

**Why the change.** The Phase 1 implementation covered the first six. A leading newline is
the seventh documented vector: some spreadsheet importers strip leading whitespace,
including a newline, before evaluating the cell, so `\n=cmd|...` reaches the formula parser
as `=cmd|...`. The value is prefixed rather than stripped because stripping would silently
alter a Vietnamese address whose first character is legitimately whitespace.

### DEC-0082 — New Phase 5A permissions are granted to Admin only, pending the owner's decision

**Decision.** `import:template`, `import:preview`, `import:commit`, `duplicate:review`,
`export:shipments`, and `export:reports` are added to the permission matrix. Except for
`duplicate:review`, which is granted to every role that could already reach the duplicate
endpoints so that nothing regresses, all of them are granted to **Admin only**.

**Why the narrow default.** `CRM.md` section 11 gives Customer Service a broad operational
remit and says Marketing gets no unrestricted operational exports, but it does not say who
may bulk-import a customer list or bulk-export shipments. Those are exactly the two
operations that move the whole database across a boundary in one action. The final
Operations and Marketing permission set is an open business decision (`PROJECT_STATUS.md`
section 7), and widening a permission later is a settings change, while narrowing one
after staff have been trained on it is a support incident. Admin-only is the reversible
default.

**What this is not.** It is not a claim that Customer Service should never import
customers. It is a claim that nobody has decided yet, and that the safe placeholder is the
role that already holds every other permission.

### DEC-0083 — A timeline event publishes to the customer by default, except in the exception states

**Decision.** The "Publish this update to the customer" box starts **ticked**, and the
first approved template for the event type is already selected. It starts **unticked** for
`exception`, `delivery_attempted`, `return_in_progress`, and `awaiting_parcel`. Staff can
change it either way on any event; the checkbox is not removed.

**Why the default flipped.** Recording a milestone and telling the customer about it were
two actions, and the second one was opt-in, so it was routinely skipped — a customer could
watch a parcel cross the world and see nothing. Publishing is the norm, so it is now the
default, and staying silent is the deliberate act. That also makes an unpublished event
mean something: somebody chose it.

**Why the four exceptions.** These are the states where the system knows something is
wrong but not yet *what*. A canned "there is a problem with your shipment" fired
automatically the moment a warehouse clerk flags an exception tells the customer something
staff cannot yet stand behind, and invites a call nobody is ready to take. Publishing
stays one click away once the facts are known.

**Why the box was not removed.** An operational timeline has to be able to hold an
internal note — a damaged carton, a warehouse correction, a mis-scan. Forcing every event
to be customer-visible would not delete that need; it would push it somewhere with no
audit trail.

### DEC-0084 — A public milestone stores an approved template key, not a sentence

**Decision.** `shipment_events.public_update_template_key` holds a key into a versioned
catalogue (`backend/app/content/public_update_templates.json`). The public tracking API
returns that key as `timeline[].message_template_key`, and each surface renders it in its
own reader's language. Free text remains available and unchanged; an event carries a key
**or** free text, never both. Template keys are immutable — wording changes by adding a
new key, never by editing an existing one.

**Why.** The public tracking page is genuinely bilingual with a visible language switch,
and every string on it was translated except the one that mattered most: the milestone a
customer actually reads. A staff member working in English published English, and a
Vietnamese customer got an English sentence in an otherwise Vietnamese page. Storing the
key rather than the sentence is what lets the same event render correctly for both.

**Why not render server-side per request.** The page would then have to refetch the whole
tracking result on every language switch. That defeats its deliberate no-refetch design
and spends the customer's public rate-limit allowance on pressing a language button.

**Why exclusive rather than merged.** If an event could carry both, the customer's
language would silently decide which of two different messages they read, and staff would
have no way to see what was actually published.

**Why immutable.** The row stores a key, so editing a key's wording rewrites what a
customer was told last week. A screenshot would stop matching the page.

**What is not settled.** The Vietnamese wording in the catalogue has **not** been reviewed
by a native speaker. It is written to be plain and to promise nothing, and the staff form
shows both languages before sending, but it needs a review before it can be called
approved. See `PROJECT_STATUS.md` section 7.

---

## Phase 5B decisions

### DEC-0085 — A correlation id is echoed to staff, never to the public

**Decision.** Every request is assigned a correlation id, carried on every log record for
that request and returned in the `X-Correlation-ID` response header — **on the staff API
only.** Public tracking responses carry no such header.

**Why.** DEC-0051 requires every public failure to be indistinguishable from every other:
same status, same body, same headers, so a stranger probing identifiers cannot tell an
unknown reference from a cancelled shipment. A per-request header is, by definition, the
one value that differs between two otherwise identical responses.

This was not foreseen. Adding the header uniformly broke **eleven** Phase 3 boundary tests
at once, all of them correctly, and that is how the conflict was found.

**What is kept.** The id is still generated for public requests and still appears on every
log line for them, so an operator can join a customer's report to the logs. It is simply
not handed to the customer. The privacy boundary costs nothing operationally.

### DEC-0086 — Measured contrast outranks a stated brand value

**Decision.** Where a `Design.md` colour token is used for text, an interactive control, a
focus indicator, or an icon whose contrast carries meaning, its value is **whatever meets
WCAG 2.2 AA**, measured. Three values were corrected. The original brand orange is
retained as a decorative reference token and must never be used where contrast matters.

**Approved by the owner**, 2026-09-14, for text-bearing and interactive surfaces.

**Why.** `Design.md` section 3 gave `brand.orange.600` as `#E9652A` and annotated it
*"selected to retain white-text contrast"*. It does not. Section 15 of the same file
requires WCAG 2.2 AA. The file therefore contradicted itself, and the contradiction was
not academic: **every primary button in both applications** — Track, Sign in, Save, Add
customer, Import — sat below AA on that one wrong annotation.

Between a requirement and a value that fails it, the requirement is what the value was
trying to satisfy. So the requirement wins.

#### The measurements, before and after

All ratios computed by the WCAG 2.x relative-luminance formula and independently confirmed
by axe-core 4.13.0 in a real browser.

| Use | Before | Ratio | Required | After | Ratio |
|---|---|---:|---:|---|---:|
| White text on the primary button | `#E9652A` | **3.30:1** | 4.5:1 | `#C94D15` | **4.61:1** |
| Teal badge text on `accent.teal.100` | `#16867D` | **3.99:1** | 4.5:1 | `#147B73` | **4.61:1** |
| Public footer wordmark on `neutral.50` | `#F47A3A` | **2.61:1** | 4.5:1 | `#BD4814` | **4.89:1** |

Supporting measurements for the new tokens on every surface they land on:

| Token | On white | On `neutral.50` | On its tinted badge | White on it |
|---|---:|---:|---:|---:|
| `brand.orange.600` `#C94D15` | — | — | — | **4.61:1** |
| `brand.orange.700` `#BD4814` | 5.12:1 | 4.89:1 | 4.60:1 | — |
| `accent.teal.700` `#147B73` | 5.11:1 | 4.88:1 | 4.61:1 | — |
| `brand.orange.500` `#F47A3A` *(unchanged)* | 2.73 ✗ | 2.61 ✗ | — | — |
| `brand.orange.ref` `#E9652A` *(retained, decorative)* | — | — | — | 3.30 ✗ |

`brand.orange.500` on `brand.navy.900` measures **5.36:1** and is the correct token there.

#### What was deliberately *not* changed

**The corporate brand palette has not been changed or approved.** This decision governs
the application's *semantic interaction tokens* only. `#E9652A` is retained in the token
table as `brand.orange.ref`, decorative and referential, so the original value stays on
record.

Every replacement keeps the brand **hue and saturation exactly** — 18.5° for the orange,
unchanged for the teal — and moves only lightness. These are the same colours, deeper, not
a re-hue.

`brand.orange.500` and `accent.teal.600` keep their original values for non-text use,
where the 3:1 bar applies and they clear it.

**If a future approved brand kit supplies different values, the semantic interaction
tokens must still meet AA.** A brand kit does not lower the bar; it supplies candidates
that then have to pass.

#### Why the accent had to become contextual

The wordmark appears on a navy header *and* a light footer. Fixing the footer with one
darker colour broke the header, where the darker ink is 3.02:1 and the lighter is 5.36:1.
The audit caught it on the next run. The same mistake was then made again on the login
page, whose background is navy and which I had assumed was a light card — caught again and
reverted.

Hence `--wordmark-accent`, defaulting to the light-surface token and overridden on dark
surfaces, and hence auditing **every** screen rather than a representative one.

#### How it is kept

`frontend/tests/contrast.test.js` computes every corrected pairing from the token file and
fails the build if any drops below its threshold — so a future edit to a hex value cannot
silently undo this. The axe audit covers the rendered result at both viewports, and
`EXPECTED_FINDINGS` is empty: nothing is suppressed.

### DEC-0087 — Proxy-header trust is refused unless both halves are configured

**Decision.** In production the application refuses to start when
`TRUST_PROXY_HEADERS=true` and `TRUSTED_PROXY_HOSTS` is empty, and equally when the
reverse holds. Both, or neither.

**Why.** This makes DEC-0048's "both halves, or neither" enforceable rather than advisory.
Half a proxy configuration is worse than none, because it *looks* configured while leaving
the public rate limiter keyed on a value the caller chooses. A setting that must be right
and is only documented is a setting that will eventually be wrong.

**Phase 5B did not enable proxy trust.** Both settings remain off, asserted by test. The
conditions for turning them on are in `docs/DEPLOYMENT.md`.

---

## Phase 7 decisions

### DEC-0088 — Merge Customer Service into Operations, using the former Customer Service permission set

**Decision.** The `customer_service` role is retired. The surviving `operations` role
carries **the complete former Customer Service permission set**, unchanged. The owner
selected **Option A** from the three options put to them.

**Why this is a merge and not a widening of two roles into something new.** The former
Operations set was a **strict subset** of the former Customer Service set — twelve
permissions, every one of which Customer Service also held. Verified, not assumed:

```
former Operations  (12) ⊂ former Customer Service (29)     → strict subset: True
merged Operations  (29) = former Customer Service (29)     → identical
```

So no staff member could do anything as Operations that a Customer Service colleague could
not already do, and the merged role grants no permission that was not already held by
somebody doing this work. **No permission was invented to make the sets meet.**

**What merged Operations gains over former Operations.** Seventeen permissions:

| Area | Permissions gained |
|---|---|
| Customer management | `customer:create`, `customer:update`, `customer:archive` |
| Addresses | `address:write` |
| Consent | `consent:read`, `consent:write` |
| Duplicate review | `duplicate:review` |
| Tags and referrals | `tag:read`, `tag:write`, `referral:read`, `referral:write` |
| Segments | `segment:read`, `segment:write` |
| Shipment cancellation | `shipment:cancel` |
| Reporting | `report:read` |
| Revenue | `financial:read`, `financial:write` |

**What is deliberately still absent.** `financial_cost:read` is **not** in the merged set
and remains Admin's alone. Carrier cost and profit are therefore still structurally absent
for Operations — not blanked, not zeroed, not masked, but never serialized into the
response at all. This is the boundary DEC-0033 drew and this decision does not move it.

**What changes for Marketing and the read-only manager.** Nothing. Neither set is touched.

#### This changes role semantics, and invalidates the affected RC-UAT-3 results

RC-UAT-3 was frozen against a tree in which Customer Service and Operations were separate
roles with different permission sets. Every case that asserted an Operations *negative*
boundary over the seventeen permissions above now asserts something that is no longer
true — most sharply `UAT-OP-10`, whose expected result was that Operations holds neither
`financial:read` nor `financial_cost:read`. Half of that is now wrong.

**No completed human UAT result is being discarded, because none existed.** Human UAT was
on hold when this decision was taken; every result, defect, reviewer and sign-off field in
the RC-UAT-3 pack was blank and remains blank. What is superseded is the *case set*, not a
set of outcomes. RC-UAT-3 stays frozen and historically valid as the record of what was
prepared; it is superseded for future execution by the remapped case set, and the
supersession is recorded rather than applied by editing the frozen pack.

#### Rollback and migration consequences

The migration (`a1c7f4d92b30`) is **exactly reversible**, which the first attempt at it was
not. Merging two role values into one destroys the information needed to separate them
again, so the upgrade writes that information down first, in a migration-owned
`role_merge_provenance` table holding a user id, the previous role, the migration id and a
timestamp — and nothing else. No password hash, no session token, no profile field.

* Upgrade captures the pre-merge role of **both** populations before changing any row, then
  maps `customer_service` to `operations`.
* Downgrade restores each captured account to its exact pre-upgrade role, then deletes only
  the rows it wrote.
* An account **created after the upgrade** has no pre-merge role to restore. The contract is
  that it stays `operations`, and the downgrade reports how many such accounts it found
  rather than inventing a role for them.

`backend/tests/test_migrations_role_merge.py` compares the whole `users.role` column as a
mapping before and after a round trip, across every population shape — only former Customer
Service, only former Operations, both, several of each, none, empty, and a populated
pre-merge deployment. A migration is not called reversible here on the strength of its
docstring.

**Reversible.** Yes, and demonstrated. Reverting the decision is a `downgrade` plus
restoring the `_CUSTOMER_SERVICE` permission set and the enum member; the role rows come
back exactly.

**Still open.** The production staff list has not been reviewed against the merged role.
Any real deployment running this migration widens its former Operations accounts by
seventeen permissions, and that is a change an owner should see the staff list for. Recorded
in `PROJECT_STATUS.md` section 9.

**What this decision does *not* settle.** DEC-0082 left the final Operations and Marketing
permissions **for import and export** open, and this decision does not answer it. Merged
Operations holds neither `import:*` nor `export:customers`/`export:shipments`; those remain
Admin-only placeholders awaiting the owner. Option A merged the two roles; it did not widen
the merged role beyond what Customer Service already held.

### DEC-0089 — `alembic check` excludes exactly one migration-owned table

**Decision.** Alembic autogeneration is given an `include_object` hook that hides exactly
one object from comparison: a **reflected** table named `role_merge_provenance` that has
**no counterpart in the model metadata**. Everything else in the database is compared as
before. The hook lives in `backend/alembic/autogenerate_policy.py`; `backend/alembic/env.py`
passes it to both the online and the offline configuration.

**Why.** `role_merge_provenance` is created, written, read and dropped entirely by the
role-merge migration `a1c7f4d92b30` (DEC-0088). It is what makes that migration reversible:
it holds the role each account had before the merge so the downgrade can restore it. No ORM
model maps it, deliberately — it holds staff identifiers outside the access controls that
protect `users`, and a mapped model is a runtime handle on exactly that.

Autogeneration therefore saw a table with no model behind it and proposed the only thing it
could: `DROP TABLE role_merge_provenance`. Two bad outcomes followed from leaving that in
place. Applying such a generated migration would silently make the role merge
irreversible. And short of that, `alembic check` failed on every run against any database at
head — so the project had a drift check that was permanently red, which is a drift check
that reports nothing. A real difference would have arrived as one more line in a message
everybody had already learned to expect.

**Why not the alternatives.**

* **Map the table into the ORM.** It would make the check green by creating the runtime
  handle the migration was designed not to have, and it would move ownership of the table
  from the migration to the application. Rejected; the table is migration bookkeeping.
* **Ignore any unmapped table.** That is the rule that would have hidden the next
  hand-created table, the next half-applied migration, and the next restored-from-backup
  schema. The exclusion is one literal name for that reason.
* **Ignore a name prefix or pattern.** A `role_merge_provenance_backup` left behind by a
  manual repair is drift and must be reported. Matched literally and whole.
* **Stop running `alembic check`.** It is the only automated statement that the schema in a
  database equals the schema the models describe.

**Scope, stated as limits rather than intent.**

* The hook returns `False` only when `type_ == "table"`, the object is `reflected`, its
  `compare_to` is `None`, and its name is in `MIGRATION_OWNED_TABLES` — today a
  one-element set.
* If anybody ever *does* map this table, `compare_to` stops being `None` and the exclusion
  stops applying to it in the same commit, with no second change required.
* Column, type, index and constraint comparison on every mapped table is untouched.
* **What it costs:** while the table is unmapped, drift *inside* it is not detected either,
  because the whole object is skipped. The migration is its only writer, and
  `backend/tests/test_migrations_role_merge.py` asserts its shape column by column —
  including the columns it must never grow — which is where that guarantee lives instead.

**How it is proven.** `backend/tests/test_alembic_autogenerate_exclusion.py` runs the real
CLI against throwaway databases. One test asserts the green case *and* that the excluded
table is actually present while the check passes, so a green result cannot come from the
table being absent. Six assert that a deliberately introduced unrelated difference still
fails: another unmapped table, four near-miss names, an added column and a dropped column on
a mapped table. Two assert the migration still creates the table on upgrade and drops it on
downgrade. Four exercise the hook directly, including the branch no CLI run can reach while
the table is unmapped — that a mapped counterpart re-enables comparison.

**Standing requirement.** Every future schema phase keeps `alembic check` green against a
database at head, and does so by the schema and the models agreeing — not by adding names
to the exclusion. A future migration must not drop, map or repurpose `role_merge_provenance`
by accident; it is owned by `a1c7f4d92b30` and by nothing else.

**Reversible.** Yes. Deleting the hook restores the previous behaviour exactly, at the price
of restoring the permanently failing check.

### DEC-0090 — The Customer Account is a third surface, not a mode of the Staff Portal

**Decision.** The authenticated customer surface gets its own router (`app/api/account`), its
own dependency module, its own cookie realm, its own rate-limit key namespace and its own
response schemas. Nothing is shared with the Staff Portal or Public Tracking except the
database engine, the normalization and duplicate services, and the brand.
**Why.** `app/api/public/deps.py` already exists as a separate file for one reason: a staff
dependency must not be attachable to a customer-facing route by reflex. The same reasoning
applies with more force to a surface that *is* authenticated, because there the mistake
produces a working session rather than an obvious error.
**Alternative rejected.** A `is_customer` flag on `users` with permission sets adjusted. It
would place customers one permission-map bug away from 97 guarded staff routes.
**Reversible.** Yes, but expensively once built. Recorded as a requirements-phase decision so
it is reversed deliberately rather than eroded.
**Requirements only.** No code exists. Specified in
`docs/customer_account/IDENTITY_AND_AUTHORIZATION.md`.

### DEC-0091 — The identity-to-customer link is a table, not a column

**Decision.** `customer_identity_links(identity_id, customer_id, link_role, status, …)` with
partial unique indexes enforcing the release-1 rule — one active link per identity, one
active identity per customer — rather than a nullable `customer_id` on the identity row.
**Why.** OD-25 requires release 1 to be one-to-one *and* requires that later company access
must not mean rebuilding identity ownership. A column satisfies the first and fails the
second: relaxing it later would change the shape every ownership check reads. With a link
table, relaxing it is dropping an index and permitting a second `link_role`.
**Cost.** One more join on every authenticated request, and a uniqueness rule that lives in an
index rather than in a column type.
**Reversible.** Yes.

### DEC-0092 — Customer-submitted data lands as proposals; the surface has no canonical write path

**Decision.** Registration and profile updates write `customer_data_proposals` and
`customer_data_proposal_fields`. Canonical tables — `customers`, `customer_addresses`,
`consent_events` — are written only inside the staff approval transaction, through the
existing customer service, with the existing audit and duplicate review.
**Why.** OD-23 and OD-28 require it, and it has a structural consequence worth naming: a bug
anywhere in the customer-facing code cannot corrupt the CRM. The worst outcome is a bad
proposal that a person then declines.
**Exception.** Two direct fields — preferred language and non-marketing operational
notification preferences — apply immediately (OD-27). Neither is identity-bearing and neither
feeds duplicate detection.
**Reversible.** Yes.

### DEC-0093 — Authenticated shipment schemas are standalone allowlists

**Decision.** `AccountShipmentListItem` (17 fields) and `AccountShipmentDetail` (the same 24
values Public Tracking publishes, re-declared) inherit from nothing, set
`from_attributes=False` and `extra="forbid"`, and are populated field by field by a service.
**Why.** The rule Phase 3 already applies to `app/schemas/public_tracking.py`: an internal
schema gains fields over time, and a public model that inherits one silently starts
publishing them. OD-31 states it as an owner requirement.
**Consequence accepted.** The 24 values are declared twice, in two files, and can drift. That
is the intent — neither surface can move the other by accident — and a field-count test on
each keeps the drift visible.
**Reversible.** Yes.

### DEC-0094 — Email delivery is a seam with a development capture behind it, and no provider

**Decision.** One `EmailTransport` interface; a capture implementation that writes locally and
opens no socket; a null implementation as the test default; **no production implementation
written**. The application never names a provider.
**Why.** OD-34 selects no provider and blocks production launch until the owner does, using
verified documentation. Writing a provider adapter now would mean choosing one by
implementation, and asserting quotas and API shapes nobody has verified.
**Consequence.** Registration is fully testable locally and **cannot launch in production**
until OD-34 and OD-37 are satisfied. That is a launch blocker on the register, not a task in
a backlog.
**Reversible.** Yes; the seam exists precisely so a provider can be added behind it.

### DEC-0095 — Phase 9 builds what the owner's instruction lists, not what the plan listed

**Decision.** Where the Phase 9 instruction and `docs/customer_account/IMPLEMENTATION_PLAN.md`
differ about Phase 9's contents, the instruction governs and the difference is recorded rather
than reconciled silently. Three differences exist, all narrowings:

* the three deferred canonical columns are not added (DEC-0096);
* **change-password is not built.** The plan lists "forgot/reset/change password"; the
  instruction's scope list and its password-reset section both name request and completion
  only. Deferred to Phase 10;
* **no profile or consent route is built.** The plan lists `profile`, `profile/direct`,
  `profile/proposals` and `consent/marketing`; the instruction says not to implement profile
  editing. The registration proposal is written and nothing on this surface reads or edits it.

`GET /api/v1/account/me` **is** built, because the instruction requires a verified-but-
unapproved identity to reach a pending-account status and requires every response on this
surface to be an explicit allowlist. A status page needs a response.

**Why.** The implementation plan is this project's proposal; the instruction is the owner's
decision, and the plan itself says a phase is started by the owner rather than from the
document. Reinterpreting a narrowing as an oversight would be the project quietly restoring
scope the owner removed.

**Cost.** A customer who knows their password cannot change it in Phase 9; they can reset it
through the mailbox flow, which reaches the same place by a longer road.
**Reversible.** Yes. Each omission is an addition later, and none of them changes a schema.

### DEC-0096 — The three deferred canonical columns are not added in Phase 9

**Decision.** `customers` gains no `display_name` and no `legal_name`, and `AddressRole` gains
no `billing` member, in the Phase 9 migration. The three values are carried as allowlisted,
typed rows in `customer_data_proposal_fields` — `display_name`, `legal_name`, and the
`billing_address.*` keys — until their canonical treatment is implemented.

**Why.** `FIELD_MATRIX.md` section 6 names all three as gaps and expected them decided "in the
implementation phase, with a migration". The owner's Phase 9 instruction says otherwise:
record those values only in the approved pending-proposal representation until their canonical
treatment is implemented later. The owner decision governs.

There is an engineering argument for the same answer, which is why the instruction is easy to
follow rather than merely obeyed: nothing in Phase 9 can *apply* a proposal, because applying
one is a staff act and staff approval is Phase 10. A column added now would be a column with
no writer, and the phase that first writes it is the phase that can tell whether `full_name`
should become the legal name or sit beside a new one.

**Consequence.** The decision moves to Phase 10, where a real approval path exists to test it
against. The submitted values are not lost in the meantime —
`test_account_no_canonical_write.py` asserts they are present as proposal fields.
**Reversible.** Yes; it is an additive migration whenever it is taken.

### DEC-0097 — Auth tokens are keyed and purpose-bound; session tokens are not

**Decision.** `customer_auth_tokens.token_digest` is an HMAC-SHA256 over
`"<purpose>:<token>"` keyed with the application secret. `customer_sessions.session_token_hash`
stays the plain SHA-256 the staff realm uses.

**Why the difference.** Both inputs are 32 bytes of `secrets` output, so neither construction
is defending against a dictionary and the key buys nothing against brute force. It buys two
other things, and only for the emailed tokens:

* **purpose binding by construction.** The same random token digests differently for
  `email_verification` and `password_reset`, so a verification link presented to the reset
  endpoint matches no stored row even if a query forgot its `WHERE purpose` clause. The clause
  is still written; this is what makes forgetting it survivable (T-05).
* **deployment binding.** A restored database copy carries no live password-reset links into a
  second environment.

A session token has no second purpose to be confused with and never leaves the browser, so the
same treatment would add a key-rotation hazard for no gain.

**Cost, stated plainly.** Rotating `SECRET_KEY` invalidates every outstanding verification and
reset token. For credentials that live hours rather than days that is acceptable and arguably
desirable, and it is recorded here so it is not discovered during a rotation.
**Reversible.** Yes, at the price of invalidating outstanding tokens once.

### DEC-0098 — Registration idempotency is a ninth table

**Decision.** `customer_registration_attempts` is added to the eight tables
`docs/customer_account/DATA_MODEL.md` proposes. It holds a digest of the caller's idempotency
key (unique), a keyed digest of the normalized address, a fingerprint of the canonicalized
submitted fields, the internal outcome, and an optional identity reference.

**Why.** The Phase 9 instruction requires registration to be idempotent, to behave generically
when one key is reused with different data, and to survive concurrent equivalent requests
without creating duplicate identities, proposals, tokens or captured messages. SQLite has no
`SELECT … FOR UPDATE`, so a unique index is how this codebase serializes a claim — the shape
`booking_confirmations` already uses for exactly this problem (DEC-0031). Reusing it is cheaper
and better understood than a second idempotency mechanism, and it keeps duplicate suppression
in the database rather than in application memory.

**What it deliberately does not do.** It does not make a repeated registration for one address
an error. The per-address rate-limit bucket suppresses repeat work; a uniqueness constraint
there would make a second attempt answer differently from the first, which is the enumeration
oracle OD-23 forbids.

**Privacy.** No address, no body and no token. The address is a keyed digest and the
submission is a fingerprint — enough to tell "the same request again" from "the same key,
different data", and not enough to reconstruct either. The password is deliberately outside the
fingerprint, so no password-derived value reaches a column.
**Reversible.** Yes.

### DEC-0099 — The Customer Account error body keeps `field`; the public one still does not

**Decision.** A failure under `/api/v1/account` returns exactly three keys — `code`, `message`,
`field` — on every failure, with `field` null when there is none. Public Tracking keeps its
two-key body. The staff `detail` object appears on neither.

**Why not two keys.** The Customer Account first borrowed the public shape, and it was wrong.
`STATE_MACHINES.md` section 2 requires field-level validation errors for **format** and forbids
them for **existence**, and a registration form whose errors named no field is a form nobody
can fill in. The two requirements are compatible because `field` is set only by checks that
perform no lookup — the allowlist, the password policy, the email parser — plus the token
failure, where it is the constant `"token"`.

**Why not the staff shape.** `detail` carries a missing permission name or a retry-after count.
A value in the body that differs between two failures is one more thing that tells them apart,
which is the distinction DEC-0051 exists to deny and T-17 asks for here. The `Retry-After`
header still carries the throttle information; the body does not repeat it.

**Why the shape is fixed rather than variable.** `field` is present on every failure, null
where it does not apply, so the key set never changes between two responses.
**Reversible.** Yes.


### DEC-0100 — Two Customer Account permissions, not one and not five

**Decision.** `customer_account:review` (read the queue, an application, its duplicate
candidates and a preview) and `customer_account:approve` (acknowledge, approve, link, reject).
Every mutating route requires **both**. Admin and Operations hold both; nobody else holds
either.

**Why not one.** The Phase 10 instruction names one permission and also requires that "read
permission and mutation permission remain explicit". Two names is the only way both are true,
and it is what OD-24 asks for in its consequence line: "two new staff permissions".

**Why not five.** `DATA_MODEL.md` section 8 proposes five, covering suspension, separate
proposal review and privacy requests. None of those is in this phase's scope list, and a
permission granted before the route that uses it exists is a permission nobody can audit the
use of. The other three are deferred with the routes.

**Why not `duplicate:review`.** Marketing and the read-only manager already hold it. Deciding
whether two records are one person, and deciding whether a person holding a password may read
a customer's shipment history from now on, are related powers and different ones.
**Reversible.** Yes; widening is a settings change, narrowing after training is an incident.

### DEC-0101 — The three canonical gaps close as two nullable columns and one enum member

**Decision.** `customers.legal_name` and `customers.display_name`, both `String(200)`,
nullable, no default, no backfill; and `AddressRole.BILLING`, a fourth enum member requiring
no DDL because the column is a `String(20)` with no check constraint.

**Why now.** DEC-0096 deferred all three from Phase 9 with a reason that expires here: nothing
in Phase 9 could *apply* a proposal, so a column added then would have been a column with no
writer. Phase 10 applies one.

**Why not overload `full_name`.** It would have avoided a migration and created the column that
means two things `FIELD_MATRIX.md` section 6 asked nobody to create. `full_name` is read by
every existing query, displayed as a person's name, and fed into `name_match_key`; filing a
company into it would make the company start matching people.

**Why a role rather than an `is_billing` boolean.** The booking pickers select on role. A
billing row carrying a flag would have been offered as a place to collect a parcel from. The
pickers were changed from exclusion filters to inclusion filters in the same change, because
an exclusion filter would have offered a fourth role in both of them.
**Cost.** Two columns that are null on every row that existed before this phase.
**Reversible.** Yes, and the downgrade is tested (DEC-0102).

### DEC-0102 — The Phase 10 downgrade uses native `DROP COLUMN` and refuses old SQLite

**Decision.** `6af30fcdd3a8`'s downgrade calls `op.drop_column` directly rather than through
`batch_alter_table`, and raises a clear error on a SQLite older than 3.35.0 instead of falling
back.

**Why.** The autogenerated batch downgrade **did not work**. Batch mode implements
`DROP COLUMN` by rebuilding the table — copy, move rows, drop the original, rename — and
dropping `customers` violates the foreign keys eleven other tables hold into it, with
`PRAGMA foreign_keys` on for every connection (`app/core/db.py`). It failed on the first run
against a populated database, which is precisely what "a downgrade that is tested rather than
asserted" is for.

**Why not turn the pragma off around the rebuild.** That is the usual workaround and is
unavailable here: `PRAGMA foreign_keys` is a no-op inside a transaction, and Alembic runs a
migration inside one.

**Why refuse rather than fall back.** The fallback is the rebuild that is known not to work.
An error naming the required version is more useful than a foreign-key violation.
**Cost.** The downgrade requires SQLite 3.35.0 or newer. The verified environment runs 3.49.1
(`docs/DEPLOYMENT.md` section 9).
**Reversible.** Yes.

### DEC-0103 — The approval preview is a server fingerprint, and the acknowledgement stores figures

**Decision.** `GET …/preview` returns a keyed digest over every material fact. The
acknowledgement is a **row** carrying the five OD-29 figures, the definition version and that
fingerprint. At approval time every fact is recomputed, compared, and a mismatch is
`409 preview_stale`.

**Why a row rather than a flag.** The approval that reads the acknowledgement is a later
request against a world that may have moved. A boolean records that somebody clicked; the
figures record what they agreed to, which is what OD-29 is asking for.

**Why recompute rather than compare the stored fingerprint with itself.** Comparing a stored
value with itself proves only that the row exists. The comparison is against a freshly
computed digest, and the acknowledgement is then found *by* that digest.

**What the fingerprint covers**, and therefore what counts as drift: the identity and its
status, the proposal and a digest of its field rows, the intended action, the target customer
with its `updated_at`, merge state, archive state and mapped values, the duplicate
classification and candidate set, all five disclosure figures with their definition version,
the mapping version, and the active-link state of both the identity and the target.
**Cost.** A reviewer who takes a long time re-reads and re-agrees. That is the intent.
**Reversible.** Yes.

### DEC-0104 — Link-existing writes no canonical customer value at all

**Decision.** Approving by linking sets the identity active and writes the link row, and
writes **nothing** to `customers`, `customer_addresses` or `consent_events`. Differences
between the submission and the record are recorded as field **keys** in the audit payload and
left `applied = false` on the proposal.

**Why.** OD-28 read literally. A person filling in a registration form is not thereby editing
a customer record somebody else maintains; an approval that applied their version would make
registration a write path into the CRM under another name, which is exactly what DEC-0092
exists to prevent.

**Consequence accepted.** A linked account's canonical record may disagree with what its owner
submitted, and nothing reconciles it in release 1. The disagreement is recorded rather than
resolved, and Phase 12's change-proposal handling is where it gets resolved by a person.
**Reversible.** Yes.

### DEC-0105 — The applicant's login address is the proposal's email

**Decision.** Where a registration proposal carries no `email` field, the review and approval
paths treat `customer_identities.email_entered` as that field.

**Why.** A registration supplies its address once, at the top level, and Phase 9 stores it on
the identity rather than copying it into the proposal. `FIELD_MATRIX.md` section 2 nonetheless
lists email as a registration field whose canonical target is `customers.email_entered`, and it
is the only contact detail in the whole submission whose control has actually been **proved**.

**What it fixes.** Without it, an applicant registering with the address of an existing
customer produced **no duplicate candidate at all** — the strongest signal the CRM has,
invisible to the one decision it exists to inform. This was found by a test rather than by
reading, which is the argument for having written the test.

**Why `setdefault` rather than an override.** A proposal that *does* carry an `email` key keeps
it, so a future profile-update proposal proposing a different address is not quietly replaced
by the login one.
**Reversible.** Yes.

### DEC-0106 — Reinstatement checks the live link, not the approval history

**Decision.** `customer_identity_service.reinstate` returns a suspended account to `active`
only when `approved_at` is set **and** an active `customer_identity_links` row exists.
Otherwise it returns it to `pending_approval`.

**Why.** As written in Phase 9 it tested `approved_at is not None` alone, which was correct
while no link existed anywhere and became wrong the moment Phase 10 started writing them: an
account approved, then suspended, then unlinked would have come back `active` with no active
link — an identity in the one state that reaches shipment data, with no customer to reach it
through.

**Why fix it in a phase with no route to it.** Transition 7 of `STATE_MACHINES.md` is not in
Phase 10's scope and no route calls this function. A guard that only exists once a route exists
is a guard added under time pressure, on the day somebody needs the route.

**Consequence.** `active` has two writers, not one, and the source scan in
`tests/test_account_activation_invariant.py` asserts exactly those two rather than forbidding
the second. A third is a defect.
**Reversible.** Yes.

### DEC-0107 — A customer merge is refused while either side holds an effective link

**Decision.** `customer_service.merge_customers` refuses the whole merge, before any write,
when the source customer or the surviving customer has a `customer_identity_links` row with
`status = 'active'`. The refusal carries the stable code `customer_account_link_present` and
names which side blocked. The definition of "effective" lives in one module,
`customer_account_link_policy`, which both the merge and the approval read.

**Why in the service and not in the route.** A route guard is a guard for one caller. The
merge is reachable from a script, an import, and whatever bulk tool gets written next; the
service is the only place that covers all of them. The route's sole addition is committing
the refusal audit row, which is a presentation concern, not the rule.

**Why refuse rather than move, revoke or suspend.** OD-40 rules out the other four options
and gives the reasons. The one worth restating is the one the earlier code got wrong in the
opposite direction from the way it was documented: merging *into* a linked customer grows
that account's disclosable shipment history by everything the source owned, with nothing
previewed and nothing acknowledged. That is a disclosure, and OD-29 says a person agrees to
a disclosure before it happens.

**Why the identity's status is not part of the test.** A suspended identity keeps its link
and transition 7 of `STATE_MACHINES.md` hands it straight back; a deactivated one keeps an
active row today because `deactivate` does not revoke links. Reading the link table rather
than the identity table means every impossible combination fails closed.

**Consequence accepted.** Staff cannot merge a duplicate involving an account holder at all
until a reconciliation workflow exists. That is a real operational cost and it is the
reversible direction: nothing has happened, so any of the other five options is still open
to a later phase.
**Reversible.** Yes.

### DEC-0108 — SQLite transactions begin when SQLAlchemy says they do

**Decision.** `build_engine` installs the documented pysqlite recipe: the driver's implicit
transaction handling is switched off (`isolation_level = None`) and `BEGIN` is emitted on
SQLAlchemy's `begin` event.

**What it fixes, and neither of these was visible from the code that suffered it.** Left
alone, pysqlite emits no `BEGIN` until it sees an `INSERT`, `UPDATE` or `DELETE`.

1. **`Session.begin_nested()` was committing.** A `SAVEPOINT` issued with no `BEGIN` in
   front of it *is* the outermost transaction in SQLite, and releasing the outermost
   savepoint commits. So in `approve_link_existing` the idempotency claim landed in its own
   transaction, then the proposal decision and the link row landed in a second one, and the
   identity's activation ran outside both. A refusal after any of them left exactly the
   partial state — a link with no activation — that the module is written to make
   impossible, and that `test_account_activation_invariant.py` sweeps for.
2. **Check-then-write across two connections was unprotected.** A read taken before the
   first write belonged to no transaction, so another connection could commit between a
   check and the write that depended on it, with no error on either side. That is write
   skew, and it is precisely the shape of OD-40's race: a merge checking for a link while an
   approval creates one.

**How it was found.** By writing the concurrency tests OD-40 asks for and having one fail
on "a refused approval left an idempotency claim". The behaviour is demonstrated rather
than asserted, in `tests/test_merge_link_concurrency.py::test_a_read_before_the_first_write_is_protected`,
so if the engine's isolation ever changes the test says so.

**Consequence accepted.** A transaction now holds its read snapshot from its first
statement, so a writer racing a long reader meets `database is locked` sooner than before.
That is a refusal rather than a corruption; `PRAGMA busy_timeout` absorbs the short cases
and `commit_with_retry` the rest. Tests that read through a second session after an HTTP
write now have to end their own transaction — `expire_all()` refreshes objects but not the
snapshot — which is a change to a handful of assertions and not to any behaviour.

**Why not a schema change.** OD-40's brief anticipated one. None was needed: the invariant
is a transaction-isolation property, and the smallest fix is the engine's own documented
configuration. No table, column, index or migration changed.
**Reversible.** Yes — deleting `_register_explicit_transactions` and its call restores the
previous behaviour exactly.

### DEC-0109 — The merge's first write is its claim

**Decision.** `merge_customers` tombstones the source with a conditional
`UPDATE ... WHERE id = ? AND merged_into_customer_id IS NULL` whose affected-row count is
checked, **before** it moves anything, and re-runs every refusal check immediately
afterwards. The tombstone is no longer written at the end.

**Why the order.** The conditional update is the transaction's first write, so it is the
statement that takes SQLite's writer lock. Every check made after it reads committed data
with no other writer able to intervene; every check made before it is advisory. Both are
kept — the early ones so a refusal costs nothing and reads well, the late ones so a refusal
is correct.

**Why not a `SELECT ... FOR UPDATE`.** SQLite has none worth using. The guard had to be a
write or it would be decoration, which is the same reasoning the approval service's four
guards were built on.

**Consequence accepted.** A merge that is going to be refused for a late reason now writes
and rolls back, rather than never writing. Inside one transaction that is invisible, and it
buys the only ordering under which the late checks mean anything.
**Reversible.** Yes.

### DEC-0110 — An assertion may only be weakened against a register

**Decision.** `docs/customer_account/SUPERSEDED_ASSERTIONS.md` records every assertion an
earlier phase made that a later one inverted, with the original text, why it became false,
the replacement, the guarantee that survives, and the decision that authorised it.
`backend/tests/test_superseded_assertions.py` fails the build if a registered test has
vanished or been renamed away, if an entry is incomplete, if it cites a decision nobody can
look up, or if a test calls itself superseded without an entry.

**Why.** Four Phase 9 assertions were amended in Phase 10 and a fifth in the OD-40 work.
Every one was legitimate. But "the later phase implemented something the earlier phase
deliberately had not" and "somebody weakened a guard to make a new test pass" produce
identical diffs, and the only thing that distinguishes them is a written reason — which
nothing was requiring.

**What it deliberately does not check.** Whether the replacement is as strong as the
original. No parser can see that. The register's job is to make sure review has something
to review, in the same way `verify_decision_log.py` cannot tell whether a citation points
at the *right* decision and says so.
**Reversible.** Yes.

### DEC-0111 — A refusal's audit row is written after its rollback, not inside it

**Decision.** A service that wants a refusal recorded attaches the audit call to the
exception as an `audit_refusal` hook and writes nothing. `app.core.db.persist_refusal_audit`
performs it at the route boundary, in this order: roll the session back, write the one row,
commit.

**What it fixes.** Every refusal audit on the Customer Account surface was being written
into the transaction that was about to be rolled back, so none of them survived. The rows
existed in the code and never in the database. `preview_stale_refused` and
`approval_conflict` were both in this position, and so was the merge refusal OD-40 asks to
be able to see.

**Why not commit instead.** A refusal raised halfway through an operation sits in a
transaction holding real work — an idempotency claim, a proposal decision, a created
customer. Committing to save the audit row would commit that work too, which is the exact
partial state the refusal exists to prevent.

**Why the hook rather than auditing in the route.** The route does not know which refusal
happened or what the payload should be; the service does. Attaching it keeps the payload
where the facts are and the transaction control where it belongs.

**Why this is what OD-40 asked for.** Section 1 of the instruction requires that a refused
merge mutate nothing, and lists `audit` among the tables. Section 5 requires the refusal to
be audited. Written inline, those two are in direct conflict. Written after the rollback,
both are literally true: the refused transaction writes nothing at all, and the record
still lands.

**Consequence accepted.** A refusal that carries a hook now performs two round trips
instead of one, and a refusal whose hook itself fails will surface that failure rather than
the refusal. Refusals carrying no hook are untouched, so this stays limited to the ones
somebody decided were worth a record.
**Reversible.** Yes.

### DEC-0112 — An automated browser run gets its own database, and proves it reached it

**Decision.** Every complete Playwright run creates or explicitly resets a dedicated SQLite
database whose resolved filename ends in `.e2e.db` and which lives inside `data/e2e/`. The
backend serving it runs with `ENVIRONMENT=e2e` and refuses to start against anything else.
The run mints a random identifier, gives it to that backend's environment and to a marker
row inside that database, and the suite's global setup requires the server it actually
reached to confirm both before any test runs.

**What it fixes.** `playwright.config.js` declared no `webServer`, so the suite never
started the stack it tested: it opened `http://localhost:5173`, whatever answered served the
tests, and on four runs what answered was a development backend serving
`data/solaris_crm.db`. 314 rows were written into it — 40 customers, 32 import batches, 36
import rows, 195 audit events, 11 sessions. `docs/incidents/` holds the record.

**Why a handshake and not just a path check.** A path check inside the launcher proves what
the launcher intended, not what the browser reached. A development backend on the expected
port answers a browser exactly as well as the right one does, and so does a stale E2E
backend from a previous run, and so does the right process pointed at the wrong file. The
identifier is the only thing all three fail to produce.

**Why the identifier is not a credential.** It authorises nothing. The endpoint that
compares it returns a status and no data, sets no cookie, and is mounted only when
`ENVIRONMENT=e2e` — not hidden behind a flag, *not routed* anywhere else, and absent from
every OpenAPI document. Presenting the right one opens no staff route.

**Why the suffix as well as the directory.** Either alone is weaker than it looks. A bare
`.db` in the right directory is a file somebody can mistake for a real one in a listing; an
`.e2e.db` anywhere convenient is a licence to point a run at `data/`. Both are required,
both are checked on the canonical path, and the development database, the UAT directory,
`backups/` and the source tree are each refused by name on top.

**Why the E2E rate limits are applied by the harness.** `docs/OPERATIONS.md` used to ask a
developer to export two variables. The suite runs entirely from loopback against a
process-local limiter, so forgetting them cost about five public-tracking tests to failures
that read as "element not found" and were really "Too many lookups". No application default
moved, and the tests that exercise the limiter still set their own explicit values.

**Consequence accepted.** Running `playwright test` directly no longer works: it stops in
global setup with an explanation and the correct command. That is the point — the previous
behaviour of that command was to write into whatever was listening.
**Reversible.** Yes. Deleting `app.core.e2e_guard`, `app.api.e2e`, `scripts/e2e_env.py` and
`frontend/scripts/run_e2e.mjs`, and restoring `"e2e": "playwright test"`, returns the
previous behaviour exactly.

### DEC-0113 — Phase 11 keeps one predicate, one inclusion rule and two shared policy helpers

**Decision.** The authenticated Customer Account shipment surface reuses four things
rather than restating them, and each reuse is a named, public function rather than a copy:

* `customer_account_link_policy.EFFECTIVE_LINK_STATUSES` — the `status == 'active'`
  predicate. Phase 11 adds `effective_links_for_identity` and `resolve_readable_customer`
  to that module, so the literal is still written exactly once in the repository, on the
  customer side and the identity side alike;
* `customer_account_disclosure_service.qualifying_conditions` — the OD-29 inclusion rule,
  promoted from `_qualifying`. The staff disclosure preview counts rows with it and the
  authenticated list and detail serve rows under it;
* `public_tracking_service.public_events` — the publication gate that decides which events
  may be shown to a customer at all, promoted from `_public_events`;
* `public_tracking_service.public_carrier_link` — the safety policy that decides whether a
  stored carrier link may be shown, promoted from `_carrier_link`.

**Why.** Each of these is a *policy*, and two copies of a policy are two chances for one
copy to drift. The one that matters most is the inclusion rule: the reviewer acknowledges a
count before approving a link (OD-29), and the customer then reads rows. If those two ever
disagree, the disagreement is in the direction where a reviewer authorized less than was
disclosed.

**What is deliberately *not* shared.** The response models. `AccountShipmentListItem` and
`AccountShipmentDetail` are declared field by field in their own module, inherit nothing,
re-declare their own enums and nested shapes, and never embed or return a
`PublicTrackingResult`. The timeline and package structures are built in the Customer
Account's own service from the shared queries' rows. Sharing a *predicate* means two
surfaces cannot disagree about a fact; sharing a *model* would mean neither could change
without the other, which is the opposite of what OD-31 asks for.

**Also decided here: the status-group vocabulary.** `SHIPMENT_ALLOWLISTS.md` §3.2 approves
filtering "by status group" and defines no groups, so Phase 11 defines four —
`in_progress`, `delivered`, `cancelled`, `exception` — as a closed set that **partitions**
`OperationalState`. Every state belongs to exactly one group, asserted by test: a state in
none would be unreachable by any filter, and a state in two would make the groups' counts
exceed the list. The two return states sit in `exception` rather than in a group of their
own, because a `returns` filter would be the first half of a return workflow OD-22 has not
authorized.

**Reversible.** Yes, in both directions. A later phase that needs the authenticated view to
diverge from the public one edits `app/schemas/account_shipments.py` and
`customer_account_shipment_service.py` and touches neither public file. A later phase that
needs a fifth status group edits one dictionary and one test.

### DEC-0114 — The two OD-41 list filters are exact-match, service-validated, and applied after ownership

**Decision.** `reference` and `route_group` join `status_group` and the date range on
`GET /api/v1/account/shipments`. Both are exact.

* `reference` is normalized by `app.core.public_reference.parse_public_reference` — the
  **same** parser the detail route uses — and compared with `Shipment.public_id ==`. There
  is no `LIKE`, no `ILIKE`, no `startswith` and no collation trick anywhere in the path.
* `route_group` is checked for membership in `RouteGroup` before any statement is built, so
  the value that reaches SQL is an enum member this repository declared, never a string a
  caller composed.
* A value that fails either check raises `ValidationError` inside
  `customer_account_shipment_service.parse_filters`, which the Customer Account error
  boundary turns into this surface's `{code, message, field}` body. Neither parameter
  carries a FastAPI `Query(...)` constraint, for the reason the path parameter carries none
  (DEC-0059): a framework constraint answers with a second failure shape that echoes the
  submitted value back.
* Both clauses are appended to `qualifying_conditions(customer_id)`, which already carries
  the OD-29 ownership equality, so a filter can only narrow.

**Why an unmatched reference is an empty list and not a 404.** The detail route answers "is
there a shipment here" and a generic 404 is the safe answer. The list answers "which of
your shipments match", and the safe answer to a filter that matches nothing is nothing. An
unknown reference and another customer's reference produce the identical empty page — same
status, same body shape, same headers, same `total: 0` — so the filter distinguishes
neither, and no code path exists that could.

**Why the limiter still cannot be bypassed.** `_limit_or_refuse` runs before `parse_filters`
in `list_shipments`, so a flood of malformed filter values is refused at the same rate as
valid traffic and issues no statement beyond the session resolution.

**Why the length bound lives in the service.** `MAX_FILTER_VALUE_LENGTH` already bounds the
other three; the two new ones join it, checked in the same loop, before anything is parsed.

**Reversible.** Yes. Removing either filter is deleting one branch of `_owned`, one check in
`parse_filters` and one control on the list screen. Widening `reference` to a prefix search
would not be reversible in the same sense — it would be a new owner decision, because
OD-41 declines it by name.

### DEC-0115 — `commit_with_retry` stops retrying once the flush has failed

**Decision.** The loop checks `session.is_active` and, when the transaction has been
deactivated by a failed flush, rolls back and re-raises the original `OperationalError`
instead of calling `commit()` again.

**Why.** `Session.commit()` flushes first. A flush that hits `database is locked` marks
the transaction as needing a rollback, and every later statement on that session —
including the next `commit()` — is refused with `PendingRollbackError`. That is not an
`OperationalError`, so it escaped the `except` clause entirely and propagated: a transient
lock surfaced as an exception naming SQLAlchemy internals rather than as the lock it was.
The retries were therefore not merely useless after a failed flush, they were actively
replacing a legible error with an illegible one.

**Why not roll back and retry.** The rollback discards the work being committed, so the
retry would succeed and write nothing. Silence is worse than the error.

**Found by** the Phase 12 staff approval screen, which issued three audit-writing reads at
once.

**Reversible.** Yes: delete the `deactivated` check.

### DEC-0116 — A refusal audit on the shipment routes rolls back before it writes

**Decision.** `_authorized_customer` and the detail route's not-found branch call
`db.rollback()` before adding the audit row and committing.

**Why.** Both paths have already read — the session, the identity, the link, the shipment
query — so the transaction holds a read snapshot. Adding a row and committing asks SQLite
to **upgrade** that read to a write, and SQLite refuses an upgrade with `database is
locked` *immediately*, without consulting `PRAGMA busy_timeout`, if any other connection
has written since the read began. There is nothing to wait for, because waiting could not
make a stale snapshot valid. The refusal then left as a 500 instead of the 403 or 404 it
was.

Rolling back discards the read snapshot and the courtesy `last_seen_at` touch, and nothing
else: neither path has written anything worth keeping. The audit row becomes the
transaction's first statement, so there is no upgrade and `busy_timeout` applies as the
comment in `_register_explicit_transactions` always claimed it did.

This is `persist_refusal_audit`'s order (DEC-0111) applied to two paths that predate it.

**What was considered and rejected.** Emitting `BEGIN IMMEDIATE` for every transaction
would fix the whole class at once, and it was tried. It breaks the Phase 10 concurrency
tests at their *setup*: those tests hold two sessions open simultaneously to prove write
skew is prevented, and under `IMMEDIATE` the second session cannot begin at all. Making
the guarantee stronger by making its evidence impossible to collect is not an improvement,
and reworking the session model is not a frontend phase's business. The residual
limitation — genuinely concurrent writers on SQLite can still meet a lock — is what
`docs/OPERATIONS.md` §5 and DEC-0006 already record as the point at which this deployment
outgrows SQLite.

**Found by** the Phase 12 browser suite, with two browser contexts in play.

**Reversible.** Yes: delete the two `rollback()` calls, and the 500s come back.

### DEC-0117 — Test fixtures build shipment references with the real generator

**Decision.** `conftest.add_shipment` and `approval_fixtures` build a `public_id` with
`identifier_service.random_suffix(12)`, the function the application uses, instead of
`uuid4().hex[:12].upper()`. A test asserts that every reference the fixtures produce
parses as a Solaris shipment reference.

**Why.** The unambiguous alphabet is `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` — no `0`, no `1`,
no `I`, no `O`. A hexadecimal string contains `0` and `1` freely, so a uuid-derived suffix
matches `SHIPMENT_PATTERN` only when twelve consecutive hex characters happen to avoid
both: about **one time in five**.

A shipment with such a reference is perfectly usable through any path that addresses it by
row — it is created, listed, reported on and exported — and is unreachable through every
path that addresses it by *reference*, because the parser refuses the value before the
query is built. Public tracking and the authenticated detail route both refuse it, and
both refuse it with the generic not-found they refuse everything with, so the failure
arrives as "that shipment does not exist" rather than as "that fixture is wrong".

`test_account_review_privacy.py::test_an_active_account_reaches_its_shipments_and_nothing_planted_comes_with_them`
is the test this surfaced on: it lists a shipment successfully and then fetches the same
reference and gets a 404. It had been passing at roughly one run in five since Phase 11,
and three consecutive full suites had happened to land on the winning side.

**This is a defect in the fixtures, not in the product.** The parser is correct to refuse a
string that the generator could not have produced; a reference space with `0`/`O` and
`1`/`I` in it is a reference space customers read out wrong over the telephone, which is
why `UNAMBIGUOUS_ALPHABET` exists. Loosening the parser to accommodate a fixture would
trade a real property for a convenient one.

**Why a guard test rather than only a fix.** Two fixture modules had the same bug and two
others (`report_fixtures`, `shipment_history_fixtures`) already did it correctly, which is
exactly the situation in which the wrong version gets copied again. The guard asserts the
property — every fixture-built reference parses — rather than the spelling.

**Found by** the Phase 12 validation re-run, which failed once in 2,617 tests and then
reproduced on demand.

**Reversible.** In principle; there is no reason to.

### DEC-0118 — Public tracking derives its state from published events only, and a cancelled booking is not publicly retrievable

**Decision.** `public_tracking_service` no longer reads `shipment.operational_state`,
`shipment.delivered_at` or `package.operational_state`. The public status, each package's
status, the delivered count and the delivered time are derived from the rows
`public_events` returns — non-voided events a staff member explicitly published with
approved wording — by the same rules `event_service` applies internally (latest event by
occurred time per package; every package delivered is Delivered, some is Partially
delivered, an attention state wins, otherwise the least advanced package). A package with
no published event is "booked". A booking in `cancelled` state answers the same 404, body
and headers as an unknown reference.

**Why.** The 2026-10-14 bot-executed UAT run (UAT-XX-02) found two disclosures. A package
showed "Delayed" from an exception that was never published: the stored state is derived
from *every* event, so an internal note moved the public page while the timeline stayed
empty. And a cancelled booking answered 200 with a safe summary, which told anyone probing
identifiers that this one had been issued — the one fact DEC-0051 exists to deny. The
owner approved both corrections.

**What changes for staff.** Nothing the customer has not been told moves the public page.
A delivery recorded without "Publish this update" leaves the public status where the last
published milestone put it, and the estimate in place. The staff portal still shows the
stored state. Provider events (Phase 4A seam) carry no public wording and therefore move
the internal status only; `test_public_contract_unchanged.py` now asserts that split.

**What was considered and rejected.** Publishing every state-changing event automatically
would restore the old behaviour by another route and is exactly what CRM.md section 10
forbids. Showing the stored state but hiding attention states only would have left the
next unpublished state to leak. The authenticated Customer Account keeps showing its owner
a cancelled booking: the owner is not a stranger, and the surface is authenticated.

**Found by** the bot-executed UAT run, 2026-10-14.

**Reversible.** Yes: `_visible` and `build_result` carry the change; the enum value
`TrackingState.CANCELLED` was kept so the public contract is unchanged in shape.

### DEC-0119 — Account link tokens travel in the URL fragment and are captured before React mounts

**Decision.** `verification_url` and `password_reset_url` put the token after `#token=`
rather than `?token=`. `frontend/src/main.jsx` calls `captureLinkToken()` as its first
statement: the token is copied into a module-level variable and the address bar rewritten
with `history.replaceState` before `createRoot`, before the router reads the location. The
two landing pages take the token from that stash, and still accept `?token=` for links
already sent. The token stays single-use and short-lived; nothing else about it changed.

**Why.** CA-SEC-07 found the reset URL, token included, in the browser's history. A
fragment is never sent to a server, so the token reaches no access log and no `Referer`,
and stripping it before the first render keeps it out of the address bar, the session
history and the Back button. **What this does not do:** Chromium records the committed URL,
fragment included, in its global history database before any script runs, and no
client-side technique removes that entry. The bound on that exposure is the token itself —
single-use, expiring, purpose-bound and invalidated by the next one issued — and this
decision records the limit so nobody reads the fix as more than it is.

**What was considered and rejected.** A server-side redirect that exchanges the token for
a short-lived cookie would still commit the tokenised URL to history before redirecting,
and would put the token on the wire and in the proxy log, which the fragment avoids.
Redeeming the reset token on arrival (as the verification link does) was rejected because
a reset needs a password first and consuming the token before one is typed would strand a
person whose form submission fails.

**Found by** the bot-executed UAT run, 2026-10-14.

**Reversible.** Yes, and both shapes are accepted during any transition.

### DEC-0120 — Customer identity suspension and reinstatement have staff routes; deactivation does not

**Decision.** `GET /customer-account/identities/{ref}`, `POST .../suspend` and
`POST .../reinstate` call the Phase 9 service functions. Reads need
`customer_account:review`; the two mutations need review **and** approve, like every other
decision on the surface. Reason codes are bounded (`SUSPEND_REASON_CODES`,
`REINSTATE_REASON_CODES`) and the transition guards (`can_suspend`, `can_reinstate`) live
in `customer_identity_service`, so the route names no identity state. The Staff Portal
shows an "Account status" card on the application screen for any reference, decided or
not. **Deactivation is not wired.**

**Why.** Finding A8 of `docs/DECISION_REGISTER.md`: the service existed with no route, so
after launch the only way to suspend an account would have been the database. Sprint 13
Lane A item A-1 proposed the routes; the 2026-10-14 fix pack wired suspend and reinstate.
Deactivation is irreversible, and the owner has not decided who may perform it or whether
it is the privacy-request path (OD-35); wiring it would be deciding that by default.

**Addressed as `/identities/…`** rather than `/registrations/…` because a suspension acts
on an account that may have been approved months ago, and the registration routes refuse
an identity with no pending proposal.

**Reversible.** Yes: three routes and one card.

### DEC-0121 — A password-reset link lives one hour

**Decision.** `ACCOUNT_PASSWORD_RESET_TOKEN_HOURS` defaults to **1**, down from 2. The two
link templates state the lifetime as a phrase (`expires_after`: "1 hour", "24 hours")
rather than a bare number, so the reset message does not read "expires in 1 hours". The
verification link is unchanged at 24 hours.

**Why.** Approved by the owner on 2026-10-14 after the fix pack. DEC-0119 keeps the token
out of the address bar, the session history and every server log, but Chromium still
records the committed URL in its history database before any script runs. The bound on
that copy is the token's lifetime, and a reset link is requested by the person about to
use it, so an hour costs a legitimate user nothing and halves the window.

**What it does not change.** Single-use, purpose-bound, invalidated by the next one
issued, and every session revoked on completion — all as before.

**Reversible.** Yes: one setting. The message wording follows it.

### DEC-0122 — The CA-SEC-07 browser-history residual is accepted, bounded by a one-hour reset link

**Decision.** The owner accepts the residual exposure DEC-0119 recorded: Chromium writes a
committed URL, fragment included, into its global history database before any script runs,
so a password-reset or verification link's token is present in that database even though it
is gone from the address bar, the session history, the Back button, every server log and
every `Referer`. The bound on that copy is the token's own lifetime and single use. With the
reset link at one hour (DEC-0121) the owner considers CA-SEC-07 closed.

**What would reopen it.** A browser that synchronises history across devices the customer
does not control, or a requirement that no token ever be written to any local store. Either
would need a different delivery — a short code typed into the page rather than a link — which
is a product change, not a fix.

**Recorded by** the owner's fix-pack-2 approval, 2026-10-14. Register: `DECISION_REGISTER.md`
§8.2.

### DEC-0123 — The Customer Account profile: what it does, what it leaves out, and how a grant meets a suppression

**Decision.** The profile DEC-0095 deferred is built as FIELD_MATRIX §3 and §4 describe, with
three choices recorded here.

* **Proposal groups.** A reviewer decides legal name, preferred name, phone (with its region)
  and pickup address as four groups, each approved or declined whole; every field row in a
  group is marked `applied` together. Half an address is not an address. A group whose
  canonical value moved since submission is refused with a 409, never merged. A decided
  proposal is not decided again. A newer submission supersedes the pending one and carries
  forward the groups it did not resubmit.
* **Email is not proposable.** It is the account's sign-in address and STATE_MACHINES §6
  requires verification of the new address before a change lands; that flow is not built,
  so the key is refused by name rather than half-supported.
* **A customer's marketing grant against a suppressed address is recorded.** The staff
  consent path refuses such a grant so a staff member cannot clear a suppression by typing a
  consent. A consent row never clears a suppression anyway — eligibility reads the suppression
  first — and for a customer a refusal would be the one response that differs for a
  suppressed address, which FIELD_MATRIX §4 rule 2 forbids. So the choice is appended as the
  customer's own (`source = customer_account`), the suppression keeps deciding, the response
  is identical, and the audit row tells staff the address was suppressed. The registration
  approval path still skips the row silently (Phase 10); the two differ and both satisfy the
  rule.

**Not built.** Operational notification preferences after registration (the other §3.1
row) and a customer change-password flow.

**Reversible.** Yes; five customer routes and three staff routes, no migration.

### DEC-0124 — Profile change requests are reviewed by Operations; Louis Tong owns the queue by default

**Decision.** The **Customer accounts → Profile change requests** queue DEC-0123 added is an
Operations queue. Louis Tong is its default owner: he works it, or hands a request to another
Operations reviewer. Admin keeps the permission as a fallback. No code changes: the queue
already needs `customer_account:review`, which Operations and Admin hold and Marketing and the
read-only manager do not.

**Why.** `PROJECT_STATUS.md` §33.4 item 1 asked who owns the queue before UAT round 3.

**Recorded by** the owner (Ben), 2026-10-15. Register: `DECISION_REGISTER.md` §8.3.

**Reversible.** Yes: a staffing choice, not a permission.

### DEC-0125 — Customer self-service email change is deferred

**Decision.** A customer cannot change their sign-in email address from the Customer Account.
The profile keeps refusing the `email` key by name (DEC-0123). A customer who needs a new
address asks staff, who change it on the canonical record.

**Why.** STATE_MACHINES §6 needs a verified email-change flow: confirm the new address before
it lands, notify the old one. That flow is not built, and the owner chose not to build it
before launch.

**Recorded by** the owner (Ben), 2026-10-15. Register: `DECISION_REGISTER.md` §8.3.

**Reversible.** Yes: building the flow is additive.

### DEC-0126 — Customer account deactivation is Admin-only

**Decision.** Only Admin may deactivate a Customer Account identity. Deactivation is permanent
for the account (it revokes every session and invalidates every outstanding token) and is not
a deletion. Suspend and reinstate stay with review-and-approve holders (DEC-0120). This answers
the question DEC-0120 left open and closes OD-35's open point on who may deactivate.

**Not built here.** `customer_identity_service.deactivate()` still has no route. When it is
routed it must check an Admin-only permission, require a bounded reason code and write an
audit row, like suspend and reinstate. Privacy-request execution (export, correction, legally
required deletion) is still designed only.

**Recorded by** the owner (Ben), 2026-10-15. Register: `DECISION_REGISTER.md` §8.3.

**Reversible.** Yes: who holds a permission.

### DEC-0127 — A customer who opts in to marketing is told, plainly, when email cannot reach the address

**Decision.** `GET /account/profile` and `POST /account/consent/marketing` carry one boolean,
`marketing.delivery_blocked`. It is true only when the customer is opted in and
`consent_service.marketing_eligible` says the address cannot receive marketing, whether
because of a suppression or a staff do-not-contact flag. The profile then shows one plain
sentence: the customer is opted in, Solaris Express cannot currently send marketing email to
the address, and they can contact Solaris Express if they think that is wrong. The reason,
source and date of the block are never returned.

**Supersedes in part** DEC-0123's third bullet: the profile's response is no longer
identical for a suppressed address once the customer has opted in. FIELD_MATRIX §4 rule 2
and §7 obligation 4 are amended to match. The grant is still recorded and the
suppression still decides.

**Why.** UAT round 3: a suppressed customer who opted in got no feedback and had no way to
know why marketing email never arrived. The owner approved the plain note. The address is the
customer's own and the customer is signed in, so the boolean tells them nothing about anyone
else. Registration's response is unchanged and still identical for every address.

**Recorded by** the owner's UAT round 3 approval (Ben), 2026-10-15.

**Reversible.** Yes: one response field and one sentence.

### DEC-0128 — A linked customer's preferred language has one source: the canonical customer

**Decision.** `/account/me` and `/account/profile` both read the preferred language through
`customer_account_profile_service.account_language()`. It returns the linked customer's
`preferred_language`, which is what the profile writes. It falls back to the identity's
registration language only when no customer can be read or the customer's language is
`unknown`.

**Why.** UAT round 3: `/me` read the identity's language and `/profile` read the customer's,
so after a change the two disagreed.

**Not changed.** Account emails still pick their language from the identity. Release 1's
Customer Account is English only (OD-39), so nothing visible differs yet. When OD-39 adds a
language, the mail path should read the same helper.

**Reversible.** Yes: one helper.

### DEC-0129 — An Admin approval or rejection of a Customer Account is recorded as an Admin override

**Decision.** OD-24 makes account approval Operations' work and lets Admin override. The
`customer_account.approve` and `customer_account.reject` audit rows now carry
`admin_override`, a boolean: true when the actor's role was Admin at the moment of the
decision, false otherwise. An override's summary ends "(Admin override)". The audit API derives
`admin_override` for the Audit access screen, which shows it as a badge beside the reason code.
Only a literal `true` in the stored detail counts.

**Why.** UAT round 4, CA-APR-05 failed: the row named the actor and the reason code but did
not say it was an override, so a reviewer had to infer it from the actor's address.

**Not changed.** Who may approve. Admin and Operations hold the same two permissions; the flag
records which role used them. Suspend, reinstate and deactivate are not flagged: suspension is
not an approval, and deactivation is Admin's alone (DEC-0126).

**Recorded by** the owner's UAT round 4 approval (Ben), 2026-10-15.

**Reversible.** Yes: one detail key and one badge.

### DEC-0130 — Marketing and Admin may suppress a customer's address from the Consent tab

**Decision.** A new permission, `suppression:add`, held by Marketing and Admin, reaches
`POST /api/v1/customers/{id}/consent/suppressions` and a "Suppress address" action on the
Consent tab. It requires a channel (email by default), an evidence reference and a reason, and
in one transaction writes an append-only `consent_events` row with status `suppressed`
(source `staff_suppression`, carrying the evidence and the reason), the global
`contact_suppressions` row, and a `suppression.add` audit row naming the actor, the customer
and the channel. The audit detail carries no address, evidence text or reason prose; those are
staff-typed and are read from the consent history. A second suppression of the same address is
refused (409). Releasing stays Admin's alone (`suppression:release`).

**Why.** UAT round 4: no staff screen could suppress an address, so the DEC-0127 customer note
could not be tested (CA-PRF-04, UAT-OP-13's Phase 12 step).

**Not changed.** The older path stays: a holder of `consent:write` (Operations, Marketing,
Admin) can still record a consent event with status `suppressed`, which also writes the
suppression. Whether Operations should keep that path, or hold `suppression:add`, is a question
for the owner (`PROJECT_STATUS.md` §35.4).

**Recorded by** the owner's UAT round 4 approval (Ben), 2026-10-15.

**Reversible.** Yes: one permission and one route.

### DEC-0131 — Customer account deactivation is routed, Admin-only, with a reason code and audit

**Decision.** `POST /api/v1/customer-account/identities/{reference}/deactivate` requires
`customer_account:review` and a new permission, `customer_account:deactivate`, which no role
set lists, so Admin alone holds it (DEC-0126). It takes one bounded reason code
(`customer_request`, `privacy_request`, `security_concern`, `duplicate_account`,
`abuse_or_test`), refuses any other (422) and an account already deactivated (409), and calls
`customer_identity_service.deactivate()`: every session is revoked, every outstanding token is
invalidated, and a `customer_account.deactivate` audit row records the actor and the code.
`IdentityStatusOut` gains `deactivated_at` and `can_deactivate`. The review screen's Account
status card offers "Deactivate account" to holders of the permission only, behind a reason and
a confirmation dialog. Sign-in afterwards fails with the same answer as a wrong password.

**Why.** DEC-0126 closed OD-35's open point and left routing as engineering work; the owner
approved it in UAT round 4.

**Not changed.** The link row stays active and the record is kept: deactivation is not a
deletion. Whether a deactivated account's link should end, which would also stop it blocking a
customer merge (OD-40), is a question for the owner (`PROJECT_STATUS.md` §35.4).
Privacy-request execution is still designed only.

**Recorded by** the owner's UAT round 4 approval (Ben), 2026-10-15.

**Reversible.** Yes for the route; a deactivation itself is not undone from the Staff Portal.

### DEC-0132 — An import whose every held row is skipped can be finished; the reset 429 uses the recovery sentence

**Decision.** Two fix-pack rules.

1. The import button is enabled once every possible duplicate has a decision, even when no
   customer would be created, provided the file has something to record (a new row, a held row
   or an earlier-import match). With nothing to create it reads "Finish import (no new
   customers)" and the confirmation says no record will be created. The server already accepted
   such a commit; the batch records the skips (`duplicate_skipped`).
2. The per-connection limit on `POST /account/password/forgot` still answers 429 with
   `Retry-After`, but its message is the ordinary recovery sentence, and the page goes to the
   same "Check your email" confirmation as an accepted request: the registration rule of UAT
   round 3, applied to recovery.

**Why.** UAT round 4: an all-skip file could not be finished, and the reset form was the one
public form still saying "Too many attempts".

**Not changed.** The resend-verification form's per-connection 429 still shows its throttle
notice (`PROJECT_STATUS.md` §35.4).

**Recorded by** the owner's UAT round 4 approval (Ben), 2026-10-15.

**Reversible.** Yes.

### DEC-0133 — Operations cannot suppress an address; suppression is Marketing's and Admin's

**Decision.** Only holders of `suppression:add` (Marketing and Admin) may suppress. The
older path through the consent history is closed to everyone else:
`consent_service.record_consent_event` refuses a `suppressed` status from an actor without
`suppression:add` (403, `required_permission: suppression:add`, field `status`) and writes
nothing. The Consent tab's "Record consent change" form offers "Suppressed" only to holders
of `suppression:add`. Operations keeps `consent:write` for recording consent and
withdrawals.

**Why.** Owner decision (Ben, 2026-10-15), answering `PROJECT_STATUS.md` §35.4 question 1.
DEC-0130 gave Marketing and Admin a dedicated action with evidence and a reason and left the
older consent-status path open to Operations; that was a second door to the same effect.

**Not changed.** Releasing stays Admin's alone (`suppression:release`). A system write with
no actor (none exists today) is not affected.

**Recorded by** the owner's UAT round 5 decision (Ben), 2026-10-15.

**Reversible.** Yes: one permission check and one form option.

### DEC-0134 — A deactivated account keeps its customer link, and the link no longer blocks a merge

**Decision.** Deactivation keeps the `customer_identity_links` row `active` as the record of
whose account it was (DEC-0131, unchanged). The merge guard now asks
`customer_account_link_policy.has_merge_blocking_link`: an effective link blocks a merge
unless its identity is `deactivated`. A link whose identity row cannot be found still blocks
(fails closed). After such a merge the link still names the source customer, now a
tombstone; nothing reads it, because a deactivated identity holds no session and
`resolve_readable_customer` refuses any identity that is not `active` before it reads a
link. `has_effective_link` and the two partial unique indexes are unchanged, so a customer
whose only link belongs to a deactivated account still cannot be linked to a second account.

**Why.** Owner decision (Ben, 2026-10-15), answering `PROJECT_STATUS.md` §35.4 question 2.
Deactivation is terminal; nothing returns the account to `active`, so the link grants
nothing a merge could widen, and refusing the merge (OD-40) protected nothing.

**Not changed.** Active and suspended accounts still block a merge (OD-40, DEC-0107).
`STATE_MACHINES.md` transition 8 now says the link is kept.

**Recorded by** the owner's UAT round 5 decision (Ben), 2026-10-15.

**Reversible.** Yes: one predicate.

### DEC-0135 — The resend-verification 429 uses the generic sentence and the same confirmation

**Decision.** The per-connection limit on `POST /account/verification/resend` still answers
429 with `Retry-After`, but its message is the ordinary registration sentence ("If that
address can be registered, we have sent a message to it."), and the page goes to the same
"Check your email" confirmation as an accepted request. No public form on the registration
and recovery paths now says "Too many attempts".

**Why.** Owner decision (Ben, 2026-10-15), answering `PROJECT_STATUS.md` §35.4 question 3:
the rule applied to registration in UAT round 3 and to reset in DEC-0132.

**Not changed.** The limits themselves, the per-address behaviour (the ordinary body, no
429), and the throttle notices on the signed-in shipment screens.

**Recorded by** the owner's UAT round 5 decision (Ben), 2026-10-15.

**Reversible.** Yes.

### DEC-0136 — The Customer Account UAT pack has 59 cases

**Decision.** The Customer Account UAT pack's count is **59**, by heading: `CA-REG` 9,
`CA-APR` 17, `CA-SHP` 19, `CA-PRF` 4, `CA-SEC` 7, `CA-XP` 3. The 57 recorded by the
bot-executed run of 2026-10-14 is that run's own count and does not change the pack; no case
is withdrawn. `verify_uat_blank.py` keeps checking 59.

**Why.** Owner decision (Ben, 2026-10-15), closing the question open since
`PROJECT_STATUS.md` §31.6.

**Recorded by** the owner's UAT round 5 decision (Ben), 2026-10-15.

**Reversible.** Yes: a count in one script and one table.

### DEC-0137 — A registration's marketing choice reaches the linked customer; suppression evidence is shown in the audit

**Decision.** Two fix-pack rules from UAT round 5.

1. **Consent on link.** An applicant who ticked the marketing box gets one express consent
   event on the customer the account is approved against, on **link-existing** as well as
   create-new. The event is for the address the applicant proved they control, with source
   `customer_account_registration`, evidence "Customer Account registration CA-…", and the
   registration's submission time as when it was obtained. It is appended to the consent
   history and audited (`consent.record`); it is not a canonical value, so the proposal's
   per-field `applied` flags and the link-existing rule of writing no canonical value
   (OD-28) are unchanged. A suppression still wins silently (OD-27, T-08), and on a linked
   customer a consent event for the same address recorded after the registration was
   submitted is newer evidence, so the checkbox is not replayed over it. If the linked
   customer's own email differs, the event is in the history under the applicant's address
   and the channel state row, which reads the record's own address, does not change.
2. **Audit display.** `suppression.add` audit rows carry the `evidence_reference`, and the
   audit API derives it for Audit access, which shows it in the Details column. Only a value
   shaped like a reference (letters, digits and `_ - . / # :` and spaces, at most 80
   characters, no `@`) is shown. Rows written under RC-UAT-8 read it from the consent event
   they name. The address and the reason prose are still kept out of the audit detail. This
   partly supersedes DEC-0130, which kept the evidence text out. Customer Account suspend,
   reinstate and deactivate summaries now name the account: "Customer Account CA-… deactivated".

**Why.** UAT round 5: the opt-in was lost when an application was linked to an existing
customer, and Audit access showed "—" for a suppression and "Customer Account deactivate"
with no reference.

**Also in this fix pack, not decisions.** One sentence for a malformed email on every form
("Enter a valid email address, like name@example.com."), checked in the browser with the
server's rules before sending; an error summary on the Add customer dialog; a 409 is a
final answer and is not retried by the staff application.

**Recorded by** the owner's UAT round 5 approval (Ben), 2026-10-15.

**Reversible.** Yes.

### DEC-0138 — A customer has one email: once an account is linked, the record's email is its verified sign-in email

**Decision.** A customer has one email. When a Customer Account is approved and linked, the
customer record's email **is** the account's verified sign-in email, and marketing consent
and suppression apply to that same address.

1. **Link-existing where the emails differ.** The approval writes the sign-in email to the
   record (`customers.email_entered` / `email_normalized`) through
   `customer_service.update_customer`, so the record is normalized and audited as a staff
   edit is (`customer.update`), and audits why as `customer_account.sign_in_email_applied`
   (identity and customer references, `previous_email_present`, reason
   `single_email_rule`; no address in the payload). A record with no email gets it too.
2. **Staff see it before confirming.** The preview carries `email_change`
   (`{current, new}`) and the review screen shows "The customer's email will change", with
   both values, above the acknowledgement; "Submitted values written to the customer
   record" reads "Only the email". The change is in the preview fingerprint: if the
   record's email is edited after the preview, the approval is refused as stale.
3. **Consent.** The registration's opt-in (DEC-0137) is then recorded for the record's own
   address, so the email state row reflects it. This answers `PROJECT_STATUS.md` §36.4
   question 1 and replaces the last sentence of DEC-0137 point 1.
4. **Create-new.** The sign-in email is the record's email even if the registration's
   customer block carried a different one (`effective_values` now always takes the
   identity's address).
5. **It stays that way.** While an active or suspended account holds the link, a staff
   edit that changes or clears the customer's email is refused (409, field `email`, "This
   email is the sign-in email of the customer's account, so it cannot be changed here.").
   Saving the same address passes. A deactivated account's link does not hold the email,
   as it does not hold a merge (DEC-0134).

The approval and the proposal record the write: `applied_field_keys` is `["email"]` and the
decision reason is `linked_existing_email_applied` (`linked_existing_no_apply` when nothing
moved).

**Why.** Owner decision (Ben, 2026-10-15), answering `PROJECT_STATUS.md` §36.4 question 1.
Two emails for one customer left consent recorded against an address the record did not
hold.

**Supersedes in part.** OD-28 as applied by Phase 10 ("link-existing writes no canonical
value"): the email is now the one exception; every other differing value is still reported
and not applied. DEC-0137 point 1, last sentence.

**Not changed.** The sign-in email itself cannot be changed in this release (DEC-0125), so
a linked customer's email cannot change at all until that is built; how staff should handle
a customer who needs a new address meanwhile is an open question (`PROJECT_STATUS.md`
§37.4).

**Recorded by** the owner's UAT round 6 decision (Ben), 2026-10-15.

**Reversible.** Yes: one write in the approval, one preview field and one edit guard.

### DEC-0139 — A suppression blocks marketing email only, never account email

**Decision.** `contact_suppressions` blocks **marketing** email and nothing else.
Transactional account email is sent to a suppressed address like any other: the
verification email at registration and on resend, the registration-attempt notice, the
password reset, and the approval and rejection notices. Registration with a suppressed
address creates the identity and proposal and sends the verification email (outcome
`created`; `suppressed` is no longer written, and a replay of an attempt row a suppression
refused under RC-UAT-9 is given the registration it was refused).

The marketing opt-in stays ineffective while suppressed: `consent_service` still refuses a
consent grant against a suppressed address, the approval lets that refusal stand silently
(DEC-0137), and the address is not marketing-eligible. The customer reads nothing about the
suppression or its reason: every answer is the ordinary one, no customer-facing response or
message names it, and the profile's `marketing.delivery_blocked` (DEC-0127) stays a
boolean with no reason.

**Why.** UAT round 6 defect on RC-UAT-9: registering with a suppressed address recorded
"registration received" and sent no verification, so the customer could never finish
signing up and the UAT-OP-13 Phase 12 add-on could not complete. Owner decision (Ben,
2026-10-15): suppression must only block marketing email, never transactional account
email.

**Supersedes in part.** OD-27 and T-08 as Phase 9 applied them ("a suppressed address
receives nothing"), `EMAIL_DELIVERY.md` §6 test obligation 3, and the FIELD_MATRIX §4
definition of global suppression as a block on contacting an address "at all".

**Not changed.** Who may suppress (DEC-0133) and release (Admin); suppression is still
global to channel and address and survives merges and re-imports; a customer still cannot
read, create or release one (T-08); segments and exports still exclude a suppressed address.

**Recorded by** the owner's UAT round 6 decision (Ben), 2026-10-15.

**Reversible.** Yes: the checks were removed from five call sites.

### DEC-0140 — A deactivated account's customer can be taken over by a new account, by staff approval

**Decision.** A customer whose only Customer Account link belongs to a **deactivated**
account may be linked to a new registration, and only by a staff link-existing approval.
Approving ends the old link in the same transaction: the row becomes `revoked`, with
`revoked_by_user_id`, `revoked_at` and reason `taken_over_by_new_account`, audited as
`customer_account.unlink` against the old account, naming the customer and the new account.
The new link is then inserted, so the partial unique index (one active link per customer)
still holds. The preview names the account whose link ends (`ends_link_of`), the review
screen shows "Approving ends a deactivated account's link" above the acknowledgement, and it
is in the preview fingerprint: a deactivation after the preview makes the approval stale.
The duplicate-candidate list marks such a customer linkable.

A link held by an **active or suspended** account is never ended this way; the approval is
refused (409) as before. Previewing and acknowledging end nothing.

**Why.** Owner decision (Ben, 2026-10-15), answering `PROJECT_STATUS.md` §36.4 question 2.

**Supersedes in part.** DEC-0134's last sentence ("a customer whose only link belongs to a
deactivated account still cannot be linked to a second account").

**Not changed.** Deactivation still keeps the link (DEC-0134) until a takeover is approved;
the old account stays `deactivated`.

**Recorded by** the owner's UAT round 6 decision (Ben), 2026-10-15.

**Reversible.** Yes.

### DEC-0141 — The evidence reference field says "Ticket or reference number only, no names"

**Decision.** Both evidence-reference fields on the Consent tab (Record consent change, and
Suppress address) carry the helper text "Ticket or reference number only, no names", tied
to the field as its description. The audit display keeps refusing a value containing `@`
(DEC-0137).

**Why.** Owner decision (Ben, 2026-10-15), answering `PROJECT_STATUS.md` §36.4 question 3:
evidence references now reach the audit trail, and the display cannot recognise a name.

**Recorded by** the owner's UAT round 6 decision (Ben), 2026-10-15.

**Reversible.** Yes: one string.

### DEC-0142 — Staff change a linked customer's email only after the account is deactivated

**Decision.** Staff cannot change the email of a customer whose Customer Account is
**active or suspended**. The account must be deactivated first (Admin, DEC-0126); once it
is, the email is an ordinary staff edit again. There is no staff path that changes a held
email and the sign-in address together.

1. **The rule is shown before anybody types.** The customer detail carries
   `email_held_by_account` (true while an active or suspended account holds the link, the
   predicate behind DEC-0138 point 5). When it is true the edit form's email field is
   read-only and says "This is the sign-in email of the customer's account, which is active
   or suspended. To change it, deactivate the account first." Every other field stays
   editable, and saving sends the unchanged address, which passes.
2. **The server still refuses.** A stale form or a direct request that changes or clears
   the email gets 409 on field `email`, now worded "This email is the sign-in email of the
   customer's account, so it cannot be changed while the account is active or suspended.
   Deactivate the account first." (replacing the DEC-0138 point 5 wording).
3. **Deactivation does not move the sign-in email.** Editing the customer's email after
   deactivation changes the customer record only; the deactivated account keeps its own
   address.

**Why.** Owner decision (Ben, 2026-10-16), answering `PROJECT_STATUS.md` §37.4 question 1.
Customer self-service email change stays deferred (DEC-0125).

**Supersedes in part.** DEC-0138 point 5 (the refusal's wording) and its "Not changed"
paragraph (the open question is answered).

**Recorded by** the owner's UAT round 7 decision (Ben), 2026-10-16.

**Reversible.** Yes: one response field, one form state and one string.

### DEC-0143 — A suppression blocks marketing email only, including for shipment and operational email

**Decision.** DEC-0139 applies to every email that is not marketing, not only the account
email that exists today. Shipment notifications and other operational email to a
suppressed address keep sending when they are built. Only marketing selection (segments,
exports, marketing eligibility) reads `contact_suppressions`; no module that sends email
does. `test_uat_round_7.py` checks the second half structurally, so a future sender that
reads a suppression fails the suite.

**Why.** Owner decision (Ben, 2026-10-16), answering `PROJECT_STATUS.md` §37.4 question 2.

**Not changed.** DEC-0139 in full. No shipment email exists in this release.

**Recorded by** the owner's UAT round 7 decision (Ben), 2026-10-16.

**Reversible.** Yes.

### DEC-0144 — A takeover sends no notice to the former holder; it is audited only

**Decision.** When a staff link-existing approval takes over a customer from a deactivated
account (DEC-0140), no message is sent to the former account holder. The record of the
takeover is the revoked link (`taken_over_by_new_account`) and the `customer_account.unlink`
audit row. The new holder receives the ordinary approval notice, which names neither the
former account nor its address.

**Why.** Owner decision (Ben, 2026-10-16), answering `PROJECT_STATUS.md` §37.4 question 3.

**Not changed.** DEC-0140.

**Recorded by** the owner's UAT round 7 decision (Ben), 2026-10-16.

**Reversible.** Yes: a notice would be a new template and one send.

### DEC-0145 — Registration asks for the shipping address first, with "Billing address is the same as shipping address"

**Decision.** The registration form shows the shipping (pickup) address section first and
the billing address second. At the top of the billing section is a checkbox, "Billing
address is the same as shipping address".

1. **Default.** The box ticks itself once a shipping street (address line 1) is typed and
   no billing street has been, and from the first time the person touches it, it is
   whatever they chose. With no shipping address it starts unticked.
2. **Ticked.** The billing fields are hidden and no `billing_address.*` key is sent. The
   request carries `billing_same_as_shipping: true` and the server copies the shipping
   street lines, city, province or state, postal code and country into `billing_address.*`
   before the allowlist runs, so the proposal holds an ordinary billing address. The
   pickup-only parts (who to ask for, the pickup phone, the note) are not copied.
3. **Unticked.** The billing fields are shown **empty** (country Canada), not prefilled
   with the shipping address.
4. **Server checks, both ways.** Ticked: a shipping street is required (field
   `billing_same_as_shipping`), and a billing key sent alongside is refused rather than
   silently preferred (same field). Unticked: when a shipping street is given, a billing
   street is required (field `billing_address.address_line1`), and the form marks that
   field "(required)". With no shipping address the billing address stays optional, as it
   was (`FIELD_MATRIX.md` §2). A request without the flag is read as unticked.
5. **Mobile.** The two sections carry their own autofill section tokens (`section-shipping
   shipping …`, `section-billing billing …`), so a phone's address autofill does not
   write one address into both.

**Why.** Owner feedback from real-phone UAT (Ben, 2026-10-17), items 1 and 2.

**Not changed.** The allowlist (`app/core/account_fields.py`), the proposal model, and what
an approval does with a billing address (DEC-0096). The Customer Account stays English only
(OD-39), so the new wording is English; there is no Vietnamese Customer Account catalogue.

**Recorded by** the owner's UAT round 8 feedback (Ben), 2026-10-17.

**Reversible.** Yes: one request flag and one form section.

### DEC-0146 — The password is typed twice at registration and at reset, and the server checks it

**Decision.** Registration gains a **Confirm password** field under Password; the reset
page already had **New password again**. On both, a missing or different second copy blocks
submission with an inline error beside the second box, linked from the error summary on
registration, and nothing is sent. The server refuses it as well: both requests carry
`password_confirmation`, and a missing one is refused with "Type the password again to
confirm it." and a different one with "The two passwords do not match.", both on field
`password_confirmation`, 422. The comparison is exact (no trimming, no case folding), and it
runs after the password rules, so a short password is reported as short. A refused reset
does not consume its link. On the reset page a short password and a server refusal of
either field are also shown beside the field; only a link problem is shown for the whole
form.

**Why.** Owner feedback from real-phone UAT (Ben, 2026-10-17), item 3.

**Not changed.** The password policy (`RATE_LIMITS_AND_ABUSE.md` §5), the rate limits, and
the generic sentences for every registration and reset outcome.

**Recorded by** the owner's UAT round 8 feedback (Ben), 2026-10-17.

**Reversible.** Yes.

### DEC-0147 — An approved change request's own values are not drift

**Decision.** On the profile change review, a field is flagged "Changed since" (`drifted`)
when the value on file now differs from the value on file at submission, **except** when
the field was applied by this request and the value on file now equals the value it
proposed (as entered or normalized, compared ignoring case and spacing). That difference is
the approval itself. A later change by anyone else moves the value away from the approved
one and is flagged again. A declined field is unchanged by the decision and is not flagged.
The rule that refuses approving a field that drifted before the decision is unchanged.

**Why.** Staff-side verification for UAT round 8 (2026-10-17): after an approval the review
screen marked every approved field as changed, because the approved values had just been
applied.

**Recorded by** the owner's UAT round 8 instruction (Ben), 2026-10-17.

**Reversible.** Yes: one predicate.

### DEC-0148 — The approval of a change request audits each field with its old and new value

**Decision.** Approving a Customer Account change request writes one `customer.update`
audit row for every approval, an address-only one included, with:

* `changed_fields` naming each applied field (`legal_name`, `display_name`, `phone`,
  `pickup_address.1.city` and so on) instead of the `contact` pseudo-field;
* `changes`, one entry per applied field whose value moved: `{field, old, new}`, values in
  full, nothing masked, because a role that reads the audit can already read them on the
  customer record;
* `source: customer_account_profile_proposal`, and the summary "Updated customer CUS-… from
  an approved change request".

Audit access shows the entries under **Changes** as "field: old → new", with "(blank)" for
an empty side (Vietnamese "field: từ old thành new", "(trống)"). This is the one audit row
whose values are shown: the display reads `changes` only, checks each field name is a
field-name token and each side is text or empty, and cuts a side at 300 characters. A plain
staff edit still writes and shows field names only. The `customer_data_proposal.decide` row
is unchanged (groups and reason code, no values).

**Why.** Staff-side verification for UAT round 8 (2026-10-17): the row written on approval
said only that "contact" changed.

**Supersedes in part.** The UAT round 3 rule that Audit access never shows a value, for this
one row type.

**Recorded by** the owner's UAT round 8 instruction (Ben), 2026-10-17.

**Reversible.** Yes.

### DEC-0149 — A customer acting through their account is the actor of its audit row

**Decision.** The audit rows a signed-in customer causes on their own record name them as
the actor, `customer_account:CA-…`, instead of `system`: the marketing choice (grant and
withdrawal), the direct language change, and submitting, superseding and withdrawing a
change request. No staff user id is written for them. The consent history on the customer
record shows the same label in its **By** column for a consent event the customer recorded
from their account (`recorded_by_account`, read from the event's own
`customer_account:CA-…` reference when its source is `customer_account`); a staff entry
shows the staff name, and an import or seeded row shows **System** (Vietnamese "Hệ thống").
Unauthenticated events (registration, verification, sign-in, reset) still read `system`.

**Why.** Staff-side verification for UAT round 8 (2026-10-17): a customer withdrawing
marketing consent from the Customer Account was logged as "system".

**Not changed.** What these payloads contain (keys, statuses and codes, never a submitted
value).

**Recorded by** the owner's UAT round 8 instruction (Ben), 2026-10-17.

**Reversible.** Yes.

### DEC-0150 — Registration's first address is "Address", and the driver note is "Notes for driver"

**Decision.** On the registration form:

1. the first address section is headed **Address** instead of "Shipping address". It is
   still the pickup address (`pickup_address.1.*`); only the words changed. Its description
   is "Your street address. Solaris Express collects parcels from here when you book a
   pickup." (the round 8 "Leave blank if you drop parcels off" is gone, because the address
   is now required, DEC-0151);
2. the billing checkbox reads **"Billing address is the same as the address above"**, its
   ticked hint "We will use the address above for invoices too.", and the server's sentence
   for a ticked box sent with billing keys names the same words;
3. the last pickup field, "Anything the driver should know", is **"Notes for driver (buzz
   code, contact concierge, security,...)"**. Same key (`pickup_address.1.delivery_note`),
   still optional, same 400-character limit.

**Why.** Owner decisions, UAT round 9 (Ben, 2026-10-18), items 1 and 3.

**Not changed.** The request flag keeps its name, `billing_same_as_shipping`: it is an API
field, not wording, and renaming it would break a client for no customer-visible gain. The
allowlist and the order of the sections (DEC-0145). English only (OD-39, DEC-0154).

**Recorded by** the owner's UAT round 9 decisions (Ben), 2026-10-18.

**Reversible.** Yes: wording.

### DEC-0151 — The registration address's country, line 1, city, province or state and postal code are required

**Decision.** At registration the address (`pickup_address.1`) must have a **country**,
**address line 1**, **city**, **province or state** and **postal code**. Address line 2, who
the driver asks for, the pickup phone and the driver note stay optional.

1. **Form.** The five are marked "(required)". On submit, each one empty (or only spaces)
   gets its own error beside the field and a linked entry in the error summary, in screen
   order, and nothing is sent: "Choose the country.", "Enter the street address (address
   line 1).", "Enter the city.", "Enter the province or state.", "Enter the postal code."
   ("Enter the ZIP code." when the country is the United States, matching the field's
   label). The country is a list that starts on Canada, so in practice its error is only
   reachable from a client that sends no country.
2. **Server.** `POST /api/v1/account/register` refuses the **first** part missing, in the
   same order, 422 with that part's key as `field` (for example
   `pickup_address.1.postal_code`) and the same sentence. The form shows a server refusal
   beside that field. Checked before the billing box (DEC-0152) and before the allowlist,
   and after the password checks.
3. Postal codes are required for Vietnam as for Canada and the United States; the format is
   not checked beyond what the normalizer already does.

**Why.** Owner decisions, UAT round 9 (Ben, 2026-10-18), item 2.

**Supersedes in part.** `FIELD_MATRIX.md` §2's "every address field is optional at
registration", and DEC-0145 point 4's "with no shipping address the billing address stays
optional" (there is no longer a registration with no address). DEC-0145 point 4's refusal
"ticked without a shipping street" (field `billing_same_as_shipping`) can no longer be
reached: the missing address part is refused first, by name.

**Not changed.** The profile change request's own address rules (My profile), and what an
approval does with the address.

**Recorded by** the owner's UAT round 9 decisions (Ben), 2026-10-18.

**Reversible.** Yes: one tuple on each side.

### DEC-0152 — With the billing box unticked, the billing address needs the same five parts

**Decision.** When "Billing address is the same as the address above" is unticked
(`billing_same_as_shipping: false`, or absent), the billing address must have a country,
line 1, city, province or state and postal code, exactly as the address does (DEC-0151):
marked "(required)", an inline error and summary entry for each one missing ("Choose the
billing country.", "Enter the billing street address (address line 1).", "Enter the billing
city.", "Enter the billing province or state.", "Enter the billing postal code." or "ZIP
code"), nothing sent; and the server refuses the first missing `billing_address.*` part,
422, after the address's own parts. Ticked, no billing part is asked for or accepted and
the server copies the address (DEC-0145, unchanged).

Because the box ticks itself only once a street is typed (DEC-0145 point 1), a person who
presses **Create account** on an untouched form sees the billing errors as well as the
address's; they disappear when the street is typed and the box ticks.

**Why.** Owner decisions, UAT round 9 (Ben, 2026-10-18), item 4, which also answers
PROJECT_STATUS §39.4 question 2.

**Supersedes in part.** DEC-0145 point 4's "unticked: a billing street is required when a
shipping street is given" (field `billing_address.address_line1`, message "Enter the
billing address, or tick …"). Now all five parts, always, when unticked.

**Recorded by** the owner's UAT round 9 decisions (Ben), 2026-10-18.

**Reversible.** Yes.

### DEC-0153 — A customer's own sign-in and sign-out name their account as the actor

**Decision.** The `customer_account.sign_in` and `customer_account.sign_out` audit rows are
written with the actor `customer_account:CA-…`, as the profile and consent events have been
since DEC-0149, instead of `system`. No staff user id is written. Audit access shows the
label in its **Actor** column. A **refused** sign-in (`customer_account.sign_in_failed`)
keeps `system`: whoever typed the password is not known to be the customer. Registration,
verification, password reset, lockout and session revocation also keep `system`.

**Why.** Owner decisions, UAT round 9 (Ben, 2026-10-18), item 5, which answers PROJECT_STATUS
§39.4 question 3.

**Supersedes in part.** DEC-0149's "sign-in … still read `system`".

**Not changed.** The payloads (identity reference and status, never an address).

**Recorded by** the owner's UAT round 9 decisions (Ben), 2026-10-18.

**Reversible.** Yes.

### DEC-0154 — Vietnamese Customer Account copy is its own later pack; OD-39 stands

**Decision.** The Customer Account stays English only for now (OD-39 unchanged): fix pack 9
adds no Vietnamese Customer Account strings and no language switch. Vietnamese customer
copy (registration, sign-in, reset, the shipment and profile screens, and the account
emails) is a separate, later fix pack with its own language review. Staff screens keep
their EN and VI catalogues as before.

**Why.** Owner decisions, UAT round 9 (Ben, 2026-10-18), item 6, which answers
PROJECT_STATUS §39.4 question 1.

**Recorded by** the owner's UAT round 9 decisions (Ben), 2026-10-18.

**Reversible.** Yes: the later pack is the reversal.

### DEC-0155 — A refused Customer Account sign-in is committed

**Decision.** `POST /api/v1/account/sign-in` commits the session before it returns a
refusal. `customer_auth_service.authenticate` records the refusal
(`customer_account.sign_in_failed`, by reason code and hashed address key), counts the
failure on a known identity and locks it at the threshold (`customer_account.locked`), and
then raises; the route used to let that exception escape with the session uncommitted, so
the request's session closed and all three were rolled back. Over HTTP no
`sign_in_failed` row was written and the per-identity lockout (`RATE_LIMITS_AND_ABUSE.md`
§3.1) never engaged; the service-level test passed because it committed by hand. The
response is unchanged: 401 and the one generic sentence, for every reason. Known and
unknown addresses still do comparable work, both now committing one audit row.

**Why.** Found while testing DEC-0153 (UAT round 9, 2026-10-18). A control that is
documented, tested at the service level and absent at the route is a defect. Committed
separately from the round 9 items so it can be reviewed, or reverted, on its own.

**Not changed.** The IP and address rate limiters (never affected; they are in memory),
the lockout threshold and duration, the response.

**Recorded by** the fix pack 9 implementation, 2026-10-18, for the owner's review
(PROJECT_STATUS §40.4).

**Reversible.** Yes: one `try`/`except`. Reverting it restores the defect.

### DEC-0156 — The Customer Account shipment list has a keyword search

**Decision.** On **My shipments**, the "Solaris Shipment ID" filter (the whole ID, exactly)
is replaced by a **Search shipments** box. Its hint: "Searches the Solaris Shipment ID, your
booking reference, and the city it was sent from or to. Part of a word is enough; capitals
and accents do not matter." It is a `type="search"` box with the phone keyboard's search
key, 64 characters at most, and its value travels as `q` on
`GET /api/v1/account/shipments`.

1. **What it matches.** A shipment whose Solaris Shipment ID (`public_id`), booking
   reference (`booking_reference`), origin city or destination city (`origin_city`,
   `destination_city`, the two the list shows) **contains** the keyword. Case and accents
   are ignored on both sides by one fold, `app.core.normalization.search_fold`, registered
   on every SQLite connection as `solaris_search_fold`: "da nang", "ĐÀ NẴNG" and "Đà Nẵng"
   are one search. Spaces at either end are dropped and runs of spaces count as one.
   Nothing is removed beyond that, so the `-` in an ID is still typed as `-`.
2. **What it does not read.** Recipient or sender name, company, address, postal code,
   phone or email; contents; notes; cancellation reasons; carrier tracking numbers; package
   references. The four columns are a fixed tuple in the service (`KEYWORD_COLUMNS`); the
   caller cannot name a column.
3. **Safety.** The keyword is folded, its `%`, `_` and `\` are escaped, and the resulting
   `LIKE` pattern is a bound parameter with `ESCAPE '\'`: a wildcard matches itself. Over
   64 characters is refused by the service with this surface's 422 body, field `q`,
   "Search for 64 characters or fewer.", without echoing the value. An empty or all-space
   keyword is no search. The keyword is never logged. The read rate limit is consumed
   before it is parsed, as for every filter.
4. **Ownership.** The clause is appended after `qualifying_conditions(customer_id)`, like
   every other filter, so it can only narrow the caller's own rows. A keyword that matches
   only another customer's shipment returns the same empty page, byte for byte, as one that
   matches nothing anywhere. Drafts and demo rows stay out.
5. **With the other filters.** Status group, route group and the booked from/to dates still
   apply, together with the keyword (an intersection). The URL carries `q` with the rest,
   so a search can be bookmarked. "Apply filters" (or the keyboard's search key) sends it;
   typing does not.
6. **The exact `reference` parameter stays** on the API, unchanged (DEC-0114), so no client
   breaks; the screen no longer sends it. A pre-round-10 link carrying `?reference=` opens
   with that value in the search box and is sent as `q`, which finds the same shipment.

**Why.** Owner feedback from real-phone UAT (Ben, 2026-10-18, UAT round 10): the filter
required the exact full ID. Accents are folded as well as case because Vietnamese city names
are typed both ways on a phone, and SQLite's own `lower()` folds ASCII only, so "đà nẵng"
would not have found "Đà Nẵng".

**Supersedes in part.** `SHIPMENT_ALLOWLISTS.md` §3.2's "no free-text search in release 1"
(amended, §3.4), and the free-text absence AS-06's replacement asserted (registered as
AS-08 in `SUPERSEDED_ASSERTIONS.md`).

**Disclosure note.** `booking_reference` is outside the 17-field list allowlist (§3.1,
"internal booking and import mechanics") and is still not returned. Searching it lets a
signed-in customer learn that one of their **own** shipments' booking reference contains a
string, one request at a time under the read limit. `DATA_DICTIONARY.md` describes the
field as the customer's or partner's own reference, so this was judged acceptable; it is
listed for the owner in PROJECT_STATUS §41.4.

**Not changed.** The list and detail allowlists, the ordering, paging, the detail route,
Public Tracking, and the staff shipment search.

**Recorded by** the owner's UAT round 10 instruction (Ben), 2026-10-18.

**Reversible.** Yes: the `q` clause and the box; `reference` never left.

### DEC-0157 — The sign-in lockout fix, the Canada default and accent-free search stay as built

**Decision.** Three behaviours the owner was asked about in PROJECT_STATUS §40.4 and §41.4
stay exactly as they are:

1. **DEC-0155 stands.** A refused Customer Account sign-in is committed, so its audit row,
   the failure count and the per-identity lockout (ten wrong passwords in fifteen minutes
   lock the account for fifteen minutes) take effect over HTTP.
2. **The country lists start on Canada**, for the address, billing and phone country. There
   is no "Choose a country" entry. The "Choose the country." error stays for a client that
   sends no country.
3. **The shipment keyword search ignores accents as well as case** (DEC-0156): "Da Nang",
   "da nang" and "ĐÀ NẴNG" all find "Đà Nẵng".

**Why.** Owner decisions (Ben, 2026-10-18, UAT round 11, items 1, 3 and 6).

**Not changed.** Nothing: this entry records answers, not code.

**Recorded by** the owner's UAT round 11 decisions (Ben), 2026-10-18.

**Reversible.** Each one separately, as its own decision says.

### DEC-0158 — The registration billing box starts ticked

**Decision.** On registration, "Billing address is the same as the address above" is
**ticked when the form opens**, so the billing fields are hidden and an empty form pressed
**Create account** lists only the address's errors, not billing ones. Unticking it shows
empty billing fields, which are then required (DEC-0152, as amended by DEC-0159). Ticking
it again hides them and sends none. The form always sends `billing_same_as_shipping`
explicitly. The API's own default for that flag stays `false`, so a client that omits it
must still send a billing address.

**Why.** Owner decision (Ben, 2026-10-18, UAT round 11, item 2), answering PROJECT_STATUS
§40.4 question 2: an untouched form showed billing errors before a street had been typed.

**Supersedes in part.** DEC-0145's "the box ticks itself once a street is typed": there is
nothing left to tick, because it starts ticked. This box is not a consent control, so the
rule that every consent box starts unchecked (OD-27, OD-38) is unaffected; the terms and
marketing boxes still start unchecked.

**Not changed.** What ticked and unticked send, the server's conflict check
(`BILLING_SAME_WITH_BILLING`), the copy of the address into billing.

**Recorded by** the owner's UAT round 11 decisions (Ben), 2026-10-18.

**Reversible.** Yes: the box's initial state.

### DEC-0159 — The postal code is optional at registration, for every country

**Decision.** The registration address and an unticked billing address each require
**Country, Address line 1, City, and Province or state**. The postal code (ZIP code for
the United States) is **optional** for both, in Canada, Vietnam and the United States: its
label says "(optional)", a blank one produces no error on the form and is never refused by
the server (`REQUIRED_ADDRESS_PARTS` no longer lists it), and nothing is stored for it. A
postal code that is typed is kept as typed; no format is checked, on either side, so a
lenient check is all there is: the field's existing 30-character bound
(`app.core.account_fields`). The ticked billing box copies it when there is one.

**Why.** Owner decision (Ben, 2026-10-18, UAT round 11, item 4), answering PROJECT_STATUS
§40.4 question 4: Vietnamese addresses often have none.

**Supersedes in part.** DEC-0151 and DEC-0152's fifth required part. The ZIP code
refusal's test is registered as AS-09 in `SUPERSEDED_ASSERTIONS.md`.

**Not changed.** The other four parts, their sentences and their order; line 2 and the
driver fields (optional); the Staff Portal's address forms, which never required a postal
code.

**Recorded by** the owner's UAT round 11 decisions (Ben), 2026-10-18.

**Reversible.** Yes: one tuple member and one form field.

### DEC-0160 — The shipment list shows the booking reference

**Decision.** Each row of the Customer Account shipment list carries the shipment's
`booking_reference`, the customer's or partner's own reference for the booking
(`DATA_DICTIONARY.md`), trimmed, or `null` when none was given. It is the eighteenth field
of `AccountShipmentListItem`. The screen shows it as **Booking reference** under the Solaris
Shipment ID on the wide table, and as the first fact on each phone card; a shipment without
one shows "Not recorded" there. It is read only from the caller's own rows, after the
ownership clause, like every list field.

**Why.** Owner decision (Ben, 2026-10-18, UAT round 11, item 5), answering PROJECT_STATUS
§41.4 question 1: a shipment found by its booking reference appeared with nothing on the
row saying why.

**Supersedes in part.** `SHIPMENT_ALLOWLISTS.md` §3 (17 fields, now 18) and §3.1, which
listed `booking_reference` among "internal booking and import mechanics" (amended), and
DEC-0156's disclosure note ("searched, not shown"). Registered as AS-10 (the search test),
AS-12 and AS-15 (the field count and the field-by-field row check) and AS-13, AS-14 and
AS-16 (the privacy scans, which now allow it on the list only).

**Not changed.** The **detail** stays at its 24 fields and does not carry the booking
reference; Public Tracking stays at 24 fields and never shows it; `idempotency_key`,
`source_system` and `source_record_id` stay excluded. Staff should still put nothing in a
booking reference they would not want the customer to read (Staff Guide).

**Recorded by** the owner's UAT round 11 decisions (Ben), 2026-10-18.

**Reversible.** Yes: one schema field, one assignment and two screen lines.

### DEC-0161 — A package reference finds its shipment in the keyword search

**Decision.** The shipment list's keyword search (`q`, DEC-0156) also matches a shipment
when one of **its own** packages' `package_reference` contains the keyword, with the same
fold (case and accents ignored), the same escaped, bound `LIKE` pattern and the same
64-character bound. It is an `EXISTS` over `shipment_packages` correlated on
`shipment_id`, appended inside the keyword clause, which is itself appended after
`qualifying_conditions(customer_id)`: a package can only find the shipment it belongs to,
and that shipment must still be the caller's. A shipment with several matching packages is
one row. Cancelled packages count, because the detail shows them as cancelled. Another
customer's package reference returns the same empty page as one that does not exist. The
search box's hint names package references.

**Why.** Owner decision (Ben, 2026-10-18, UAT round 11, item 7), answering PROJECT_STATUS
§41.4 question 3: a whole package reference (`…-01`) found nothing.

**Supersedes in part.** DEC-0156 item 2 ("package references" were not read) and
`SHIPMENT_ALLOWLISTS.md` §3.4 (amended). The test that asserted it is registered as AS-11.

**Not changed.** The other columns read, and those never read (recipient and sender
details, addresses, phones, emails, contents, notes, carrier tracking numbers); the exact
`reference` parameter, which still takes a Solaris Shipment ID only; the detail route,
still addressed by Solaris Shipment ID only.

**Recorded by** the owner's UAT round 11 decisions (Ben), 2026-10-18.

**Reversible.** Yes: one `EXISTS` clause.

### DEC-0162 — The Customer Account UAT pack has 60 cases, with CA-SHP-20 for the keyword search

**Decision.** The Customer Account UAT pack gains **CA-SHP-20 — Searching your shipments
by keyword**, and its count is **60**, by heading: `CA-REG` 9, `CA-APR` 17, `CA-SHP` 20,
`CA-PRF` 4, `CA-SEC` 7, `CA-XP` 3. `verify_uat_blank.py` checks 60. CA-SHP-09 goes back to
filtering by status group only and points to CA-SHP-20; CA-SHP-19 and CA-XP-01 keep their
search steps.

**Why.** Owner decision (Ben, 2026-10-18, UAT round 11, item 8), answering PROJECT_STATUS
§41.4 question 4.

**Supersedes in part.** DEC-0136's count of 59. Its other point stands: the 57 of the
2026-10-14 bot run was that run's count, and no case is withdrawn.

**Recorded by** the owner's UAT round 11 decisions (Ben), 2026-10-18.

**Reversible.** Yes: a heading, a count in one script and one table.

### DEC-0163 — The shipment detail shows the booking reference too

**Decision.** `AccountShipmentDetail` carries `booking_reference`, the same value the list
row carries (DEC-0160): the shipment's `booking_reference`, trimmed, or `null` when none was
given, read through one function for both. It is the detail's **twenty-fifth** field,
declared in the identity group after `shipment_reference`. The detail screen shows it as
**Booking reference** at the top of "Where it is", the same row on a phone and on a wide
screen, with "Not recorded" when there is none. A cancelled shipment's detail still shows
it. Another customer's shipment is still the generic not-found body, which carries no
booking reference.

**Why.** Owner decision (Ben, 2026-10-19, UAT round 12, item 1), answering PROJECT_STATUS
§42.4 question 1.

**Supersedes in part.** DEC-0160's "not added to the detail", and the parity of the
authenticated detail with Public Tracking (`SHIPMENT_ALLOWLISTS.md` §4 and §4.1, amended):
the detail is now the public 24 plus this one field. Registered as AS-19 to AS-26 in
`SUPERSEDED_ASSERTIONS.md`.

**Not changed.** `PublicTrackingResult` stays at exactly 24 fields and never carries the
booking reference (OD-31). The list row, the search and every other excluded field
(`idempotency_key`, `source_system`, `source_record_id`, recipient and sender details,
money) are unchanged.

**Recorded by** the owner's UAT round 12 decisions (Ben), 2026-10-19.

**Reversible.** Yes: one schema field, one assignment and one screen row.

### DEC-0164 — A cancelled package's reference still finds its shipment

**Decision.** The keyword search keeps matching a shipment when one of its own **cancelled**
packages' reference contains the keyword, as DEC-0161 built it. It stays limited to the
caller's own shipments: another customer's cancelled package reference returns the same
empty page as one that does not exist.

**Why.** Owner decision (Ben, 2026-10-19, UAT round 12, item 2), answering PROJECT_STATUS
§42.4 question 2.

**Not changed.** Nothing in the code; this entry records the answer and the test that
pins the stranger case (`test_uat_round_12.py`).

**Recorded by** the owner's UAT round 12 decisions (Ben), 2026-10-19.

**Reversible.** Yes: one condition on the `EXISTS` clause.

### DEC-0165 — A typed Canadian or United States postal code has a lenient shape check

**Decision.** The registration postal code stays **optional** (DEC-0159): blank is always
allowed and stores nothing. When one is typed for an address whose country is **Canada**, it
must be letter, digit, letter, an optional single space, digit, letter, digit, in any case
(`A1A 1A1`, `a1a1a1`); for the **United States**, five digits or ZIP+4 with a hyphen
(`12345`, `12345-6789`). Spaces around the code are ignored, as for every field. No other
country is checked. The check is on both sides with the same sentences, beside the field
and in the summary: "Enter the postal code as A1A 1A1, or leave it blank." and "Enter the
ZIP code as 12345 or 12345-6789, or leave it blank.", with "billing" in them for the
billing block. The server checks each address's code against that address's own country
(`account_fields.POSTAL_CODE_SHAPES`), after the required-part checks, so a missing part is
still reported first. A code that passes is kept as typed. Because the check lives in the
shared field normalizer, a signed-in customer's address-change proposal (*My information*,
`pickup_address.1.*`) is held to the same shapes by the server, and its screen shows the
refusal beside Postal code; that screen has no client-side check of its own.

**Why.** Owner decision (Ben, 2026-10-19, UAT round 12, item 3), answering PROJECT_STATUS
§42.4 question 3.

**Supersedes in part.** DEC-0159's "no format is checked". Registered as AS-17.

**Not changed.** Which parts are required, the 30-character bound, the Staff Portal's
address forms, and Vietnamese codes (unchecked).

**Recorded by** the owner's UAT round 12 decisions (Ben), 2026-10-19.

**Reversible.** Yes: one table of two patterns on each side.

### DEC-0166 — The API's billing box defaults to ticked, as the form does

**Decision.** `RegistrationRequest.billing_same_as_shipping` defaults to **true**. A client
that omits it gets what the untouched form sends: the address is copied into billing and no
billing address is asked for. A client that sends billing keys without the flag is refused
with the existing conflict sentence (`BILLING_SAME_WITH_BILLING`, field
`billing_same_as_shipping`), so it must send `false` with a separate billing address. The
registration form already sends the flag every time, so the screen does not change.

**Why.** Owner decision (Ben, 2026-10-19, UAT round 12, item 4), answering PROJECT_STATUS
§42.4 question 4.

**Supersedes in part.** DEC-0158's "the API's own default for that flag stays false".
Registered as AS-18.

**Not changed.** What true and false each do, and the conflict check.

**Recorded by** the owner's UAT round 12 decisions (Ben), 2026-10-19.

**Reversible.** Yes: one default.

### DEC-0167 — The Louis handoff merges into this CRM; v1.5 is source material, not a code base

**Decision.** The B2C requirements in "CRM handoff from Louis" (bundle v1.6) are built as
phases of this repository, starting from RC-UAT-16. The v1.5 static application is read for
its approved workflow and business rules and for the vendor workbook it ships; none of its
code is ported. The audit, feature matrix, issue register, open decisions and plan are under
`docs/b2c_merge/`.
**Why.** Owner decision (Ben, 2026-10-19). This repository has persistence, identity, roles,
audit, privacy scans and about 3,800 tests; v1.5 is a browser-storage prototype whose own
pricing engine mis-prices five surcharge rows (`docs/b2c_merge/04_ISSUE_REGISTER.md`).
**Recorded by** the owner's instruction, 2026-10-19. A pre-merge backup of every branch and
both working trees was taken first (`CRM/Backups/2026-10-19_pre-merge/`).
**Reversible.** The branch `phase-13-b2c-merge` is additive; nothing in RC-UAT-16 changed.

### DEC-0168 — Vendor tariffs are imported from the workbook as immutable versions with per-cell provenance

**Decision.** A tariff is a `tariff_versions` row created by importing the vendor's `.xlsx`
through `app/pricing/kango_workbook.py`. Every rate bracket, beyond rate and surcharge rule
carries the sheet and cell (or row) it was read from; the version carries the file's SHA-256,
and the same bytes cannot be imported twice. A version is `draft` until an administrator
activates it, which supersedes the previous active version and never deletes it. Tables are
anchored on the vendor's header text, not row numbers, because the Hà Nội sheet sits one row
higher than the HCM sheet.
**Why.** Handoff §6 and §16 require source-driven pricing with preserved snapshots so a past
quotation can be reproduced; the v1.5 JSON was faithful to the workbook's numbers but carried
none of its rules (`docs/b2c_merge/02_KANGO_WORKBOOK_AUDIT.md` §4).
**Not imported, by decision.** Trucking pallet delivery fees (quoted per case), the
compensation policy sheet (prose), and the vendor staff directory sheet, which is excluded
by name and never read.
**Reversible.** Yes: the migration `f53efaa7773e` adds twelve tables and touches nothing else.

### DEC-0169 — Ambiguity in the surcharge sheet is stored as a pricing status, never guessed into a number

**Decision.** The price-text parser (`kango_semantics.parse_price_text`) reads only
unambiguous forms (`30.000/Kg`, `1.000.000/1 Kiện`, `Miễn phụ thu`, `… ( Min thu 1Kg )`) and
refuses ranges, estimates (`Dự kiến >`), compounds (`… + 50.000/Chai`), "case by case", and
unknown units. Rows whose meaning lives in the note are covered by a reviewed table
(`CURATED_RULES`) that cites its cell and applies only when the row's name still matches;
otherwise the parser's reading is used and `curated_entry_unmatched` is reported. Every rule
stores `pricing_status` (`priced`, `tiered`, `free`, `unpriced_vendor_review`,
`not_applicable_canada`, `conflict`), `scope` (per-kg surcharges default to the **full carton**,
as the sheet's footer says), and `applies_to_canada` (false for the whole USA sea section and
for the two plants rows).
**Why.** Issue register H-01 to H-03, H-08, H-09: the prototype's regex priced `10.000/1kg` as
1 VND and estimates as fixed amounts. A quotation carrying an `unpriced_vendor_review` or
`conflict` rule cannot be finalised; that refusal is the point.
**Needs business confirmation.** V-10 to V-14 in `docs/b2c_merge/05_OPEN_DECISIONS.md`.
**Reversible.** Yes: a re-import after the table changes produces a new version.

### DEC-0170 — Beyond code 180 is stored as `no_rate`

**Decision.** `tariff_beyond_rates` carries one row per code that appears in the postal code
list, including code 180 with `status = no_rate` and NULL amounts (123 far-north postal
codes in NU, NT, northern QC and ON).
**Why.** The workbook has no rate row for 180 anywhere, and its own calculator prices those
addresses at CAD 0 through an `IFERROR(…, 0)`. Zero is not the vendor's price; it is the
absence of one, and the pricing engine must refuse to finalise rather than charge nothing
(issue H-07, question V-05).
**Reversible.** Yes.

### DEC-0171 — Exchange rates: one bank, both rates, append-only snapshots, a worker process

**Decision.** `app/services/fx_service.py` reads Vietcombank's public XML at a URL fixed in
code, records **cash buying**, transfer buying and **selling** for CAD in `fx_rate_snapshots`
(append-only, with the bank's own stamp, the retrieval time and the response digest) and
every attempt in `fx_sync_attempts`. A response missing either rate, outside 1,000–100,000
VND/CAD, or with selling not above cash buying is a recorded failure, never a substitute
number. The fetch is HTTPS to the bank's exact host only, follows no redirect, and carries
no credential. `app/workers/fx_worker.py` runs it (`--once` or continuous, default every
300 s); the request process never fetches inline. A snapshot older than
`FX_STALE_AFTER_MINUTES` (default 1,440) is reported `stale`.
**Why.** Handoff owner decision 10 (cost at cash buying, customer surcharge at selling) and
§6 (immutable snapshots, explicit stale and outage states); directive v2.0 §12 (no other
provider's rate on failure). The v1.5 server read only the buying rate and polled only while a
desktop window was open (issue M-05).
**Not done.** No worker is scheduled or supervised; whether and where it runs is an
operations decision for `docs/OPERATIONS.md`. No request has been made to the bank by the
test suite or by this build's validation.
**Reversible.** Yes.

### DEC-0172 — `tariff:read` for Operations and Admin; `tariff:manage` for Admin only

**Decision.** Two permissions. Reading tariff versions, rules, accessorials and the
exchange-rate state is `tariff:read`, held by Operations and Admin. Importing a workbook and
activating a version is `tariff:manage`, held by Admin alone. Marketing and the read-only
manager hold neither. Routes live only on the staff router; `tests/test_tariff_import.py`
asserts that no tariff or exchange-rate field name appears in a public or Customer Account
schema and that no such route is mounted outside `/api/v1/tariffs` and `/api/v1/fx`.
**Why.** Vendor prices are strictly internal (directive v2.1 §1). Operations will price
shipments in the Unified Workspace (13D), so it must read the tariff. Today
`financial_cost:read` is Admin's alone; this widens vendor-price visibility to Operations
deliberately and visibly.
**Needs business confirmation.** D-06 / D-14 in `docs/b2c_merge/05_OPEN_DECISIONS.md`: who
may see vendor cost, confirm a selling rate, and override it.
**Reversible.** Yes: one set membership.

### DEC-0173 — openpyxl is added; the test fixture is a sanitized copy of the vendor workbook

**Decision.** `openpyxl` 3.1.5 (MIT) joins the backend dependencies and the lock file. The
committed fixture `backend/tests/fixtures/kango_canada_rates_2026-10-12_sanitized.xlsx` is
produced by `scripts/sanitize_kango_workbook.py` from the vendor's original: the staff
directory sheet is removed and the corporate contact header cell is blanked; every rate,
zone, postal code and surcharge row is unchanged. `kango_reference_v15.json`, the prototype's
snapshot, is kept beside it as an independent regression oracle.
**Why.** The importer needs a real workbook to be tested against, and a file containing ten
named people's personal mobile numbers must not be copied to every clone of this repository.
**Reversible.** Yes.

### DEC-0174 — Customer public IDs are `STCA-000001`; issued `CUS-` identifiers are renamed and kept as aliases

**Decision.** `identifier_service.CUSTOMER_ID_PREFIX` is `STCA`. The counter and its six digits
are unchanged, so the sequence continues without a collision. Migration `a7c3e1d9b2f4` renames
every `customers.public_id` that starts with `CUS-` to `STCA-` plus the same digits and writes
one `customer_id_aliases` row per renamed customer (`reason = prefix_change_2026_10_19`), so a
former identifier typed into any lookup still resolves through the existing alias path
(`customer_service.get_customer_by_public_id`). The downgrade restores the former identifiers
from those alias rows and removes them. Aliases created earlier by merges are left exactly as
they were. Audit rows that quote a former identifier in their summary are history and are not
rewritten.
**Why.** OD-42 (Ben, 2026-10-19): the handoff's vocabulary and the staff's. Decided while no
production customer exists, which is the only time a rename is cheap. Six digits are kept
rather than the handoff's four because 9,999 customers is a ceiling this business can reach.
**Not changed.** The identifier's immutability from here on (CRM.md section 6); the Customer
Account identity prefix `CA-`; the Solaris shipment ID.
**Known overlap.** `STCA-000001` ends in `CA-000001`, the shape of a Customer Account identity
id. Any privacy scan that looks for an account id as a bare substring must anchor on a
non-letter before it (`test_merge_refusal_audit_privacy.py` does); staff should read the whole
prefix. The two sequences are independent, so the digits coincide only by chance.
**Side effect.** A pending Customer Account disclosure acknowledgement whose fingerprint
included the former identifier no longer matches; the approval recomputes it and the
reviewer acknowledges again, which is the behaviour that fingerprint exists for.
**Reversible.** Yes: the downgrade path, and one constant.

### DEC-0175 — Solaris services map to vendor products; air first, sea deferred

**Decision.** The pricing engine prices a **Solaris service** (Air Standard, Air Express) through
a per-tariff-version **mapping** to one vendor product per origin: Air Standard → `AIR-CAD`,
Air Express → `AIR-CAD EXPRESS`. Sea products stay imported but unmapped and unpriced; UPS has
no rate sheet on file. Customer documents carry the Solaris service name only.
**Why.** OD-43 (Ben, 2026-10-19). One place to change when a vendor or product changes, and
vendor product names never reach a customer (directive v2.1 sections 2 and 4).
**Needs business confirmation.** When Sea is enabled, which sea product (standard or insured)
each Solaris sea service maps to.
**Reversible.** Yes: mapping rows.

### DEC-0176 — Surcharge markup is per rule; default pass-through at the selling rate; negative margin is refused without a reason

**Decision.** Each surcharge rule carries a markup (pass-through, fixed CAD, or percent),
default pass-through at the bank's selling rate. The engine shows cost, charge and margin per
fee line and refuses to finalise a line whose margin is negative unless the staff member
overrides with a typed reason, which is audited. Real markups are set later in Settings.
**Why.** OD-44 (Ben, 2026-10-19). Pass-through at the selling rate with no markup bills every
surcharge below cost by the sell/cash-buy spread (issue register H-04); the directive forbids
inventing a margin, so the default loses visibly rather than silently.
**Reversible.** Yes: a setting per rule.

### DEC-0177 — Operations sees vendor cost, confirms the selling rate, and overrides it with a reason

**Decision.** The Operations role reads vendor cost and margin, confirms the default Air
Standard selling rate, and may set another rate or waive a surcharge by giving a reason;
every confirmation and override is an audited action with the actor. Admin reviews the audit
log; there is no approval queue. Marketing and the read-only manager read no vendor cost.
Phase 13A's `tariff:read` for Operations (DEC-0172) is thereby confirmed; the pricing
permissions of Phase 13C follow this split.
**Why.** OD-45 (Ben, 2026-10-19): a small team where the person pricing the shipment decides
and is accountable.
**Reversible.** Yes: role set membership.

### DEC-0178 — The consolidation is its own entity, air only, with a Solaris reference and a state machine

**Decision.** `consolidations` (`MST-000001`, from its own counter) is the handoff's master:
one vendor booking (Kango), a Solaris service (`air_standard` or `air_express` today; `sea`
and `ups` are named but unmapped), an origin depot (HCM or HAN), the vendor's own booking
reference, master weight and dimensions, carton count, and the dates that matter (cutoff,
hand-over at the Vietnam depot, booking). States: `open` (accepts members) → `booked`
(handed to the vendor; members and weights frozen; chargeable weight stored) → `completed`,
or `cancelled` (every member released). `consolidation_memberships` links member shipments;
a partial unique index keeps one *active* membership per shipment while removed ones stay as
history with a reason. Only confirmed, live, Vietnam → Canada shipments may join.
**Why.** Handoff section 2 and owner decision 6: one master booking priced on its full
chargeable weight, allocated to children. OD-43 fixes the scope to air. The Solaris reference
is what staff and later documents quote; the vendor's number is internal (directive v2.1 §5).
**Who reads it.** A consolidation carries the vendor's reference, the vendor product and the
weight the vendor bills, so reading one needs `tariff:read` as well as `shipment:read`
(Operations and Admin, DEC-0172); Marketing and the read-only manager read shipments but
not consolidations, and the shipment page shows them the master's Solaris reference
without the vendor's number. A booked consolidation still accepts a corrected vendor
reference and notes; its weights, service and origin are frozen.
**Deletion behaviour.** A consolidation's memberships and event links cascade with it; its
user and tariff references are set to NULL; a mapping row cascades with its tariff version
and product; a vendor with consolidations cannot be deleted.
**Reversible.** Yes: migration `b8d4f2a6c1e7` is additive; its downgrade drops six tables.

### DEC-0179 — Booking a consolidation resolves the vendor product through the active tariff's mapping and stores the chargeable weight

**Decision.** `service_vendor_products` rows are written by the tariff importer for every
version it imports: Air Standard → `AIR-CAD`, Air Express → `AIR-CAD EXPRESS`, per origin
(`app/pricing/service_mapping.py`). Booking looks up the active version's row for the
consolidation's service and origin, copies the product's dimensional divisor, computes the
chargeable weight (`app/pricing/chargeable_weight.py`: greater of actual and L×W×H/divisor;
above 20.5 kg rounded up to the whole kilogram as the rate sheet says; below it, to the next
0.5 kg band as a **recorded convention**, V-01) and stores divisor, volumetric and chargeable
weight on the consolidation. No active tariff, or an unmapped service, refuses with the reason.
**Why.** OD-43 and DEC-0175. The figure a quotation later prices against must be reproducible
after the tariff moves, so it is stored at booking, with the divisor that produced it.
**Needs business confirmation.** V-01 (band semantics below 20.5 kg), V-04 (divisor per piece
or per shipment envelope). The engine will label figures that depended on the convention
provisional.
**Reversible.** Yes.

### DEC-0180 — A master milestone is one event per member, through the event service, marked by a link row, never repeated

**Decision.** `consolidation_service.record_master_event` records the milestone on every
active member through `event_service.record_event`, so every rule that function holds (no
future time, delivery only by the recipient event, public wording needs its flag, a
cancelled booking refuses) holds for inherited events; each created event gets a
`consolidation_event_links` row. A repeat is refused and reported as a duplicate: with a
stated time, the same type **and** time; with no stated time (the staff clicked the
milestone again), the same type. Cancelling a member's booking releases it from the
consolidation in any state, so a cancelled shipment is never reported as refused on later
milestones; booking refuses a member that is no longer confirmed. A member the event service
refuses is reported with the reason, and the others still receive the milestone. Package
targets are refused on the master: a package event belongs on the shipment.
**Why.** Directive v2.1 §5 ("milestones can be inherited by the linked customer shipments")
and acceptance tests 2 and 8. One write path for events is the property Phase 2 built;
inheriting through it keeps it.
**Reversible.** Yes.

### DEC-0181 — The payer and the inherited-event mark are link tables, not columns on existing tables

**Decision.** `shipment_payers` (one optional row per shipment: the paying customer when it is
not the booking customer) and `consolidation_event_links` (one row per inherited event)
rather than `shipments.payer_customer_id` and `shipment_events.consolidation_id`.
**Why.** The first draft added the two columns. A foreign-key column cannot be added to an
existing SQLite table in place, so Alembic rebuilt `shipments`; with `PRAGMA foreign_keys`
on for every connection, dropping the original cascaded into every child row and the Phase
4A populated-database test lost the shipment's packages. The pragma cannot be turned off
inside the transaction Alembic runs in (the Phase 10 downgrade met the same wall). New tables
carry the same facts and touch nothing existing in either direction; the Phase 4A column
guard stays unchanged.
**Reversible.** Yes.

### DEC-0182 — Commodity items are their own rows, numbered once, deactivated rather than deleted

**Decision.** `shipment_items`: description, quantity and unit (`piece`, `pair`, `box`,
`bottle`, `set`, `kg`, `carton`, `other`), optional weight, declared value and package. The
sequence number is never reused; removing an item deactivates it. Items are editable while the
shipment is a draft or confirmed, read-only once cancelled. Nothing charges a fee from an item:
Phase 13C attaches surcharge rules to items explicitly through the fee picker.
**Why.** Handoff owner decision 4 (unlimited items; staff choose the fee, nothing is charged
from a keyword) and the issue register's M-04. A quotation that referenced an item must keep
its meaning after the item is removed.
**Reversible.** Yes.

### DEC-0183 — Captured e-mail files survive a shared microsecond

**Decision.** `CaptureEmailTransport._write` appends a counter suffix (`-2`, `-3`, …) when the
file it is about to write already exists. The name is still the stamp, the template key and
twenty-four characters of address.
**Why.** `test_two_addresses_sharing_a_prefix_do_not_collide` relied on the microsecond stamp
alone and failed twice during the Phase 13B validation, both times while two test suites ran
on one machine: two sends landed in the same microsecond and the second file replaced the
first. A capture directory exists to hold every message that was sent; losing one silently is
the one thing it must not do. Found by a full-suite run, not by 13B's own tests; recorded here
because the fix is outside 13B's scope.
**Reversible.** Yes.

### DEC-0184 — The air pricing engine is pure, Decimal throughout, and every split is a largest-remainder allocation

**Decision.** `app/pricing/engine.py` takes dataclasses and returns dataclasses: no database, no
clock, no settings. Money and weights are `Decimal`; an amount is rounded to the cent only where
it is produced, and every split (base freight to members, a fee's cost to members, a customer
surcharge to triggers, the CAD conversion of each) is a largest-remainder allocation at one cent,
so the parts always sum to the whole and no part is more than a cent from its exact share. Ties
go to the earlier member.
**Why.** Handoff section 5: "reconcile exactly with deterministic residual cent handling". A pure
engine is testable from the specification alone; the independent golden tests
(`tests/test_pricing_golden.py`, written by a separate agent from the handoff's acceptance cases
without reading the developer's tests) exercise it that way.
**Reversible.** Yes.

### DEC-0185 — Vendor cost is zoned at the delivery point L5A 3K6 (OD-46)

**Decision.** The zone for vendor base freight comes from one postal code,
`pricing_settings.vendor_delivery_postal_code`, default `L5A3K6`: Ground zone 2, Express zone 3,
not beyond-area. No customer address is read for vendor cost. Should the setting ever name a
beyond-area code, a priced code is reported as provisional (the per-piece beyond fee needs
per-carton weights) and an unrated one (code 180) blocks.
**Why.** OD-46: Kango always delivers to Soleil at L5A 3K6. It also closes V-05 for vendor cost.
**Reversible.** Yes: one setting.

### DEC-0186 — Which surcharges are charged once per consolidation, and how cost and revenue are split

**Decision.** A rule whose effective scope is the full carton, the full master or the whole
shipment (with a per-kilogram or per-shipment basis) is **one vendor charge per consolidation**,
at the master's chargeable weight, however many members trigger it (SC-09). Any other rule is a
direct charge on its own line (quantity × price; tiered by the carton weight entered; compound =
tier + per-unit × quantity). Cost: base freight by member chargeable-weight share; a master-wide
fee — one member: all of it; one trigger among several: the configured trigger share (2/3) to
the trigger and the rest equally to the others; several triggers: by weight among the triggers;
a direct fee to its own shipment. Revenue: the fee converted at the bank's selling rate, plus the
rule's markup, billed only to triggers (one trigger: all; several: by weight). Non-triggers are
never billed. A member's billable weight is its packages' Σ max(actual, volumetric), rounded by
the vendor's rule.
**Recorded conventions (provisional, flagged on every estimate where they apply).** With more
than one carton, a full-carton rule uses the master's weight (per-carton weights are not
recorded); the per-carton minimum fee on lots over 21 kg is not evaluated for the same reason;
the customer's billable weight uses the vendor's rounding (whole kilogram above 20.5 kg, half
kilogram below, V-01). Tier bounds that overlap (nail polish at 5 and 22 kg) go to the lower tier.
**Why.** Handoff section 5 Examples A and B, SC-03, SC-05, SC-06, SC-08, SC-09.
**Needs business confirmation.** V-20 (new, below): SC-01 charges eyelashes on the item's 1 kg,
while the vendor's sheet says per-kilogram surcharges apply to the full carton. The engine follows
the tariff's stored scope; a per-rule `scope_override` (`item_weight`) lets the owner choose
SC-01's reading for any rule without a release.
**Reversible.** Yes.

### DEC-0187 — Pharmaceuticals and every unpriced rule block finalisation (OD-47)

**Decision.** A fee line on a rule whose pricing status is `conflict` (pharmaceuticals, both
origins) or `unpriced_vendor_review` gets no price and a blocking issue naming the open vendor
question. Finalisation is refused for **every** member of the consolidation while any blocking
issue exists, because a master-wide rule moves cost onto every member through the trigger split.
A Canada-excluded rule cannot be attached at all.
**Why.** OD-47: "block finalising on any pharma line, no guessed price"; the same rule protects
every case-by-case rule.
**Reversible.** Yes.

### DEC-0188 — The $18/kg default and the two-thirds share are settings, flagged until the owner confirms (OD-48)

**Decision.** `pricing_settings` holds the Air Standard default rate (CAD 18.00/kg), an optional
Air Express default (none), the trigger share as a fraction (2/3) and
`defaults_owner_confirmed` (false). While false, every estimate and quote carries the provisional
flag `pricing_defaults_pending_owner_confirmation`. Administrators change these values
(`settings:manage`); finalised quotes keep the values they were priced with.
**Why.** OD-48, recorded open with that disposition by the owner's instruction.
**Reversible.** Yes.

### DEC-0189 — A quote is a versioned record with one open draft, a revocable rate confirmation, and a frozen snapshot

**Decision.** `quote_versions`: one open draft per shipment (partial unique index); re-pricing
rewrites it. The selling rate starts at the service default and is unconfirmed; Operations
confirms it, and any other rate needs a typed reason (OD-45). The draft stores a fingerprint of
its inputs (billable weight, the shipment's fee lines, the triggers it shares a master-wide fee
with, service, consolidation); a change to any of them revokes the confirmation (SC-07). A new
exchange-rate reading does not revoke it but is re-applied at finalisation. Finalising re-prices
and refuses while the confirmation is missing, any blocking issue exists, or a surcharge line
bills below its cost without a reason (OD-44). A finalised version is frozen with its full
snapshot (estimate, figures, tariff version, FX snapshot) and supersedes the previous finalised
one; `quote_versions.shipment_id` is RESTRICT. A shipment must ride in a consolidation to be
quoted, because its cost is a share of one.
**Why.** SC-07, SC-10, SC-16; OD-44, OD-45.
**Not done.** The customer-facing quote document (13D) is built from its own allowlisted schema;
lines with `is_trigger = false` carry an internal cost share only and must never print.
**Reversible.** Yes.

### DEC-0190 — Fee lines and surcharge policies are keyed by the vendor's section and row number

**Decision.** `shipment_fee_lines` and `surcharge_rule_policies` name a rule by (section, row),
not by a tariff-version row id, so a fee line and a markup survive a new tariff version; a rule
missing from the active version blocks pricing. One active fee line per item and rule (partial
unique index). Markups: `pass_through` (default), `fixed_cad` (added once to the vendor fee
instance before it is split among triggers) or `percent`.
**Why.** OD-44 (markups set later in Settings) and handoff owner decision 4 (fees attached
explicitly to items).
**Reversible.** Yes.

### DEC-0191 — One weight-rounding rule for every weight; finer inputs go to 0.1 kg first (OD-50, OD-51)

**Decision.** `chargeable_weight.round_chargeable` applies the owner's rule to the master, each
member, each recorded carton and each per-kilogram surcharge weight, above 20.5 kg too:
x.0–x.1 → x.0, x.2–x.6 → x.5, x.7–x.9 → the next whole kilogram. A weight given to more than one
decimal is first rounded to 0.1 kg half up (5.15 → 5.2 → 5.5), and nothing rounds below 0.5 kg.
Per-kg bands are chosen by the last band whose lower bound the rounded weight reaches (44.5 kg is
in 21–44); no separate minimum bill. This **supersedes** the half-kilogram convention and its
provisional flags (DEC-0186 in part).
**Why.** OD-50, OD-51. The tenths step and the 0.5 kg floor are this phase's reading where the
owner's examples stop; both are covered by golden tests.
**Reversible.** Yes.

### DEC-0192 — Surcharge weight tiers read the carton weight to 0.1 kg, not the half-kilogram rounding

**Decision.** Tiered surcharges (nail polish, perfume, batteries) look up their tier on the
carton weight rounded to 0.1 kg, with no half-kilogram step. A weight equal to a tier's upper
bound is in that tier; tiers do not overlap. Above the top tier, nail polish and perfume use the
top tier (OD-57) and batteries need the vendor's quoted price on the line (OD-59).
**Why.** The owner puts 3.6 kg in the 4–8 kg battery group (OD-59); the half-kilogram rule would
round 3.6 to 3.5 and put it in the lower group. Reading tiers to 0.1 kg honours both answers.
**Reversible.** Yes.

### DEC-0193 — Manual-quote rules price at the vendor's quote, else the file's minimum, flagged (OD-56)

**Decision.** New pricing status `manual_quote` for HCM air rows 4, 5, 10, 13, 27, 31, 33, 34
and 45, carrying the file's minimum as the unit price. A fee line may carry
`manual_unit_price_vnd`; without it the minimum is used and the estimate carries
`manual_quote_prefilled_minimum` (provisional, not blocking). The same field holds the vendor's
price for a battery carton above 8 kg. The manual price is part of the quote's input fingerprint,
so entering it revokes a rate confirmation.
**Why.** OD-56, OD-59.
**Reversible.** Yes.

### DEC-0194 — The under-12 kg piece fee is counted from recorded master cartons (OD-62)

**Decision.** New table `consolidation_cartons` (weight, optional dimensions), replaced as a set
through `PATCH /api/v1/consolidations/{id}/cartons` (audited `consolidation.cartons_replace`).
On a master of 21 kg and over, each carton whose rounded max(actual, volumetric / 6000) is under
12 kg adds the product's piece fee (300,000 VND Ground, 700,000 Express) to the master's base
cost, shared among members by chargeable weight. Without carton rows, a multi-carton master stays
flagged `piece_minimum_not_evaluated`; a carton list that disagrees with the master's carton
count is flagged `carton_count_mismatch` and the recorded cartons are used.
**Why.** OD-62. A new table rather than a column on `consolidations` (DEC-0181).
**Reversible.** Yes.

### DEC-0195 — Air only; pharmaceuticals priced; the OD-47 block removed (OD-49, OD-58)

**Decision.** `add_fee_line` accepts only the HCM air and Hà Nội air sections; a sea section is a
validation error. Pharmaceuticals (HCM air row 39, Hà Nội air row 1) are priced at 200,000 VND/kg
and charged like any per-kilogram surcharge. This **supersedes DEC-0187** (pharmaceutical block).
**Why.** OD-49, OD-58.
**Reversible.** Yes.

### DEC-0196 — Review hardening: tariff pinned at booking, wider confirmation fingerprint, audited drafts

**Decision.** From the independent review of Phase 13C: (1) a booked consolidation is priced at
the tariff product and version it was booked under, never a newer active version; (2) the rate
confirmation fingerprint also covers the default rate, the tariff version, the master's
chargeable weight, and for every fee the shipment triggers its vendor fee, markup, scope and the
triggers' weights, so a policy, default-rate or master-weight change revokes the confirmation;
an unconfirmed draft without an override follows the current default rate; (3) opening a draft
and revoking a confirmation are audited (`quote.draft_open`, `quote.confirmation_revoked`);
(4) a policy may name only an air rule in the active tariff, and a tiered or manual-quote rule
cannot be made master-wide; (5) a vendor price is accepted only on a manual-quote rule or a
battery carton above 8 kg; (6) a per-carton tiered line charges each of its `quantity` cartons;
(7) cartons change only on an open or booked master; (8) per-bill prices are kept to the cent
(the workbook stores some as floats).
**Why.** Review findings 1–8; each has a regression test in `tests/test_quotes.py` or
`tests/test_pricing_golden.py`.
**Reversible.** Yes.

### DEC-0197 — The workspace is one page per master, and it does no pricing arithmetic

**Decision.** Phase 13D adds `/workspace` (the masters) and `/workspace/:consolidationId` (one
master): master header and weights, cartons, customer cards (items, the fees on each item, the
customer's cost share, the quote), and a vendor-cost panel beside them. Every figure is what the
Phase 13C API returned; the screen formats it and never computes a price, a share or a margin.
All of a master's queries share one key prefix and every write invalidates the whole prefix,
because one fee on one customer can move every other customer's share. The navigation entry is
shown to roles holding `tariff:read` (Operations and Admin); the routes and the API refuse
independently. Air only (OD-49): the new-master form offers Air Standard and Air Express from
HCM or HAN, and the fee list searches only the master's own air section. The pending owner
settings (OD-48 defaults, markups, the pharmaceutical weight basis) are shown as a banner and as
the engine's provisional notes; none is hard-coded in the screen.
**Why.** The owner-approved interaction (`06_MERGE_PLAN.md`, 13D) on the 13C routes.
**Reversible.** Yes.

### DEC-0198 — The fee list is searched accent-insensitively in the browser

**Decision.** The fee picker loads the master's whole air section once (a few dozen rules) and
filters it locally on accent-folded, lower-case text, so "dong ho" finds "Đồng hồ thường". The
server's `q` parameter is a plain substring and is not used by the picker.
**Why.** The vendor writes some names with diacritics and some without, and staff type either
way; the first live run of the screen found nothing for "dong ho".
**Reversible.** Yes.

### DEC-0199 — Demo pricing data comes from the sanitized fixture and a labelled demo exchange rate

**Decision.** `python -m app.seed_pricing` (guarded exactly like `app.seed`: refused in
production and wherever demo seeding is off) activates the sanitized Kango tariff fixture and
records a fixed exchange-rate reading through the real Vietcombank parser with source
`demo://fixture`; `--with-master` adds an open Air Standard master with three eligible members;
`--refresh-fx` adds a new reading. Nothing calls the bank or the vendor. The end-to-end harness
runs it after `app.seed`. `scripts/workspace_demo_env.py` builds a separate database for trying
the screens, `data/workspace_demo/solaris_workspace.demo.db`, refusing production, the
development database, the UAT directory and the current `DATABASE_URL`, and never reading `.env`.
**Why.** The owner asked for a local test login to try the screens, with test data only.
**Reversible.** Yes.

### DEC-0200 — Workspace review hardening: confirm what is shown, ask only what the engine reads

**Decision.** From the independent review of Phase 13D: (1) a blank rate box confirms the rate
the draft carries, override and its reason included, never the default behind the user's back;
(2) the fee picker asks for a weight whenever the engine reads the line's kilograms (tiered, or
per-kg not charged on the whole master or carton), hides quantity for per-kg and per-shipment
rules, and offers a vendor price only for a manual quote or a carton above a top tier the rule
does not continue (the API now returns `above_top_tier`); fields that are hidden are not sent;
(3) the OD-48 banner reads the rate and share from the settings rather than quoting them;
(4) the exchange-rate API returns `source_url` and `is_demo`, the screen labels a demo reading,
and `app.seed_pricing` refuses any database not named `.e2e.db` or `.demo.db`; (5) the carton
editor cannot open over cartons that have not loaded, and a carton with dimensions but no weight
is an error; (6) a quote whose saved cost differs from the live estimate says it is out of date;
(7) an emptied master field is cleared rather than silently kept; (8) the shared `Button` keeps
its loading lock even when a caller passes `disabled`; (9) confirm and finalise are hidden on a
closed master; repeated buttons carry the customer, item or fee in their accessible name.
**Not done.** Removing a customer from a master, and paging past 100 masters, are left to a
later phase.
**Reversible.** Yes.

### DEC-0201 — Invoices come only from a finalised quote; payments are CAD with no credit

**Decision.** An invoice (`INV-000001`) is issued from the shipment's latest **finalised** quote
version and copies only its customer revenue lines; the payer is the shipment's recorded payer
or else its customer; one live invoice per shipment (partial unique index); numbers are never
reused, a mistake is a reasoned void and a new invoice. No tax is computed while D-11 is open
(OD-64): `tax_cad` is empty and the documents say "under review" and "draft for review". A
payment is CAD only (OD-66), dated the day the money moved, never more than the balance, so no
credit is kept on account (OD-68), and gets a receipt `RCT-000001`; a receipt exists only for a
recorded payment. A refund returns money against one payment and never more than it brought;
refunds and voids are Admin's (`financial:adjust`, OD-69) and need a reason. The shipment's
existing `payment_state` follows its invoice. The customer documents are built from explicit
allowlist schemas (`InvoiceDocumentOut`, `ReceiptDocumentOut`) that carry no cost, margin,
exchange rate, vendor or master reference.
**Why.** Handoff sections 3, 9 and SC-15: quote, invoice and receipt are separate documents;
customer documents carry revenue only.
**Reversible.** Yes.

### DEC-0202 — A vendor bill is reconciled to the expected cost and split like the estimate

**Decision.** A booked master's vendor bill (`VB-000001`, one live per master) is entered in VND
or CAD beside the engine's expected cost at that moment; a VND bill is put into CAD at the
latest cash-buying snapshot, frozen on the bill (OD-67); a CAD bill is never converted twice.
Any difference from the expected cost needs a reason before approval. Approval splits each line
onto the master's shipments in cents (largest remainder): base freight, the piece fee and
unkeyed lines by chargeable-weight share, a surcharge line keyed to an estimate fee by that
fee's own cost split (so the two-thirds rule carries through). Profitability matches each
invoiced shipment's revenue to its own share of the approved bill (or its quote's estimate until
then); bill shares of shipments not yet invoiced are shown as unmatched cost and kept out of
profit.
**Why.** Handoff sections 5 and 9, SC-14; the first live run showed a whole master's bill set
against one customer's revenue.
**Reversible.** Yes.

### DEC-0203 — Revenue months lock at M+7; late figures are next-month adjustments

**Decision.** The revenue month of an invoice or bill is the master's Vietnam hand-in month
(then its booking date). A month locks seven days after it ends, at 00:00 UTC. An invoice or a
bill whose month is locked is booked in the first open month after it, flagged as an
adjustment; a payment dated in a locked month, a void of an invoice in one, or the void of an
approved bill in one, is refused. A locked month may be closed (`period_closes`, versioned, with
the profitability figures frozen; a closed month's report answers from that snapshot); Admin may
reopen it with a reason; every step is audited.
**Why.** Handoff section 9 and owner decision 12.
**Reversible.** Yes.

### DEC-0204 — Reading settings never writes; heavy write routes re-run whole on a SQLite lock

**Decision.** The pricing and finance settings readers return unsaved defaults when no row
exists; the row is created only when an administrator saves. The write routes for pricing and
finance run their work through `run_unit_with_retry`, which on `database is locked` rolls the
whole unit back and runs it again from the start (up to four times), so nothing half-done is
committed.
**Why.** The first live run on a fresh database failed with `database is locked`: concurrent
screen loads raced to create the settings rows, and, with explicit transactions (DEC-0108), a
read-heavy write loses its snapshot whenever another request commits (every signed-in request
records its session's last-seen time); `commit_with_retry` cannot recover a failed flush.
**Reversible.** Yes.

### DEC-0205 — The 13D gaps: remove a customer from an open master; page the masters

**Decision.** A customer card on an open master offers "Remove from master" with a required
reason (the existing audited route); the masters list pages 50 at a time.
**Why.** The two gaps left open by DEC-0200.
**Reversible.** Yes.

### DEC-0206 — Finance review hardening

**Decision.** From the independent review of Phase 13E: (1) a bill line keyed to a surcharge is
split by the engine's own rule recomputed on the billed amount (a direct fee to its shipment, a
master-wide fee by the trigger share), so an unpriced or waived fee never spreads across other
customers; a key no longer on the estimate refuses approval; zero total weight is refused, not a
crash; (2) a master's invoices and bill share one revenue month (the earliest non-adjustment
period already booked for it), so revenue meets its own cost even when the hand-in date is
recorded after the invoice; (3) finance CSV cells are escaped against formula injection
(DEC-0081) and the export audit runs as its own retried unit; (4) month routes accept only
`YYYY-MM` and answer from the month's own row; (5) payment, bill and paid dates are taken as
naive UTC from any ISO form and are never in the future; (6) Admin may void a bill marked paid
by mistake, with a reason; (7) the customer documents no longer touch the invoice while reading;
(8) closing a month takes a second click; the refund form starts from what is left to refund;
the locked-month payment message no longer suggests re-dating a payment.
**Why.** Review findings 1–10; regression tests in `tests/test_finance.py`.
**Reversible.** Yes.

### DEC-0207 — Vendor-bill schemas live apart from the customer documents; finance tables scroll by keyboard

**Decision.** The vendor-bill request and response schemas moved to `app/schemas/vendor_bills.py`
(listed with the other staff-only vendor modules), so `app/schemas/finance.py`, which holds the
customer invoice and receipt documents, stays under the guard that no general or
customer-facing schema carries a vendor or exchange-rate field. Every finance table's scroll
container is a named, keyboard-focusable region, because at phone width it scrolls sideways.
**Why.** The full backend suite's vocabulary guard and the 375 px accessibility audit, both on
the first full run of Phase 13E.
**Reversible.** Yes.

### DEC-0208 — The owner's finance and pricing answers of 2026-10-20 in force

**Decision.** (1) GST/HST is chosen by staff per invoice from 0, 5 and 13 % (default 0 %,
an international move), computed to the cent and added to the total; invoices and receipts
carry Soleil Global Transportation Inc., Solaris Express, business number 795093756RT0001 and
2446 Cawthra Road B1U8, Mississauga ON L5A 3K6, and no longer say "draft" (OD-64). (2) Invoices
are due on issue (OD-65). (3) A VND payment is converted at Vietcombank's selling rate of the
reading in force on the invoice date, kept in the new `payment_conversions` table and printed
on the receipt (OD-66). (4) A VND vendor bill is converted at the middle -- transfer -- rate of
the reading in force on the bill date (OD-67; "middle" read as the middle column). (5) Operations
holds `financial:adjust` (OD-69). (6) The $18/kg default and the two-thirds rule are confirmed
(OD-48): still settings, no pending flag by default. (7) Pharmaceuticals are charged on the
item's own kilograms (OD-70); other per-kilogram rules still follow the sheet footer.
**Why.** OD-48, OD-64 to OD-67, OD-69, OD-70.
**Reversible.** Yes.

### DEC-0209 — Milestone email: an outbox with a dedup key, published milestones only, test transports only

**Decision.** A **published** event of type received at Solaris, departed origin or in transit,
out for delivery, or delivered (to the recipient or a collection point) queues one row in
`notification_outbox` per shipment, milestone and template version (unique `dedup_key`), so a
repeat, a correction or a master milestone fanned out to members notifies once. The request that
recorded the milestone dispatches right after its own commit, in a separate retried unit that can
never undo the milestone; `python -m app.workers.notification_worker` picks up anything left
queued or failed (three attempts). Dispatch skips, and records why: no address (`no_email`), the
customer turned that milestone off (`opted_out`; no saved choice means on), or the address is
suppressed (`suppressed`). For milestone email the owner's instruction of 2026-10-20 ("respect
suppressions") supersedes the 2026-10-16 rule that a suppression blocks marketing only; account
email is unchanged. The message goes through the account email seam, whose only transports are
null and capture, so nothing reaches a customer (OD-72, test capture only). Language: English for
a customer who chose English, Vietnamese otherwise (OD-71). The outbox stores no address and no
body; templates take only the shipment reference and its public tracking link. Customers read
their choices and history at `/api/v1/account/notifications`; staff read the outbox and retry a
failed row (`tracking:write`), and may change a customer's choices on their behalf.
**Why.** OD-72; directive v2.1 test 8 (a duplicate milestone gives one event and one notification).
**Not done.** No production email provider (OD-34); no mobile push (later, OD-72).
**Reversible.** Yes.

### DEC-0210 — Notification and finance review hardening (13F review)

**Decision.** (1) "Delivered" is notified only when the shipment as a whole is delivered; a
collection-point handover notifies nothing; a milestone behind the shipment's current status
notifies nothing. (2) Voiding an event withdraws its unsent notification (`skipped`/`voided`)
and frees the dedup key, so the corrected milestone still notifies; dispatch re-checks that the
event is live and published. (3) Dispatch is claim (`sending`, committed), send outside any
retried unit, record in its own unit, so a SQLite lock cannot send a message twice; one row's
fault is recorded on that row and never blocks the rest; a claim older than ten minutes is
retaken. (4) The language is the one chosen in the customer's account, then English for an
English customer record, else Vietnamese; account email defaults to Vietnamese and serves
`vi,en` (OD-71). (5) The customer is told "sent" only for a message the capture transport took;
the null transport's `recorded` and an exhausted failure read "not sent". (6) Profitability
revenue excludes GST/HST. (7) A VND payment's rate is frozen per invoice at its first VND
payment, read for the invoice date in the business time zone (America/Toronto), refused when the
nearest reading is more than four days old; a VND amount that covers the balance settles it
exactly. (8) The email footer no longer assumes an account; staff preference input is strict;
the payment audit carries the VND figures.
**Not done.** Carrier-reported events notify only once staff publish them (the published-only
rule); existing databases keep `defaults_owner_confirmed = false` until an administrator ticks it
(no data is migrated).
**Why.** Independent review of Phase 13F and the owner-answer commit.
**Reversible.** Yes.

### DEC-0211 — The Customer Account is Vietnamese first, with an English switch and no stored choice

**Decision.** The Customer Account has its own bilingual catalogue (`src/account/i18n/en.js`,
`vi.js`) and provider. It opens in Vietnamese; a signed-in customer's chosen language (`vi` or
`en`) applies at sign-in; a "Tiếng Việt / English" switch on every screen overrides it for the
page view. The choice is held in memory only -- nothing is written to local or session storage,
which the account's security tests forbid. `VITE_ACCOUNT_DEFAULT_LOCALE` exists so the existing
English-worded test suites run in English; a production build without it is Vietnamese.
Registration sends the screen language; the account serves `vi,en` and defaults to Vietnamese;
account emails have a Vietnamese catalogue. Supersedes OD-39 (OD-71). The Vietnamese is a
working translation awaiting review by Vietnamese-speaking staff; server messages still arrive
in English.
**Why.** OD-71.
**Reversible.** Yes.

### DEC-0212 — One FX rule both ways, and a 2 % default markup (owner correction, 2026-10-20)

**Decision.** VND to CAD uses Vietcombank's buy rate (first column); CAD to VND uses its sell
rate (last column). The pricing engine converts a vendor fee's cost and the customer surcharge
for it at the buy rate, so a pass-through surcharge recovers exactly its cost; a VND vendor bill
converts at the buy rate of the bill date, frozen on the bill (supersedes OD-67's middle rate). A
CAD invoice paid in VND is a CAD-to-VND conversion and stays at the sell rate of the invoice
date (OD-66's result, now under OD-73). A surcharge rule with no policy of its own carries a
configurable default markup, 2 % (`markup_defaults`, a new table; readers return the unsaved
default and never write); a per-rule policy still overrides it, and a negative margin is still
refused without a reason. Quotes and bills already finalised keep their frozen figures.
A rule policy that names no markup (`default`, e.g. a scope-only override) inherits the
default markup. The default is one row (id 1), rounded half up to cents, at most 100. Every
"on the date" rate (VND payments and VND bills) is the reading in force at the end of that day
in the business's time zone (America/Toronto), refused when older than four days. A bill
entered before this change keeps the rate frozen on it (test data only so far).
**Why.** OD-73, OD-74 (Ben's correction of 2026-10-20 16:23).
**Reversible.** Yes: the default is a setting; the rate columns are one line each.

### DEC-0213 — Customer quote acceptance: staff send a frozen, customer-safe offer; the customer answers once

**Decision.** Staff send a finalised quote to its customer (OD-77, D-08); the customer accepts
or declines it in the Customer Account. A new table, `quote_offers` (migration
`b7d2e9a4c1f6`; nothing existing altered, DEC-0181), holds one offer per quote version, ever,
and at most one `sent` offer per shipment (partial unique index). **Sending** needs the
shipment's latest quote version to be `finalized` (an open draft after it must be finalised
first) and a customer on the shipment; an older unanswered offer is withdrawn ("superseded by
vN"). The offer freezes a **customer view** read only from the customer side of the version:
the Solaris service label (OD-79), billable kilograms, selling rate per kilogram, base charge,
each surcharge line the customer pays (its customer-facing description and amount; zero-revenue
cost-share lines left out, as on the invoice), total, `CAD`, before tax (GST/HST is chosen per
invoice, OD-64). No cost, exchange rate, markup, margin, tariff or vendor product code, or
vendor name is read into it, and the account routes return nothing else (an allowlist schema).
**Answering**: only a `sent` offer, only by the active identity linked to the offer's customer
(the account's existing link policy), only while the offer's version is still the latest
finalised one; the change is a conditional update (`WHERE status = 'sent'`), so a second
answer, or two at once, is a 409. An offer of another customer, an unknown id and a malformed
id are one 404. Finalising a newer version withdraws a sent offer in the same transaction, and
acceptance re-checks the version anyway. The customer's decline reason is optional (400
characters); a staff withdrawal reason is required and is never shown to the customer.
**Email**: after the offer commits, one quote-sent email (`quote.sent.vi` / `quote.sent.en`, the
reference and the account's quotes link only, no amount) goes through the account email seam
(null and capture transports only), outside any retried unit, in the customer's language
(`notification_service.language_for`); an address on file is emailed even if suppressed (a
quote is operational email, DEC-0143; only milestone notifications respect suppressions, OD-72); the
outcome is recorded on the offer (`email_status`), and a failure never undoes the offer.
**Permissions**: send and withdraw need what finalising needs (`shipment:read`, `tariff:read`,
`financial:read`, `financial:write`: Operations and Admin); reading offers needs what reading a
quote needs. Audit actions `quote.sent`, `quote.withdrawn`, `quote.accepted`, `quote.declined`
(the last two carry the account reference as actor). Review fixes: an answer also requires the
offer's version to be the shipment's latest version of any status (an open draft: "being
updated", 409); a newer version finalised after an acceptance leaves the acceptance standing but
flags it (`superseded_by_version`, audit `quote.accepted_superseded`) for staff; a customer merge
or a change of the shipment's customer withdraws sent offers and re-points answered ones; the
account gets a customer-safe `closed_reason`; accept and decline have their own rate-limit
bucket. Air only.
**Why.** OD-77 (D-08), OD-79.
**Not done.** No automatic re-send of a failed quote email; no expiry date on an offer; an
accepted quote does not yet book or invoice anything by itself; the Vietnamese wording awaits
review by Vietnamese-speaking staff.
**Reversible.** Yes: one new table and additive routes.

### DEC-0214 — Vendor rate emails become draft tariffs; only a designated approver activates one

**Decision.** A vendor rate email (an `.eml` with the tariff workbook attached) is read into a
**draft** tariff version by the existing importer, with its provenance; only a designated
approver activates it (OD-76, D-12). Two new tables (migration `c5e8a1f3d7b9`; nothing existing
altered, DEC-0181): `tariff_intake_settings` (one row, id 1; readers return the unsaved
default and never write, DEC-0204) holds `approver_emails` (default the owner's address,
OD-76), `allowed_sender_domains` (default empty: every sender is held for review) and an
informational `mailbox_address`; `tariff_email_intakes` holds one row per email (unique
(Message-ID, sender), Message-ID being `sha256:<digest of the file>` when it has none): sender, subject (plain text,
bounded), the email's Date, source (`upload` | `folder`), attachment name and SHA-256,
status (`imported` | `duplicate` | `rejected` | `failed` | `no_attachment` | `held_sender`),
the draft version, a bounded plain error, and the approver's review.
**Reading an email.** Python's `email` package (`policy.default`), headers and attachment
parts only: a file over 15 MB is refused before it is parsed; text and HTML bodies are never
decoded, rendered or stored; no link is followed. Exactly one `.xlsx` attachment is imported
(none: `no_attachment`; other types only, more than one `.xlsx`, a non-workbook or an oversized
workbook: `rejected` with the reason). The same Message-ID again answers with the first row;
the same workbook in another email is `duplicate` (the importer's SHA-256 check). The draft's
effective date is the email's Date as a calendar date in America/Toronto; its label is the
subject, truncated. The workbook reader still never opens a `DS SDT…` sheet, and nothing in the
intake stores or returns a sheet's content.
**Approval.** `POST /tariffs/versions/{id}/approve` and `/reject {reason}`, and the existing
`POST /tariffs/versions/{id}/activate`, need `tariff:manage` **and** the user's email in
`approver_emails` (403 otherwise, with that reason). `TariffVersionStatus` has no rejected
state and the version table is not altered: a rejected draft stays `draft`, its intake row
becomes `rejected`, and it can no longer be approved or activated (409). A service call with no
actor (seed, demo and e2e scripts, test fixtures) activates as before. A held sender's email is
imported only when an approver releases it (`POST /tariffs/intake/{id}/release`); its workbook
waits in the intake folder's `held/` directory meanwhile (git-ignored `data/`), never in the
database. Nothing activates a version automatically. Air only (the diff compares air brackets
and air surcharge sections).
**Stand-in.** No live mailbox connection (no IMAP, Graph or Gmail; no credential): staff upload
the `.eml` (`POST /tariffs/intake/upload`) or drop it in the intake folder that
`app/workers/tariff_intake_worker.py --once` reads, moving each file to `processed/` or
`failed/`, never deleting. A mailbox connection needs a provider decision and credentials.
**Review fixes (2026-10-20).** (1) A rejection is recorded **by version**, whatever its
source, in a third new table `tariff_version_reviews` (one row per version: `approved` or
`rejected`, by whom, when, note); approve, the activate route and even
`activate_version(actor=None)` refuse a rejected version (409). (2) Only a current approver
changes `approver_emails`; scripts (no actor) may; when no current approver is an active
Admin, any Admin may (audited `tariff_intake.approvers_recovered`). Settings audits carry the
old and new approver and domain lists in full. (3) Before openpyxl, the `.xlsx` container is
checked from its central directory: more than 2,000 parts, more than 100 MB uncompressed, an
overall ratio above 100, or a part over 1 MiB compressed more than 100 times is `rejected`;
an XML part with a DTD is refused. (4) A held workbook is written to a temporary file before
the commit and renamed after it; an identical re-send restores a lost one. (5) A `DS SDT…`
worksheet is stripped **at the zip level before any hash, store or parse**, without reading
its cells (`app/pricing/xlsx_guard.py`): its part, `<sheet>` element, relationship,
content-type override, its own comments/drawings/tables, sheet-scoped or sheet-referencing
`definedName`s and the calculation chain are dropped, and shared strings no kept sheet uses
are blanked in place; the result is deterministic, and `attachment_sha256` is its digest.
The importer and the held folder only see the stripped workbook. (7) The duplicate key is
(Message-ID, sender), so an outside sender cannot pre-empt the vendor's id; a concurrent
duplicate meets the unique key and is answered with the first row. (8) The folder worker
skips symbolic links, survives a file it cannot read or move, and does not ingest or audit
again a file whose exact bytes are already recorded (`source_sha256`). (9) An email Date more
than 60 days from the intake time is not trusted: the intake date (Toronto) is used and a
`warning` is recorded. (10) An approver may reprocess a `failed` folder intake from its kept
file in `failed/` (`POST /tariffs/intake/{id}/reprocess`); an uploaded one is not kept, so it
is uploaded again. (11) Statuses as the code assigns them: a refusal by rule (no `.xlsx`,
several, too large, not a zip, an archive bomb) is `rejected`; a zip that is not a readable
workbook is `failed`; the screen words a refusal by rule ("Refused" / "Không hợp lệ")
differently from an approver's rejection ("Rejected by approver" / "Đã từ chối").
**Why.** OD-76 (D-12); independent review and test of Phase 13H.
**Reversible.** Yes: three new tables, additive routes; the activate route's approver check is
one call.

### DEC-0215 — Staff screens for the API-only features (Phase 14); a printable quote from an allowlist

**Decision.** The features that had routes but no screen get staff screens, built on the
existing routes; **no table is added or altered** (DEC-0181) and no migration is made.
(1) **Settings → Pricing** (`tariff:read` reads; `settings:manage`, Admin, saves): the Air
Standard and Air Express default rates (Express may be empty: Operations enter the rate per
quote), the trigger share as numerator over denominator (OD-48), the owner-confirmed flag shown
read-only, the default surcharge markup (OD-74), and the per-rule surcharge policies of the
active tariff's **air** sections (OD-44: Default, which inherits the default markup, pass
through, fixed CAD, percent; value; weight-basis override; note). Only changed fields are sent;
an obvious mistake is named beside its field before anything is sent and a server refusal is
placed beside the field it names; the server validates and audits as before. (2) **Workspace**:
a master milestone recorded once (`POST /consolidations/{id}/events`, `tracking:write`) with the
same publish rules as a single shipment (an approved template or the staff's own wording, never
both), and the result per member (updated, already had it, refused with the reason); complete
(booked) and cancel (open or booked, reason required) each behind a confirmation dialog; editing
an item (changed fields only; an emptied weight is cleared). (3) **Settings → Tariffs**
(`tariff:read`): versions with status, a version's air products and brackets, air accessorials,
beyond-area rates, and the exchange-rate history the worker recorded; the manual workbook import
(`tariff:manage`) makes a **draft**, which is reviewed exactly as an emailed draft (13H): the
diff, then Approve and activate or Reject, shown **only to a designated approver** (the server
still refuses anyone else, OD-76). Sea products and sea-only accessorials are not listed (OD-49).
(4) A customer's milestone email choices on the customer record (`tracking:write` edits), and
the invoice due days in Finance → Periods (`settings:manage` edits). (5) A **printable customer
quote** for a finalised version.
**Two backend additions.** `GET /shipments/{id}/quotes/{version}/document` (what reading a quote
needs: Operations and Admin) returns an **allowlist** (`QuoteDocumentOut`, `extra="forbid"`):
the company's details as on invoices (OD-64), the customer's name and reference, the shipment
reference, version and date, and the customer side of the version read by the same
`build_customer_view` as the 13G offer (Solaris service name, billable kg, rate per kg, base
charge, the surcharges the customer pays, total, CAD, before tax). A draft has no document
(409). No vendor cost, exchange rate, markup, margin, vendor name, product code or tariff
version is read into it. Tariff versions now carry `review_decision` (`approved` | `rejected` |
null, from `tariff_version_reviews`), so the browser shows a rejected draft as rejected rather
than as a draft awaiting review.
**Language of the printed quote.** The staff member's interface language (English or
Vietnamese): staff print it and hand it over; the figures are the same in both.
**Review fixes (2026-10-20).** (1) A **superseded** version is printable too (it is what the
customer was quoted then); the document carries `status` and `superseded_by_version` and the page
says "Superseded by vN"; a draft is still 409. (2) A master milestone that reached no shipment
(nothing applied, nothing already there) is shown as a failure ("not recorded on any shipment")
with each member's reason. (3) The pricing form measures changes against the values it was
filled from; a refetch refills only untouched fields, so it cannot send a stale value back; the
same for the milestone-email choices (only changed choices are sent; Save is disabled until
something changes) and the invoice due days. (4) The tax setting is worded, not shown as its
code. (5) An item's unit is chosen from the server's allowed units. (6) The default markup takes
at most two decimals. (7) The workbook import checks the 4 MB limit before uploading, puts the
error beside the file field and shows the importer's counts and warnings afterwards. (8) The
master's milestone / complete / cancel buttons are hidden without `tracking:write` /
`shipment:write`. (9) A finance-settings PATCH that changes nothing writes nothing and no audit
entry. (10) Cancelling a master whose customers hold a finalised quote or an accepted offer
lists them in the confirmation and warns that cancelling does not withdraw them (no server
rule changes; read from what the workspace already loaded).
**Why.** Owner, 2026-10-20 22:16 (finish to UAT-ready); `16_REMAINING_WORK_PLAN.md` gap items 1–6;
independent review and test of Phase 14.
**Not done.** The printed quote is not in the customer's own language when it differs from the
staff member's; surcharge names on it are the vendor sheet's (open question 4); no sea screen.
**Reversible.** Yes: screens, one read-only route, additive response fields, and a no-op
finance-settings save that no longer writes.

### DEC-0216 — Workflow hardening (Phase 15): furthest-milestone notifications, customer timeline wording, quote email resend, accepted-quote invoice prompt, approver badge

**Decision.** Five changes; **no table is added or altered** (DEC-0181) and no migration is made
(head stays `c5e8a1f3d7b9`). (1) **Milestone email.** A milestone is never notified when it is
below the **furthest milestone the shipment already reached**: the highest of the shipment's
current state when that state is on the milestone ladder (received 1, in transit 2, out for
delivery 3, delivered 4) and every other **published, unvoided** milestone event on the
shipment (`notification_service.furthest_reached`). An exception or a return in progress (the
"on hold" cases, rank 0 as states; a delivery attempt ranks as out for delivery) no longer lets
a late or backdated earlier step through. A recipient delivery counts as delivered only when the whole
shipment is delivered, otherwise as out for delivery (AC-7). A **returned or cancelled**
shipment notifies nothing further: nothing is queued while the state is returned or cancelled
or the booking is cancelled (see the review fixes below); a row queued before the
return or cancellation is skipped at dispatch with the new reason `closed`. (2) **Customer
timeline wording** (stand-in in `16_REMAINING_WORK_PLAN.md`): each Customer Account timeline
entry carries its published `event_type` (`AccountTimelineEntry`, a vocabulary value); the
account shows the standard sentence for that event type in the customer's language (vi/en,
account catalogue `detail.event.*`), and beneath it the staff's published text (a standard update
rendered in the same language, or the sentence they typed) unless it says exactly what the
standard sentence says. Internal notes are not in the response shape. The public tracking page
and its contract are unchanged (it does not share the component). (3) **Quote email resend.**
`POST /quote-offers/{id}/resend-email` (the send/withdraw permission): only an offer still
waiting for an answer whose `email_status` is `failed`, or `no_email` once the customer has an
address. A conditional update claims it (`email_status = resending`, so two presses send once),
audited `quote.email_resent` with the previous outcome, committed; then the same
decide / send / record seam as the first send, outside any retried unit. Workspace: "Resend
email" in the offer panel. (4) **Accepted quote → invoice prompt** (stand-in: acceptance records
only). When the latest offer is accepted and the shipment has no live (unvoided) customer
invoice, the workspace offer panel shows "Customer accepted vN — issue the invoice" with a
button that moves to the existing Issue invoice control; Finance → Invoices lists "Accepted, not
invoiced" (`GET /finance/accepted-not-invoiced`, `financial:read`, read-only: reference,
customer, version, accepted date, the accepted total, the master, and a newer-version flag), each
linking to the master. Nothing issues an invoice automatically; a voided invoice brings the
prompt back. (5) **Approver badge.** `GET /tariffs/intake/pending-count` (`tariff:read`) returns
`viewer_is_approver`, drafts awaiting a decision (draft versions with no
`tariff_version_reviews` row; a rejected draft is decided) and held-sender intakes. Holders of
`tariff:manage` ask for it; a designated approver sees the count on the Settings navigation
entry and the Settings → Tariff updates tab. No email.
**Review fixes (2026-10-21).** (1) "Closed" is read from the **shipment's state only**: the
booking cancelled, the state returned or cancelled, or every active package returned. One parcel
of several returned does not close the shipment, and a returned shipment sent out again (state
back on the ladder) notifies later milestones normally; a returned event no longer closes by
itself. A delivery attempt is on the ladder (rank 3, out for delivery); exception and return in
progress are off it (rank 0). (2) A `closed` row frees its dedup key as a `voided` one does, so
voiding a mistaken return lets the milestone notify. (3) A `resending` claim older than 10
minutes (abandoned mid-send) may be taken over; a younger one answers 409 "already being sent
again". The offer is re-checked just before sending: if it was answered or withdrawn meanwhile,
nothing is sent and `email_status` becomes `skipped`. (4) An accepted offer flagged
`superseded_by_version` shows "agree the price first" in the workspace, with no shortcut to the
invoice; "Go to Issue invoice" says why when the control is absent (no permission, or not
available yet). (5) Customer timeline entries carry `scope` (`shipment` | `package`, derived from
the listed package references): a step on some, not all, of several parcels reads "One of your
parcels …" (AC-7). (6) `pending-count` gives a non-approver `false` and zero counts.
(7) `accepted-not-invoiced` reads in one joined query with the limit in SQL (`limit`, default
100) and returns the true total.
**Why.** Gap items 7–10 and 12 of the remaining-work plan; workflow safety without new tables.
**Not done.** No automatic invoice on acceptance; no reminder email to approvers; the account
standard sentences await review by Vietnamese-speaking staff.
**Reversible.** Yes: additive routes and response field, one dispatch skip reason, screens.

### DEC-0217 — Registers and staff documentation (Phase 16): OD-32 narrowed by OD-77; owner-decision register brought up to date

**Decision.** Documentation only; no code, table or migration changes. (1) **OD-32 and OD-77
reconciled.** OD-32 (2026-09-19) said the Customer Account shows no financial information.
OD-77 (2026-10-20) is newer: staff send a quote and the customer accepts it in the account.
OD-77 is read as narrowing OD-32, not replacing it. The only financial figures the account shows
are those of a quote staff sent: the service, billable weight, rate per kg, base charge, the
surcharges the customer pays and the total before tax, in CAD. These figures come from the
`AccountQuoteDetail` allowlist. The account still shows no invoice, payment, balance, cost,
profit, margin, exchange rate or markup. Recorded in OD-32's `current_implemented_behavior`,
citing OD-77. (2) **Register refresh.** Each `not_implemented` record was checked against the
backend and frontend code. Fourteen records whose code is built move to `default_in_force`:
OD-23, 24, 25, 27, 28, 29, 31, 32, 34, 36, 37, 38, 43 and 44. Their current behaviour and evidence
files (`cited_in`) were updated. Two records keep `not_implemented`, with their text refreshed
to say what is and is not built: OD-35 (suspend, reinstate and deactivate are built; data export
and deletion on request are not) and OD-53 (no beyond fee is computed; the lb-to-kg rule is not
coded). The open records OD-10 to OD-13, OD-17 to OD-19 and OD-22 are not built and are
unchanged. The current
behaviour of OD-02, 03, 45, 48, 71, 72, 76 and 77 was corrected to match Phases 13D to 15. OD-71 had
said the language choice is remembered in the browser; the account stores nothing in the
browser. (3) `docs/STAFF_GUIDE.md` gains a part covering the workspace, quotes and acceptance,
finance, pricing settings, tariffs, milestone emails and the Customer Account.
`docs/b2c_merge/19_OWNER_QUESTIONS.md` lists every open question with the stand-in in force.
**Why.** Gap items 11, 14–18 and 20 of `16_REMAINING_WORK_PLAN.md`. A register that says
`not_implemented` for built code misleads UAT and the owner.
**Corrected in Phase 16.** Texts that predated OD-69 now say Admin or Operations may reopen:
the Month close note (`en.js`, `vi.js`), the finance service's refusal messages and docstring
(which also now states GST/HST per OD-64 and the OD-73 rates), and a comment in
`FinancePage.jsx`. Comments, docstrings and screen text only; no rule changed.
**Not done.** Nothing else.
**Reversible.** Yes: documentation only.

### DEC-0218 — UAT readiness (Phase 17): the seeded air dataset, a third UAT pack, RC-UAT-17

**Decision.** (1) **Air dataset.** `scripts/uat_env.py --reset` now runs
`scripts/uat_seed_phase13.py` after the base seed. Through the services and the HTTP routes,
never by writing rows, it adds the sanitized tariff (active), demo Vietcombank readings, the
2 % default markup and CAD 18.00 rate saved by the demo Admin, four customers A1 to A4 on
`example.com`, five Air Standard masters (`UAT-AWB-OPEN`, `-BOOKED`, `-TRANSIT`, `-DELIVERED`,
`-CLOSED`) at the stages the cases name, a sent quote awaiting the customer, two accepted in
the account, invoices at GST/HST 0, 5 and 13 %, a part payment, a VND payment and a refund,
two vendor bills (one with a variance, reconciled), a closed month, two linked Customer
Accounts (A1 Vietnamese, A2 English; A2 has turned "in transit" off), milestone emails in the
UAT capture folder, and two vendor rate emails generated from the sanitized fixture and read
by the intake worker (one draft with three prices changed, one held). The tariff approver
list in UAT is the demo Admin only and the intake mailbox is `tariffs@demo.example.com`
(set through a new, service-only `mailbox_address` argument of the intake settings update;
the first save's audit records the old approvers as "owner default" rather than copying the
defaults), so no real address is stored anywhere in the UAT database — the seed test scans
every text column. Street addresses are plainly fictitious. Idempotent (a second run adds
nothing), guarded (production, demo seeding off, a non-`.uat.db` database, or a mail or intake
folder outside the database's directory are refused), and `--check` reports each item.
`--refresh-fx` adds a demo reading without calling the bank. (2) **A third pack.**
`docs/UAT/AIR_UAT_PACK.md` holds 36 cases (`UAT-WSQ` 7, `UAT-QAC` 4, `UAT-FIN` 8, `UAT-PRC` 4,
`UAT-TAR` 5, `UAT-MLS` 4, `UAT-VIA` 4) in the existing format, with a blocked-by table from
`19_OWNER_QUESTIONS.md` in which nothing is blocked (each question's stand-in is what the case
tests). `UAT_CASES.md` stays at 49 and the Customer Account pack at 60, which are owner
decisions (DEC-0136, DEC-0162). `scripts/verify_uat_blank.py` checks the third pack and its
count. (3) **Stale text corrected.** The Customer Account is Vietnamese first (OD-71), not
English only: `CA-XP-03` now tests the language switch (same identifier, same count); the
`CA-PRF-*` banner says the profile and notification screens exist; `ENVIRONMENT.md` updated
(RC-UAT-17, the air dataset, `TARIFF_INTAKE_DIR`, the `--once` workers, how the owner adds
himself as an approver). New: `HOW_TO_RUN.md`, `UAT_SCRIPT_FOR_BEN.md`. (4) **RC-UAT-17**
supersedes RC-UAT-16 (Phases 13A to 16 changed screens, routes, schemas, the Alembic head and
the backend lock), measured at the application commit `1089257`; the freeze adds only
documents, scripts and one backend test file. (5) **Dry-run fixes** (stand-ins where the
owner has not ruled): a published master milestone is a repeat only of a published one, so
"unpublished, then published" records the published event and queues its email once
(UAT-MLS-04); the Customer Account session's last-seen touch is committed on its own, best
effort, in the session dependency for every account route, after the unchanged expiry,
idle, revocation and CSRF checks — a lock skips the touch and never fails the request (the
per-route workaround in `quotes.py` is removed), and the touch is written at most once a
minute (`SESSION_TOUCH_INTERVAL`), so ordinary page loads take no write lock (found by the
full suite's statement-count test); an invoice for a quote version whose offer
was withdrawn or declined stays allowed, but the workspace warns before **Issue invoice** and
the issue audit records `offer_state`. Because these change application files, RC-UAT-17 is
measured on the app+tests commit the lead makes, not on `1089257`.
**Why.** Gap items 19, 21 and 22 of `16_REMAINING_WORK_PLAN.md`: UAT needs data for every
phase, cases for it, and a baseline that reports 10 of 10.
**Not done.** No table, migration, route or dependency changed. No case was executed. The
full backend suite and Playwright were not re-run after the fixes. Items and fee lines can
still be added to the shipments of a booked master (only the master's weights, service,
origin and membership freeze); recorded in `UAT-WSQ-05`, behaviour unchanged.
**Reversible.** Yes: scripts and documents.

### DEC-0219 — A booked master's items and fees are locked (owner decision 8)

**Decision.** Once a master is `booked`, and while it is `completed`, the commodity items and
the surcharge fee lines of every shipment riding in it are locked: adding, editing or removing
an item (`shipment_item_service`) and adding or removing a fee line
(`pricing_service.add_fee_line` / `remove_fee_line`) is refused with 409 and the message
"MST-… is booked, so the items and fees of its shipments are locked. An Admin can unlock it for
edits, with a reason." (`detail.code = master_locked`). An `open` master is unaffected; a
`cancelled` one has released its members, so their items are theirs again.

**Stand-in (owner: "Admin can unlock with a reason, audited").** `POST
/consolidations/{id}/unlock {reason}` -- Admin only, through a new permission `master:unlock`
held by no role set (Admin holds every permission); reason required, at most 400 characters;
one open unlock per master (partial unique index; two Admins unlocking at once get 409, not
500); refused on a master that is not locked.
`POST /consolidations/{id}/relock {reason?}` -- Admin or Operations (`shipment:write`). The
unlock also closes by itself when a quote for any member shipment is finalised after it
(`pricing_service.finalize` -> `master_lock_service.on_quote_finalized`; relock reason
`quote vN finalised for SX-…`). While unlocked, each item and fee audit row carries
`master_unlock_id`. Audits: `master.unlocked`, `master.relocked` (`automatic` true/false).
Workspace: a lock badge in the header, a banner (Admin: "Unlock for edits" with a reason dialog;
others: "An Admin can unlock it"), item and fee controls disabled with "Locked: this master is
booked…"; when unlocked, the reason and "Lock again". `GET /consolidations/{id}` carries
`edit_lock {locked, lockable, unlock}`.

**Not locked (unchanged):** re-pricing, rate confirmation and finalising a quote; master
milestones; cartons (`PATCH /consolidations/{id}/cartons`); the master's own fields (already
frozen by booking).
**Why.** OD-88 (Louis Tong, 2026-10-21).
**Reversible.** Yes.

### DEC-0220 — Quotes expire on a new tariff before the goods are received (owner decision 9)

**Decision.** A quote expires only when the goods have not yet been received **and** a new
tariff version becomes active. On activation (`tariff_import_service.activate_version`, the
approver's `tariff_intake_service.approve`, and the `POST /tariffs/versions/{id}/activate`
route all call `quote_expiry_service.expire_for_new_tariff`, which is idempotent), every
finalised quote version priced against an older version of the same vendor's tariff expires,
with or without an offer, unless:

* **received** -- the shipment has a published (`is_public_update`), unvoided milestone of
  `received_at_solaris` or later (processing, departed, in transit, customs, arrived, out for
  delivery, delivered, delivered to a collection point, delivery attempted, return in progress,
  returned), or its operational state is `received_at_solaris` or later. Never expires;
* an **issued invoice** exists for the shipment (any live, unvoided one) -- stand-in: the quote
  does not expire and the invoice is never touched;
* the master the shipment **currently** rides in (`master_lock_service.master_for_shipment`,
  not the master named on the quote version) is **booked or completed** -- stand-in: a booked
  master is priced at the tariff it was booked under (`estimate_for` pins it), so the new
  tariff cannot re-price it;
* the shipment is cancelled.

Expiring writes a `quote_expiries` row (version, tariff version, previous offer status, the
draft withdrawn), turns a `sent` or `accepted` offer into `expired` (a new value of the string
`quote_offers.status`), discards the version's draft invoice (`invoice.draft_discarded`), and
audits `quote.expired`. Race with an acceptance: the offer is changed by a conditional UPDATE
(`WHERE status IN ('sent','accepted')` and equal to the status just re-read from the
database), so the recorded previous status is the true one; the draft is re-read afterwards,
so a draft created by an acceptance that committed a moment earlier is withdrawn too.
`activate_version` passes its `now` to the hook. The migration's downgrade maps `expired`
offers back to `withdrawn` before dropping the new tables. The quote version keeps its status and figures. An expired quote cannot
be accepted (409, closed reason `expired`), sent (`send_quote` refuses) or invoiced
(`issue_invoice` and draft Send refuse). The workspace shows "Expired: re-quote on the new rate"
with a re-quote button (opens the next version on the new tariff); the Customer Account shows
the quote as **Đã hết hạn / Expired** with "Báo giá này đã hết hạn vì giá cước thay đổi trước khi
chúng tôi nhận hàng của bạn. Solaris Express sẽ gửi bạn báo giá mới." No customer notification
(owner: no). The accepted-not-invoiced list no longer shows an expired offer.
**Why.** OD-89 (Louis Tong, 2026-10-21). Stand-ins listed in `05_OPEN_DECISIONS.md` and `19_OWNER_QUESTIONS.md`.
**Reversible.** Yes.

### DEC-0221 — Accepting a quote prepares its invoice as a draft (owner decision 9a)

**Decision.** In the same unit as the customer's acceptance (`quote_offer_service.accept` ->
`invoice_draft_service.create_for_acceptance`), an `invoice_drafts` row is created: payer (the
recorded payer, else the customer), the accepted version's revenue lines with vendor-naming
wording replaced by the neutral label (`customer_labels`, customer's language), bill-to name and
the payer's billing (else both-ways) address, GST/HST 0 %, revision 1. Audited
`invoice.draft_created` with actor `customer_account:CA-…`. Not created when the shipment already
has a live invoice; an older live draft is discarded first ("replaced by the draft for accepted
quote vN"). **No `INV-` number until Send.**

Staff (permissions as invoicing today: read `financial:read`, change `financial:write`):
`GET /invoice-drafts`, `GET /invoice-drafts/{id}`, `GET /shipments/{id}/invoice-draft`,
`PATCH /invoice-drafts/{id} {expected_revision, bill_to_name, bill_to_address,
customer_reference, notes, tax_rate_percent 0|5|13, lines [{description, amount_cad}],
total_change_reason}` -- 409 `stale_revision` when the revision is not the saved one; a reason
is required when the lines' total differs from the accepted quote; audited
`invoice.draft_edited` with a `{field: {from, to}}` diff. `POST /invoice-drafts/{id}/send
{expected_revision}` -- issues the real invoice with `finance_service`'s numbering, revenue
month and tax from the saved draft (`issue_invoice_from_draft`), marks the draft `issued`,
audits `invoice.issue` and `invoice.draft_sent`, commits, then (outside any retried unit)
emails `invoice.sent.vi` / `.en` (invoice number, total, due date; no line, no vendor name)
through the account email seam and records `email_status`. `GET /invoice-drafts/{id}/pdf?revision=N`
(the saved draft, diagonal **DRAFT** watermark; 409 on a stale revision) and
`GET /invoices/{id}/pdf` (issued, no watermark) are drawn by ReportLab with the vendored Unicode
font; both carry Soleil Global Transportation Inc. (Solaris Express), BN 795093756RT0001, 2446
Cawthra Road B1U8, Mississauga ON L5A 3K6, bill-to, lines through `customer_safe_label`, GST/HST,
total and due date, labels in the customer's language.

**A newer version.** When a quote version newer than the draft's is finalised, Send is refused
(409 `quote_superseded`, `{draft_version, latest_version}`) unless the request carries
`acknowledge_superseded: true` (the screen names both versions and asks for the box "Send at the
accepted price (vN)"; `invoice.draft_sent` records `sent_despite_newer_version`). Otherwise
`POST /invoice-drafts/{id}/withdraw {reason}` (`financial:write`, reason required, at most 300
characters) discards the draft (`invoice.draft_discarded`, actor the staff member) and the
shipment is invoiced from its latest version the normal way. Send asks for confirmation first
(number assigned on send, total, the customer's email address or "no email on file"). A draft
save whose lines, notes, bill-to name or address, or PO names a vendor is refused (422, field
named; DEC-0222). The PDFs continue long notes and many lines on further pages, wrap long
unbroken words, and a void invoice's PDF is watermarked **VOID**. A background refetch never
overwrites unsaved edits on the draft screen.

The manual Issue invoice stays for a shipment with no draft; with a live draft it is refused
(409 `invoice_draft_exists`) and the workspace button becomes "Review draft invoice". The
accepted-not-invoiced list (`GET /finance/accepted-not-invoiced`) carries `invoice_draft_id`
and links to the draft. Issued invoices keep the existing void/reissue rules. The invoice
document (`/invoices/{id}/document`) adds `bill_to_name`, `bill_to_address`,
`purchase_order_reference`, `invoice_notes`.

Unsaved edits: on the draft screen, while the form differs from the saved draft, Send and
Download are disabled with "Save your changes first"; leaving by an in-app link asks for
confirmation (capture-phase click guard: the app's `BrowserRouter` has no navigation blocker),
and closing or reloading the tab triggers `beforeunload`. The server's revision check backs it.
**Why.** OD-89, OD-90 (Louis Tong, 2026-10-21; draft confirmed 16:02 ET).
**Reversible.** Yes.

### DEC-0222 — Owner answers of 21 October 2026 (Louis Tong): tariff readings and vendor names

**Decision.**

1. **Express 16 kg step (D-07).** The Express zone 2 price drop at 16 kg (HCM and Hà Nội; Hà Nội
   Express zone 3 too) is correct. Price exactly as the vendor rate sheet prints it; no flag.
   The engine already used the printed band unflagged. The importer now keeps a curated list of
   owner-confirmed cells (`kango_workbook.CONFIRMED_PRICE_STEPS`: HCM-AIR-CAD!F39,
   HN-AIR-CAD!F38, HN-AIR-CAD!G38, each with product `AIR-CAD EXPRESS`, its zone and band `16`)
   and reports those drops as `confirmed_price_steps` (informational) in the import report,
   not as `price_falls_with_weight` anomalies. A drop at any other cell -- or at a listed cell
   whose product, zone, band or printed price (pinned to the cent: 5,051,007.30;
   4,757,567.30; 4,881,875.75 VND) no longer matches -- is still an anomaly.
2. **HCM meat / egg / dairy / honey (HCM air row 41, D50).** 20,000 VND/kg for route VN-CA
   (Vietnam to Canada air, the only route priced), on the full carton (current scope). The
   curated entry carries `route = PRICED_ROUTE = "VN-CA"`, and its note cites this decision
   instead of V-14 (closed). Hà Nội row 2 stays 15,000 as printed (parser reading).
3. **Per-kg scopes.** Every per-kg air rule's note either agrees with its current scope or is
   silent. HCM row 27 (costume jewellery, manual quote) stays `item_weight` although the
   sheet's footer says surcharges are charged on the full carton. Pharmaceuticals (HCM 39, HN 1)
   stay on the item's own kilograms (OD-58, OD-70). The scopes are pinned by a regression test.
4. **No vendor name in front of a customer.** Customer-facing quotes, invoices and receipts never
   show a vendor's name, including inside surcharge labels. A label that names a vendor (the
   `vendors` table's key and name, plus `kango` always; case-, diacritic- and spacing-insensitive)
   reads as a neutral label: "Phụ phí" (vi) / "Surcharge" (en), in the customer's language.
   Applied at: the Customer Account quote view (`build_customer_view`, and again when an
   already-frozen view is read by the account routes), the printable quote document (same
   builder), the invoice document (`finance_service.invoice_document`), and the draft invoice
   created on acceptance (fix pack F, `invoice_draft_service.create_for_acceptance`), its PDF,
   the issued invoice PDF and the invoice.sent emails (all covered by the leak test). Receipts
   and emails carry no tariff text (checked by test). Staff screens are unchanged.

   **Matching** (independent review): the folded text (case, diacritics) is cut into words of
   letters and digits and a name matches only as whole consecutive words ("ana" never hides
   "Canada", "ups" never "groups"); a name of five or more letters also matches the text with
   everything but letters and digits removed ("Kan-go", "K.ango"); names shorter than four
   letters are ignored unless listed in `ALWAYS_HIDDEN`.

   **Staff-typed free text.** Screened on output, replacing only the words that name a vendor
   with "đối tác vận chuyển" (vi) / "carrier" (en) in the customer's language: public tracking
   and Customer Account timeline messages and location labels, the invoice document's and
   receipt's free-text fields (bill-to, address, PO, notes, customer name and reference,
   payment reference) and both invoice PDFs. Refused on save (422, field named): a draft
   invoice's lines, notes, bill-to and PO. A last-mile carrier link whose host or label names a
   vendor is not shown at all (the next safe link, if any, is); it no longer reads "Carrier".
5. **Vietnamese wording** accepted as is. No change.
6. **Air Express** has no default rate; each quote takes a manual rate with a typed reason
   (confirmation of existing behaviour, now pinned by test).
7. **Vendor rate emails** go to benjamin.le@soleiltransportation.com (D-12, OD-76): the intake
   settings' defaults; the UAT seed overrides them with demo addresses (confirmation, pinned).

**Why.** OD-81 to OD-87 (Louis Tong, 2026-10-21). Answers D-07, D-09 and V-20; confirms D-12 / OD-76.

**Not changed.** No migration; the neutral label is computed at read time, so stored quote lines,
invoice lines and frozen offer views keep the vendor's wording for staff.
**Reversible.** Yes.

### DEC-0223 — GST/HST on the draft invoice: 13 %, included in the price, confirmed before Save and Send (owner answer 1, 2026-10-22)

**Decision.** Rates are usually all-in, with the tax included. Every draft invoice created from
now on (`invoice_draft_service.create_for_acceptance`) starts at **GST/HST 13 %, included in the
price**: the tax is backed out of the all-in line amounts,

* `tax = round_half_up(total × rate / (100 + rate))` to the cent,
* `subtotal = total − tax`,
* `total = Σ lines`.

Staff may change the rate (0, 5, 13 %) and the **mode**: `included` (in the price) or `added`
(on top, the RC-UAT-18 behaviour: `tax = round_half_up(subtotal × rate / 100)`, `total =
subtotal + tax`). The draft screen shows the rate, the mode and the amounts ("Prices include
GST/HST 13 %: subtotal X, GST/HST Y, total Z" / "GST/HST 5 % added on top: …"), previewed from
the form as typed by the server's rule in whole cents.

**Confirmation.** A checkbox "I have checked the GST/HST on this invoice":

* **Save** (`PATCH /invoice-drafts/{id}`) must carry `tax_confirmed: true`, else **422**
  `detail.code = tax_unconfirmed` (`field = tax_confirmed`); field errors (vendor name, total
  reason) are reported first. A save that changes anything bumps the revision and records the
  confirmation **for the new revision**; a save with nothing else changed only records the
  confirmation of the current revision (no new revision).
* **Send** (`POST /invoice-drafts/{id}/send`) is refused with **422** `tax_unconfirmed` unless
  the **saved** revision was confirmed (`invoice_draft_tax.confirmed_revision = revision`).
  The check runs after the expiry and newer-version checks.
* **Echoed figures** (review, 2026-10-22): a save that changes the lines, the rate or the
  mode must also send what the tax box showed — `confirmed_total_cad`, `confirmed_tax_mode`,
  `confirmed_tax_rate_percent` — and is refused (422 `tax_unconfirmed`, detail carrying the
  server's total, mode and rate) when they are missing or differ from the server's figures
  for that save. A save that sends them anyway (e.g. notes only) is checked too; a
  confirm-only or notes-only save may omit them. The screen always sends them.
* The screen clears the box whenever the rate, the mode or any line changes; Save is disabled
  with "Tick … before saving" while unticked; Send is disabled with "The GST/HST of the saved
  draft is not confirmed …" until a confirmed save. A notes-only edit keeps the box as it was.

**Storage.** New table `invoice_draft_tax` (one row per draft): `mode`, `rate_percent` (a
mirror of `invoice_drafts.tax_rate_percent`, which stays the rate's source of truth; written in
the same unit), `confirmed_revision`, `confirmed_at`, `confirmed_by_user_id`. A draft with **no
row** (created before this) reads as mode `added` at its saved rate, **unconfirmed**; its first
confirming save creates the row.

**Send.** `finance_service.issue_invoice_from_draft(…, tax_mode=…)`: included → `subtotal =
total − backed-out tax`, `tax_cad` the backed-out tax, `total_cad = Σ lines`; added → as
before. `tax_status` stays `gst_hst_<rate>`. The mode and rate are written into the invoice's
`document_json` (`tax_mode`, `tax_rate_percent`). The invoice document
(`/invoices/{id}/document`) adds `tax_mode` and `tax_included_note`; when included, the
document, the draft PDF, the issued PDF and the staff print page print **"Prices include
GST/HST 13 %"** (Vietnamese customer: "Giá đã bao gồm GST/HST 13 %") beside the totals and
label the subtotal "Subtotal before GST/HST". At **0 %** no such sentence is printed (nothing
is included). The manual Issue invoice hint now reads "13 % included by default on drafts
(pending owner confirmation, P-1); staff may change it". Profitability keeps using `subtotal_cad` (tax excluded) — unchanged code, now fed the
backed-out subtotal.

**Audit.** `invoice.draft_tax_confirmed` (revision, mode, rate, subtotal, tax, total) on every
confirmation; `invoice.draft_edited` names `tax_mode` and `tax_rate_percent` in its `changes`
diff when they change and carries a `tax {mode, rate_percent}` snapshot; `invoice.draft_created`
and `invoice.draft_sent` carry the mode and rate.

**Unchanged (stand-in).** The manual **Issue invoice** path for a shipment without a draft
(`finance_service.issue_invoice`, the workspace's rate picker) still adds the tax on top at the
chosen rate and asks no confirmation.

**Why.** Owner answer 1 (Louis Tong, 2026-10-22). **Reversible.** Yes (`downgrade` drops the
table; every draft then reads as tax added on top).

**PENDING LOUIS.**
1. Which rate auto-fills for a **Vietnam → Canada air** invoice? Stand-in **13 %** (as
   answered), although OD-64 said 0 % for international moves (the manual Issue invoice hint
   still says so).
2. **Included vs added** as the default? Stand-in **included in the price**.

### DEC-0224 — Customer-facing tracking: generic leg names, carrier links visible (owner answers 2 and 3, 2026-10-22)

**Decision.**

1. **Generic names.** Wherever a customer reads a tracking leg or tracking-source name (the
   carrier link on public tracking and on the Customer Account shipment page — the only such
   place today; the timeline exposes no leg), the name is generic, never a vendor's or a
   carrier's:
   * **Master Tracking** — the leg from Vietnam to the vendor's warehouse in Canada
     (`leg_type` `origin_pickup` or `consolidation_linehaul`);
   * **Last Mile Tracking** — the leg from the vendor's warehouse to the Solaris warehouse or
     the final destination (every other leg type: `destination_handling`, `final_delivery`,
     a staff-typed type such as `last_mile`).
   `public_tracking_service.tracking_name_key`, `TRACKING_NAMES`. The responses'
   `carrier_link` keeps `carrier_name` (now the English generic name) and adds
   `tracking_name_key` (`master_tracking` | `last_mile_tracking`). **Both legs** (review,
   2026-10-22): a new field `carrier_links` lists every safe link, **at most one per generic
   name, in leg order**, so Master Tracking and Last Mile Tracking both show when both exist
   (public tracking and the Customer Account); `carrier_link` stays, as the first of them.
   The public contract grows from 24 to 25 fields and the account detail from 25 to 26 —
   registered in `docs/customer_account/SUPERSEDED_ASSERTIONS.md` as AS-27 to AS-35 (and AS-21,
   renamed with its test); the public page and the
   Customer Account render the name from the key in the reader's language. Link text: public
   "{name}: open the tracking page" with the note "This opens the carrier's own website …";
   account "{name}: open the carrier's tracking page".
2. **Links stay visible.** A last-mile carrier link (UPS, Canada Post and the other allowed
   hosts) is shown even when its stored label names the vendor: the stored label is never
   output (so no vendor word can surround the link). The RC-UAT-18 rule that hid a link whose
   **label** named a vendor is reverted.
3. **Stand-in:** a link whose **host** names a vendor stays hidden (the next safe link, if any,
   is shown) — it would send the customer to the vendor's own site.

Staff screens are unchanged (leg type, provider, carrier label and tracking number as stored).
The customer seeing the carrier on the carrier's own page is accepted (owner).

**Why.** Owner answers 2 and 3 (2026-10-22); answers Q-P1. **Reversible.** Yes.

**Vietnamese — PROPOSED, FOR REVIEW:** "Theo dõi chặng chính" (Master Tracking), "Theo dõi
chặng cuối" (Last Mile Tracking); public link text "{name}: mở trang theo dõi"; account
"{name}: mở trang theo dõi của hãng vận chuyển".

### DEC-0225 — Costume jewellery (HCM air row 27): a manual quote amount per line (owner answer 4, 2026-10-22)

**Decision.** HCM air row 27 ("Hàng mỹ ký (trang sức giả)", B36, price text "100-300.000/Kg",
quoted case by case) is no longer per kilogram of the item. Its curated reading
(`kango_semantics.CURATED_RULES[(hcm_air, 27)]`) is `manual_quote`, basis **`manual_amount`**
(a new value of the string `SurchargeBasis` / `tariff_surcharge_rules.basis`), scope
`per_unit`, **no prefilled price** (the importer stores `unit_price_vnd = NULL`, no minimum kg).

* Staff enter the charge for the fee line: **the vendor's quoted amount in VND** for that line
  (stand-in), at Add fee (an amount field, no quantity, no weight) or later on the line
  (`PATCH /shipments/{id}/fee-lines/{line_id} {manual_unit_price_vnd}`; the amount, here and
  on add, must be finite, is **rounded to the cent before** it must be more than zero (0.001
  is refused, never stored as 0.00) and is at most 999,999,999,999 VND (the Numeric(14, 2)
  column); every refusal is a 422; `shipment:write` +
  `tariff:read`; only for a `manual_amount` line, else 422; refused on a locked master like any
  item or fee edit; audited `shipment.fee_line_amount` with from/to). Stored in the existing
  `shipment_fee_lines.manual_unit_price_vnd` (the line amount for this basis).
* The engine prices the line at exactly that amount (no kilograms, no quantity, no master-wide
  share: a `manual_amount` rule is never master-wide, even under a scope override); the cost is
  the triggering shipment's alone; the customer charge follows the buy-rate conversion and the
  markup like any surcharge.
* A line without an amount **blocks finalising**: "'Hàng mỹ ký …' is quoted case by case; enter
  the vendor's quoted amount (VND) for this line."
* Workspace: the fee line shows "Vendor's quoted amount … " or **"Amount needed"**, with an
  amount field and "Save amount".

**Re-import (S-8).** An already-imported tariff version keeps its stored reading of row 27
(per kg, item weight) until a new version is imported and activated. A row-27 line that still
carries kilograms (priced per kg under the old reading) is **never reread silently** as the
line's amount under the new reading: it is a blocking issue "'…' was priced per kg under an
earlier tariff; re-enter the quoted amount (VND) for this line for the new tariff" until staff
enter the amount on the line (which clears its kilograms). Lines whose rule changes meaning in
any other way between versions are not tracked (no per-line tariff provenance is stored);
the engine's existing refusals apply (e.g. a per-kg rule without kilograms blocks).

**Why.** Owner answer 4 (2026-10-22); closes F-1. **Reversible.** Yes.

**PENDING LOUIS.** Do staff enter the **vendor's cost** (stand-in: the customer charge then
follows conversion and markup) or the **customer's price** directly?

### DEC-0226 — The portable UAT launcher finds any supported Python, and says why when it cannot

**Decision.** `uat\uat.ps1` (the portable UAT package's launcher) looks for Python in the
`UAT_PYTHON` override (quotes tolerated), the `py` launcher's list (`py -0p`), the standard
install folders (`%LOCALAPPDATA%\Programs\Python\Python3*`, `%LOCALAPPDATA%\Python\pythoncore-3*`,
`%ProgramFiles%\Python3*`, `%ProgramFiles(x86)%\Python3*`, `C:\Python3*`) and `PATH`, and never
runs a `WindowsApps` entry (the Microsoft Store alias opens the Store). It accepts 64-bit CPython
3.11 to 3.14, preferring 3.12, then 3.13, 3.14, 3.11. On failure it lists every Python it saw with
its version, path and the reason it was refused, and prints the fix steps. A `backend\.venv`
built with a Python that no longer runs is rebuilt. Program output on stderr no longer counts as
failure (PowerShell 5.1). `uat.ps1 python` prints the same list without starting anything.

**Python 3.14 is supported**: every pinned package installs from a wheel and a 434-test backend
subset passes on CPython 3.14.9 (official python.org package, signature verified). **Python 3.15
is refused** with the reason: httptools, MarkupSafe, pydantic_core, PyYAML and watchfiles have no
3.15 wheel at the pinned versions (pydantic_core would need a Rust build).
**Why.** UAT blocker reported by Louis Tong, 2026-10-22: START_UAT.bat said no Python was found
on a PC with Python installed. Open question P-8 (upgrade the pins for 3.15).
**Reversible.** Yes.

### DEC-0227 — GST/HST on draft invoices by route: international 0 %, domestic included at the destination province's rate (owner, 2026-10-23)

**Decision.** Replaces the RC-UAT-19 stand-in (every draft at 13 % included, DEC-0223, P-1/P-2).
A draft invoice created on acceptance (`invoice_draft_service.create_for_acceptance`) fills its
rate and mode from the shipment's route (`tax_rate_service.route_tax`):

* **International** -- one end outside Canada (VN-CA, CA-VN, CA-US, US-CA, ...): zero-rated,
  **0 %** (mode `included`; at 0 % nothing is included or added and no "Prices include"
  sentence is printed; the screen reads "GST/HST 0 % (zero-rated): no tax, total X").
* **Domestic** -- both ends in Canada: tax **included** in the price and backed out on the
  invoice, `tax = round_half_up(total × rate / (100 + rate))` to the cent, `subtotal = total −
  tax`, at the **destination** province's rate from `tax_rates`: ON 13 % HST; NS 14 % HST; NB,
  NL, PE 15 % HST; AB, BC, MB, QC, SK, NT, NU, YT 5 % GST.
* **Domestic, province unknown (stand-in)**: no rate is filled in. The draft view returns
  `tax_rate_percent: null`, `tax_rate_required: true` and no subtotal/tax/total; a save without
  a rate is refused (**422** `detail.code = tax_rate_required`, `field = tax_rate_percent`);
  until a rate is chosen the tax is unconfirmed, so Send and Download are refused (422
  `tax_unconfirmed`). Choosing a rate (even 0) is a change: it needs the echoed figures and
  the tick, makes a new revision and is diffed `{"from": null, "to": rate}`.

**Reading the route.** Countries: the shipment's `origin_country_code` /
`destination_country_code`, else the sender's / recipient's address country, else the route
group (VCA = VN→CA, CAV = CA→VN, CAD = CA→CA, XUS = one end US, always international).
Domestic = both CA (or route group CAD with a country missing). Destination province
(`tax_rate_service.destination_province`, review 2026-10-24), from the delivery (recipient)
address: **the postal code first** -- its first letter (A NL, B NS, C PE, E NB, G/H/J QC, K–P
ON, R MB, S SK, T AB, V BC, X0A–X0C NU and other X NT, Y YT; only a well-formed Canadian code
counts) -- **the province text second**: a two-letter code matched case-sensitively as a whole
word ("Niagara on the Lake" is not ON; "yt" is not YT), or a name or abbreviation in English or
French as whole words anywhere in the field ("Nouvelle-Écosse", "Newfoundland & Labrador",
"Terre-Neuve-et-Labrador", "Montréal (Québec)", "Alta.", "Sask.", "Man.", "P.E.I.").
**Unknown** (staff choose) when neither tells, when the text names two provinces, or when the
postal code and the text disagree. The origin province never counts.

**What staff can do.** Change the rate and the mode (DEC-0223 mechanics unchanged: the tick
"I have checked the GST/HST on this invoice" for Save, echoed figures on a change, Send only
for a confirmed saved revision). **Allowed rates** on a draft: 0, 5, 13, 14, 15, **every
rate in `tax_rates`**, and **the draft's own saved rate**, which stays allowed after the table
changes (`invoice_draft_service.allowed_tax_rates(db, draft)`: at Save, at Send through
`finance_service.issue_invoice_from_draft`, and in the screen's list; review 2026-10-24). A rate
must be a whole percent: 13.5 or "13.5" is refused (422), never truncated. The
draft view adds `tax_rate_required`, `allowed_tax_rates` and `tax_route` (route band,
countries, destination province, suggested rate and mode); the screen names the route the rate
came from and offers the server's rates.

**The table.** `tax_rates` seeded by the migration; Admin views and edits it on **Settings →
GST/HST rates** (staff i18n en + vi). `GET /finance/tax-rates` (`financial:read`), `PATCH
/finance/tax-rates/{code}` (`financial:read` + `settings:manage`, i.e. Admin): a whole percent
0 to 30 and a label GST or HST, else 422; unknown code 404; no-op saves write nothing; audited
`tax_rate.update` with from/to. A change applies to drafts created afterwards; existing drafts
keep their rate. A province with no row reads the code default (a database built without the
seed behaves the same; reading never writes).

**Labels on documents** (review, 2026-10-24). When a draft's rate is the one its destination
province filled in from `tax_rates`, the documents use that row's label: "Prices include HST
13 %" and a tax row "HST 13 %" ("GST 5 %" in a GST province); a rate staff changed, an
international or older draft, or a manual invoice uses "GST/HST". The label is stored in the
issued invoice's `document_json` (`tax_label`); the invoice document adds `tax_label` and
`tax_line_label`; the screen's summary uses the saved label for the saved rate. **A 0 %
invoice** (draft or manual path) prints the tax row "Zero-rated (0 %)" / "Thuế suất 0 (0 %)"
(Vietnamese proposed, for review) on the document, the staff print page and both PDFs; no
"Prices include" sentence.

**Read-only users** (no `financial:write`) see "The GST/HST of this draft is not yet confirmed
by finance staff, so it cannot be downloaded or sent yet." instead of being told to tick and
save.

**Unchanged.** The manual **Issue invoice** path (no draft; `finance_service.issue_invoice`)
keeps its 0 / 5 / 13 % picker and adds tax on top (owner: unchanged, OD-106); its hint now
reads "Added on top at the rate you choose. (Drafts from accepted quotes fill the rate in from
the route.)". Quotes are unchanged (tax added on the invoice, OD-108).

**Audit.** `invoice.draft_created` carries the rate (null when required), mode and
`tax_route`; the route row records when and by whom a required rate was chosen.

**Why.** Owner answer of 2026-10-23 (OD-102), answering P-1 and P-2. **Reversible.** Yes
(downgrade drops the tables; drafts keep their saved rate).

### DEC-0228 — Costume jewellery (HCM air row 27): staff enter both the vendor's VND cost and the customer price (owner, 2026-10-23)

**Decision.** Replaces the DEC-0225 stand-in (P-3). For a `manual_amount` fee line staff enter
**the vendor's cost in VND** (`shipment_fee_lines.manual_unit_price_vnd`, as before) **and the
customer price in CAD** (new table `fee_line_manual_prices`). Neither is prefilled and no
default is derived from a conversion. The quote cannot be finalised until both are entered: the
blocking issue names what is missing (the VND cost, the customer price (CAD), or both). A line
priced per kg under the old reading keeps its re-enter block ("Also enter the customer price
(CAD)" is added when that is missing); entering only the CAD price does not clear it.

**Pricing.** Cost = the VND at the buy rate (as before). Customer charge = **exactly the CAD
price**, no conversion and **no markup** on top (stand-in), recorded with markup kind
`manual_price`; quote lines, totals, profit and the customer view use it. Changing the CAD
price revokes the rate confirmation like any price input.

**Input.** `PATCH /shipments/{id}/fee-lines/{line_id}` and Add fee accept
`manual_unit_price_vnd` and/or `customer_price_cad`: finite, rounded to the cent **before** the
> 0 check, capped (VND 999,999,999,999; CAD 9,999,999,999.99 = Numeric(12, 2)), else 422;
only on a `manual_amount` line (422 otherwise); an empty body or a null is refused; refused on a
locked master like any fee edit; `shipment:write` + `tariff:read`. Audited
`shipment.fee_line_amount` (VND) and `shipment.fee_line_customer_price` (CAD), each with
from/to. The fee-line payload adds `customer_price_cad`. Workspace: two empty fields (vendor's
cost VND, customer price CAD), a "needed" message naming what is missing, Save (sends only what
changed); staff i18n en + vi.

**Why.** Owner answer of 2026-10-23 (OD-103). **Reversible.** Yes.

### DEC-0229 — RC-UAT-20 bug fixes (owner, 2026-10-23)

1. **Payment received date off by one day.** Cause: the date was stored as naive midnight
   (`2026-09-20T00:00:00`) and the screen read every naive server value as UTC, so Toronto showed
   19 Sep 20:00 → "Sep 19"; and an input carrying an offset was converted to UTC
   (`2026-09-30T22:00-04:00` became 1 October, moving the period month). Fix (no migration, no
   column change): a received date is a **plain calendar date**. `customer_payments.received_at`
   (still DateTime) stores naive midnight of the date **as written**; any offset is ignored; the
   UI (`formatPlainDate`, `localToday` in `utils/format.js`; the invoice page and the receipt
   print page) shows the `YYYY-MM-DD` part as is and sends a plain date. The period month and
   the M+7 lock use that date. "Not in the future" compares dates against today in
   America/Toronto (or the staff member's zone when it is ahead); an undated payment or a refund
   is dated today in Toronto. **Legacy rows** (review, 2026-10-24): a value with a non-midnight
   time (recorded before the fix as a UTC instant) is shown, as before, as its Toronto-local date
   (`formatReceivedDate`); only date-only and exact-midnight values are plain dates. `recorded_at` keeps the exact moment; the VND `rate_day` stays the
   invoice's Toronto date (OD-66).
2. **Download of a draft invoice needs the GST/HST confirmed.** `GET
   /invoice-drafts/{id}/pdf` is refused with **422** `tax_unconfirmed` (`field =
   tax_confirmed`) unless the saved revision's GST/HST is confirmed -- the same rule and error as
   Send, checked after the draft-status and revision checks (a stale revision is still 409).
   The screen disables Download with the Send message ("… tick the check and save before sending
   or downloading"), shown to read-only users too.
3. **Final delivery leg offers the vendor.** Cause: the staff provider picker read one fixed
   carrier list (`leg_service.KNOWN_CARRIERS`) that never held the vendor; other legs only showed
   it from stored names. The staff provider list is now per leg type (`/shipments/meta`
   `leg_providers`), the vendor ("Kango Logistics", the existing constant) first on every leg
   type including `final_delivery`; the stored provider stays free text (backend already
   accepted it). The carrier list of tracking references is unchanged.
4. **Generic tracking name on the staff shipment view.** Each staff leg shows "Master Tracking"
   / "Theo dõi chặng chính" (origin pickup, consolidation linehaul) or "Last Mile Tracking" /
   "Theo dõi chặng cuối" (every other leg type), from `tracking_name_key` now on the staff leg
   payload (DEC-0224 mapping). The label is a fixed i18n string, never a vendor or carrier
   name; staff still see the stored provider and carrier. Public and Customer Account contracts
   unchanged.
5. **Tariff import warnings on Settings → Tariffs.** Each tariff version shows "Import
   warnings (N)" with the count by kind and the full list (25 per page) and, apart, "Confirmed
   price steps (3)" (HCM-AIR-CAD!F39, HN-AIR-CAD!F38, HN-AIR-CAD!G38; DEC-0222), not counted.
   Route `GET /tariffs/versions/{id}/warnings?limit=&offset=` (`tariff:read`; limit 1–500)
   returning `count`, `counts_by_code`, `items [{code, message, sheet, cell}]` and
   `confirmed_price_steps`. **The seeded sanitized tariff has exactly 39 warnings**: 35
   `express_zone_below_ground`, 2 `trucking_pallet_fees_not_imported`, 1 `duplicate_fsa` (K1A),
   1 `beyond_code_without_rate` (code 180). Unchanged by the row-27 change (DEC-0225); 42 before
   DEC-0222 moved the three Express 16 kg steps out. The UAT script's "39" is right; it only
   could not be found before (warnings showed only right after a manual import).
6. **Wording kept (OD-108).** The customer quote total stays "Tổng cộng" with the note "Thuế,
   nếu có, sẽ được tính trên hóa đơn." (quotes never include tax: `tax_included` stays false);
   the staff note label stays "Ghi chú từ Solaris Express". Pinned by
   `test_rc20_tax_by_route.py::test_the_customer_quote_wording_is_kept` and
   `::test_the_customer_quote_view_still_says_tax_is_not_included`.

7. **Both tracking links (tester note, review 2026-10-24).** Verified, no defect: with a safe
   carrier link on a Master Tracking leg and another on a Last Mile Tracking leg,
   `carrier_links` returns both and both render on the public page and the Customer Account
   (`test_rc20_carrier_links.py`, `rc20CarrierLinks.test.jsx`). A last-mile link is hidden on
   purpose when its tracking reference's source mode is left on "manual" (the staff form's
   default), when it is a Canada Post address-bar URL with a `#/details/...` part, or when its
   host lacks `www.` (not on the allowed list) -- the likely cause of the tester's observation.
   Possible follow-up (not built): default the staff form to "external link" when a URL is
   entered.
8. **Negative margin on costume jewellery.** A CAD price below the VND cost at the buy rate is a
   negative-margin fee like any other: finalising needs a reason (pinned by test).

**Why.** UAT findings reported 2026-10-23 and the review of 2026-10-24. **Reversible.** Yes.

### DEC-0230 — Shipment CSV import and legacy history baseline (OD-15 / OD-16 stand-ins)

Two new import kinds sit beside the customer import and follow its pattern exactly:
`csv_safety` reads the file (2 MiB, 5,000 rows, 60 columns, 1,000 characters per cell,
binary/encoding/quoting refusals, header allow-list — OD-14 limits unchanged); a **dry run**
validates every row and reports per row while writing no business record; a **commit**
re-uploads the same bytes, needs `confirm=true`, re-parses and re-validates, and is refused
unless the **same staff member dry-ran the same bytes with the same options within 24 hours**
(proved by the dry run's own audit entry `<kind>.import_dry_run`; no staging table, no copy
of the file). Every commit is an `import_batches` row (`kind` = `shipments` or
`legacy_history`, shared `IMP-` counter) with one `import_batch_rows` row per CSV row, and an
audit entry (`shipment.import_commit` / `legacy_history.import_commit`) carrying counts and
the digest only — never a cell value.

1. **Shipment import** creates ordinary **air** shipments for **existing** customers through
   `booking_service` (draft, optionally confirmed through the normal confirmation, which
   issues the Solaris ID), `package_service` and `shipment_item_service`, so an imported
   shipment gets the same validation and audit as a typed one. It creates **no quote,
   invoice, email, event or milestone notification**. An `external_reference` already
   imported (or repeated in the file) is **refused as a duplicate**; the unique
   `shipment_import_links (source_system, external_reference)` backs this. Every created
   shipment is traceable to its batch and row (`shipment_import_links`) and carries
   `source_system = csv_shipment_import`, `source_record_id = external_reference`.
2. **Legacy history baseline** imports past shipments with dated milestones into
   **separate tables** (`legacy_shipments`, `legacy_shipment_events`), never into
   `shipments`/`shipment_events`. By construction legacy records never notify (the outbox
   reads `shipment_events` only), are never quoted, invoiced, master-locked or expired, and
   are absent from every operational queue, shipment list, dashboard, finance report and
   export. Staff with `shipment:read` see them on Import › Legacy history (read-only list,
   search, include-voided). A re-run is idempotent (a live `source_system|legacy_reference`
   is matched, never duplicated or overwritten); a baseline is **voided as a whole** (soft,
   Admin, reason ≥ 5 characters, audited `legacy_history.baseline_void`); voided records stay
   in the table and the same history can be imported again.
3. Permissions follow the customer import (DEC-0082): `import:template`, `import:preview`
   (+ `shipment:read` for a dry run) and `import:commit` (+ `shipment:write` for a commit or
   a void) — Admin only today. Reading legacy records: `shipment:read`.
4. Only tables were added (DEC-0181): migration `a1c3e5f7b9d2` (revises `f7c2d9e3a1b5`).

### DEC-0231 — Customer Account: password change, self-service email change, and reinstating a deactivated account; staff password change (owner, 2026-10-24)

1. **Customer change password** (`POST /api/v1/account/password/change`, signed in, CSRF).
   Body `{current_password, new_password, new_password_confirmation}`. Rate limit per account
   (5 per 15 min, before the body is read; 429 with Retry-After). The current password is
   checked first (422 `field=current_password`, audited `customer_account.password_change_refused`
   `bad_current_password`); the new one follows the account policy (`ACCOUNT_MIN_PASSWORD_LENGTH`
   = 12, no leading/trailing space, not a common password), must be typed twice and must differ
   from the current one (422 `field=password`, audited `same_password`). On success: the hash is
   replaced; **every other session of the identity is revoked; the caller's session is rotated**
   (revoked and re-issued with new cookies and CSRF token, so a copied cookie is worthless);
   outstanding password-reset links die; **any pending email change is cancelled and its
   link killed** (audited `customer_account.email_change_cancelled`, reason
   `password_changed`; a password **reset** does the same with reason `password_reset`, so a
   stolen session cannot keep a takeover pending through the owner's fix); a notice "Your Solaris Express password was changed"
   (template `account.password_changed_here`) goes to the account's address in the customer's
   language (linked customer's preference, else the identity's); audited
   `customer_account.password_changed` (count of sessions revoked). Any signed-in account
   (`pending_approval` or `active`) may use it.
2. **Staff change password** (`POST /api/v1/auth/password/change`, staff session + CSRF; account
   menu → "Change password", `/my-password`). Same principles: current password required, staff
   policy (12 characters, no leading/trailing space), typed twice, not the same; rate limit 5 per
   15 min per user; every **other** staff session revoked, this one kept; `must_change_password`
   cleared; this session is **rotated** (new cookies and CSRF token, as on the customer
   side); audited `auth.password_change` / `auth.password_change_refused` (reason code only).
   No email (staff email is not on the account email seam; B-1).
3. **Customer self email change.** `GET /api/v1/account/security` (sign-in email + pending
   change), `POST /account/email/change` `{current_password, new_email}` (signed in, rate limit 3
   per hour per account), `POST /account/email/change/cancel`, and the public
   `POST /account/email/change/confirm` `{token}` (origin check + per-caller token limit, like
   `/verify-email`). The request needs the current password. A single-use, hashed,
   purpose-bound token (`customer_auth_tokens.purpose = email_change`, issued to the **new**
   address, valid for the OD-36 verification period, 24 h) is sent to the new address
   (template `account.email_change_confirm`, link `/account/confirm-email-change#token=…`).
   **The account keeps using the old address until the link is used.** A new request supersedes
   the previous one; cancel invalidates it. The **single email rule** holds: an address already
   held by another account (any status) or by another customer record (not the account's own
   linked customer, not a merged tombstone) is refused with **the same answer as success** —
   same status, same sentence ("If that address can be used, we have sent a confirmation link to
   it…"), same pending state — and no message is sent (no enumeration; the refusal code is kept
   internally on the request row and in the audit `outcome`). The rule is **checked again when the
   link is used**, and a true race is decided by the unique index on
   `customer_identities.email_normalized` inside a savepoint; every refused link answers the one
   `GENERIC_TOKEN_FAILURE` sentence. On success: the identity's email changes (and
   `email_verified_at` is stamped), **the linked customer's email follows it** (single email rule,
   B-3), outstanding reset links die, the **old** address receives a notice that names neither
   address (`account.email_changed_notice`), audited `customer_account.email_changed`. A
   suspended account cannot complete a change. **When a change is requested, the current
   address is told** (template `account.email_change_requested`, customer's language, no token,
   no address), whether or not a link went out — so the requester's answer still says nothing
   about the address. **Confirming ends every other session** of the identity; the browser that
   opened the link keeps its own session if it holds one of this identity's. Audit payloads carry the keyed `address_key` of
   the new address, never the address.
4. **Admin reinstatement of a deactivated account** (`POST
   /api/v1/customer-account/identities/{ref}/reactivate`, `{reason_code, note?}`; list `GET
   /customer-account/identities-deactivated`). Admin only — the deactivation permission
   (`customer_account:review` + `customer_account:deactivate`). Reason codes:
   `deactivated_in_error`, `customer_request`, `review_complete`; optional note ≤ 500 characters
   kept on the reinstatement row only. The identity returns to its **prior usable status**:
   suspended stays suspended (B-4); approved with its link still active → `active` —
   **unless the linked customer was merged away, archived, or absorbed another customer by a
   merge at or after `deactivated_at`**: then the link is ended (audited
   `customer_account.unlink`, reason `merged_since_deactivation` /
   `archived_since_deactivation`) and the account returns to `pending_approval` (or
   `suspended`), never `active`, so staff re-review and link it afresh (B-13); the status is
   written by `customer_identity_service.restore_after_deactivation`, which refuses `active`
   without exactly one live link (the activation invariant keeps its two writers); otherwise
   verified → `pending_approval`, unverified → `pending_verification`. Old sessions stay revoked
   (the customer signs in again); lockout counters are cleared; when the account returns to
   `active` the single email rule puts the sign-in email back on the linked customer (B-6). A
   notice `account.reinstated` is sent when the account can sign in. Recorded in
   `customer_account_reinstatements` (the deactivation it reversed: when, by whom, why) and
   audited `customer_account.reactivate`. **Refused (409)** when the account is not deactivated,
   was deactivated on a `privacy_request` (B-5), or was a declined application. The deactivated
   list read is audited (`customer_account.deactivated_list_read`). `IdentityStatusOut` gains
   `can_reactivate`.
   The account route table grows from 21 to 26 routes: AS-42 in
   `docs/customer_account/SUPERSEDED_ASSERTIONS.md` (cites OD-36, DEC-0181 until DEC-0231 is
   in the log).
5. **UI.** Customer Account: "Sign-in and security" (`/account/security`, nav link for every
   signed-in account; Vietnamese first) with Change your password and Change your sign-in email
   (pending state, cancel); landing page `/account/confirm-email-change`. Staff: account menu
   "Change password"; on the account review card an Admin-only "Reinstate account" section
   (reason + note) and on the Customer Accounts queue an Admin-only "Deactivated accounts" list.
   The deactivation hint and confirmation no longer say "permanent".

### DEC-0232 — Customer quote tax wording follows the invoice rule (P-9 stand-in, pending Ben; owner direction 2026-10-24)

The customer quote's GST/HST wording follows the RC-UAT-20 **invoice** rule (DEC-0227), read
with the same route detection (`tax_rate_service.route_tax`) and the same `tax_rates` table:
**domestic** — "Giá đã bao gồm HST 13 %" / "Prices include HST 13 %" at the destination
province's rate and label (HST/GST); a domestic route whose province is unknown says "Giá đã
bao gồm GST/HST" / "Prices include GST/HST" with no rate (B-8); **international** — "Thuế suất
0 (0 %)" / "Zero-rated (0 %)". The total label "Tổng cộng" stays. This **replaces** the
RC-UAT-20 note "Taxes, if any, are added on the invoice" / "Thuế, nếu có, sẽ được tính trên
hóa đơn." — **it supersedes OD-108's note, pending Ben.** Applied to the Customer Account quote
list and detail and to the printed quote document (staff print page: "Total" / "Tổng cộng" and
the sentence, replacing "Total before tax" and "GST/HST, where it applies, is added on the
invoice."). The quote email carries no amounts (unchanged). The amounts do not change. The
wording is computed when the quote is read from the shipment's route as it is then (B-9).
API: `AccountQuoteSummary`/`AccountQuoteDetail` and `QuoteDocumentOut` gain
`tax {band, label, rate_percent}`; `tax_included` is kept (frozen, false). Superseded
assertions AS-38 … AS-41 registered in `docs/customer_account/SUPERSEDED_ASSERTIONS.md`
(cited as OD-108 + DEC-0227 until DEC-0232 is in the log; the lead may add DEC-0232 to those
citations once it is).

### DEC-0233 — Admin soft delete of old quote versions; retention-deletion machinery built but disabled (owner, 2026-10-24)

**1. Soft delete of a quote version (Admin only).** Nothing in this system is ever
hard-deleted by a user, so "delete" is a **soft delete**: a row in `quote_version_deletions`
(quote version, shipment, version number, reason, who, when). The quote version, its lines, its
offer and its expiry row stay in the database for audit.

* Routes (staff router, Admin only — new permission `quote:delete`, in no role set):
  `GET /api/v1/shipments/{id}/quote-history[?include_deleted=true]` (every version, newest
  first, with offer status, expiry, whether it may be deleted and, if not, the refusal code),
  `POST /api/v1/quote-versions/{id}/delete {reason}` and
  `POST /api/v1/quote-versions/{id}/restore {reason}`. Reason required (1–400 characters).
  Audited `quote.soft_delete` and `quote.restore` (entity `quote_version`, detail: shipment,
  version, reason, deletion row id).
* **Refused** (409 with `detail.code`): `draft` (the working copy), `issued_invoice` (an unvoided
  customer invoice uses the version), `live_draft_invoice` (a draft invoice from it is live),
  `open_offer` (offer `sent`, awaiting the customer), `accepted_not_invoiced` (offer accepted and
  the shipment has no unvoided invoice), `too_recent` (younger than the minimum age),
  `already_deleted`. **Allowed:** superseded, expired, withdrawn/declined, and finalised versions
  never sent (and an accepted one once the shipment is invoiced from another version).
* **Minimum age**: `data_retention_settings.quote_delete_min_age_days`, default **0** (any eligible
  version); measured from `superseded_at`, else `finalized_at`, else `created_at`.
* **Where a deleted version disappears:** the staff quote list (`GET /shipments/{id}/quotes`)
  and offer list (`GET /shipments/{id}/quote-offers`); the printable quote (404); the Customer
  Account quote list and detail (404, as for an unknown quote — the customer cannot tell a
  deleted quote from one that never existed); Finance → accepted-not-invoiced. The Admin quote
  history shows it with "Show deleted", who deleted it, when and why.
* **A deleted version cannot be sent or invoiced** (`quote_deleted`, 409) until it is restored
  or the shipment is re-quoted. **A deleted version is never "the latest finalised version"**
  (review L10a): the invoice's latest finalised quote (`finance_service._latest_finalized`),
  a draft invoice's "a newer quote was finalised" check
  (`invoice_draft_service.superseding_version`) and an offer's "current" check
  (`quote_offer_service.is_current`) all skip soft-deleted versions. (Finalising a new
  version still supersedes a deleted finalised one: that is a state change, not a lookup.) Version numbering is unaffected (a re-price after a deletion
  takes the next number).
* **Restore** (Admin, reason, audited) closes the row (`restored_at`); a later delete opens a
  new row, so the whole history stays. At most one open deletion per version (partial unique
  index); a concurrent second delete gets 409.
* **Staff UI**: Workspace → customer card → quote panel → "Quote history (Admin)" (collapsible;
  rendered only for `quote:delete`): table of versions with Delete (reason dialog) or the
  worded refusal; "Show deleted versions" lists deleted ones with Restore (reason dialog).

**2. Retention-deletion machinery, disabled by default.** OD-01 is unanswered, so the machinery
exists but **does nothing** until the owner decides:

* **Global switch** `data_retention_settings.enabled`, seeded **off**. Only an Admin (new
  permission `retention:manage`, in no role set) turns it on, and only by typing
  `ENABLE RETENTION` (422 otherwise); audited `data_retention.enable`. Turning it off disables
  every record class again (`data_retention.disable`).
* **Policies** `data_retention_policies`, one per record class, seeded **disabled with no period**
  (NULL = undecided). A class can be enabled only while the switch is on **and** a period (1–36500
  days) is set; its action must be one the class allows. Edits audited
  `data_retention.policy_update` (before/after).
* **Record classes** (each a closed, non-financial set; the action each allows):
  `soft_deleted_quotes` (delete: removes the version, lines, expiry row and offer of a version
  soft-deleted longer ago than the period, **only if no invoice draft or customer invoice of any
  status references it, its offer was never accepted (the customer's acceptance record) and no
  invoice draft names its offer** (review L10b) -- such versions are not in the class at all, so
  their deletion row is never purged; the deletion row of a purged version stays with
  `purged_at`), `closed_quote_offers`
  (anonymise: clears decline/withdrawal reasons and who answered on declined/withdrawn/expired
  offers), `notification_outbox_processed` (delete: sent/recorded/skipped outbox rows; never
  queued or failed), `customer_auth_tokens_spent` (delete: consumed or expired tokens),
  `customer_sessions_ended`, `staff_sessions_ended` (delete: expired or revoked sessions),
  `customer_registration_attempts` (delete), `tariff_intake_emails` (anonymise: clears sender and
  subject).
* **Never reachable**: customer invoices and lines, payments, payment conversions, vendor bills
  and lines, cost allocations, period closes, invoice drafts and their tax rows, audit events,
  consent events, suppressions, customers, shipments, shipment events, the run log
  (`FORBIDDEN_TABLES`, asserted by tests). They are not record classes, so no policy can name
  them. Legal hold: nothing is under hold; a hold would remove records from every class (D-7).
* **Worker** `python -m app.workers.retention_worker --once [--dry-run] [--batch-size N]`.
  `--once` is required; there is no loop mode and **no scheduler**. While the switch is off a
  real run does nothing at all (no rows changed, no run row, no audit) and prints so. When on,
  it works each enabled class with a period in batches (`batch_size`, default 200; one committed
  transaction per batch; at most 1000 batches per class per run), updates the policy's
  `last_run_at`/`last_run_affected`, writes a `data_retention_runs` row (counts per class only)
  and audits `data_retention.run`. A failure rolls back the open batch only and is recorded
  (`status = failed`, bounded message, no stack trace).
* **Dry run** (worker `--dry-run`, or Admin "Run a dry run" in Settings → Retention): counts per
  class what a run would affect today (`eligible`, or "No period set"), changes nothing, writes a
  run row (`dry_run = true`) and audits `data_retention.dry_run`. The real run cannot be started
  from the screen.
* **Settings → Retention** (Admin only): a warning that periods are undecided (OD-01, OD-36)
  and that turning deletion on needs the owner's approval; the switch with the typed phrase;
  the record-class table (state, period, action, last run, Save, Enable/Disable — Enable is
  disabled until the switch is on and a period is saved); the line "invoices, payments, vendor
  bills, customers, shipments and audit events are not record classes"; the dry-run report.

### DEC-0234 — Staff re-link or close of an orphaned Customer Account (B-13; stand-in under OD-110, 2026-10-24)

**The gap.** An Admin reinstatement of a deactivated account whose customer was merged (either
direction) or archived meanwhile ends the link and returns the account to `pending_approval`
(DEC-0231, review HIGH 2). The approval flow decides a *pending proposal*, and an account
approved long ago has none, so the account was stuck: it could sign in, reached nothing, and no
screen could move it (B-13, RC-UAT-21).

**Orphaned, by state.** `pending_approval`, `approved_at` set, no active link, no pending
proposal. Defined by the rows, not by how they got there, so any other path that leaves an
approved account linkless lands in the same list.

**Two ways out, Admin only** (`customer_account:deactivate`, the reinstatement permission; no
new permission), on **Customer accounts → Accounts needing a customer**:

* **Re-link** to a customer the Admin names. The list suggests one (the merge survivor, or the
  last customer itself when it absorbed others; nothing when archived) and never applies it.
  The target passes the approval's own rules (`resolve_link_target`: not merged away -- the
  survivor is named instead -- not archived) and must hold no live link of any kind (B-16). The
  Admin first sees the history the link opens (the OD-29 figures) and must tick the
  acknowledgement; the request carries `history_acknowledged: true` and the preview's
  fingerprint, refused as `preview_stale` if anything moved (B-17). In one transaction: the
  single email rule (the record takes the sign-in email, as approval and reinstatement do), a
  new link through the approval service's one link constructor, `active` through
  `customer_identity_service.activate_relinked` (a conditional update that refuses without a
  prior approval and exactly one live link; `approved_at` is kept, B-15), a
  `customer_account_relinks` row with the acknowledged figures, the audits
  `customer_account.link` and `customer_account.relink`, and the "account approved" notice
  (test capture only, B-18).
* **Close**: an ordinary deactivation with reason `orphan_closed` (sessions and tokens end, the
  record stays), a `customer_account_relinks` row, audit `customer_account.orphan_closed`; no
  message to the customer (B-19). Reversible through the existing reinstatement, which brings
  the account back to this list (B-20).

Routes (staff router `/api/v1/customer-account`): `GET /identities-orphaned`,
`GET /identities/{ref}/relink-preview?customer_public_id=…`, `POST /identities/{ref}/relink`,
`POST /identities/{ref}/close-orphan`. Reading the list and a preview are audited
(`customer_account.orphaned_list_read`, `customer_account.relink_previewed`), as the review
queue's reads are. Migration `d4f6b8c0e2a5` adds one table; nothing existing is altered
(DEC-0181). Not changed: the approval flow, reinstatement, deactivation.

### DEC-0235 — Invoices follow the Solaris Invoicing desk rules (owner Ben, 2026-10-24)

Owner Ben confirmed on 2026-10-24 that domestic courier rates **include** GST/HST and that the
CRM must mimic the **Solaris Invoicing** desk. An invoice issued from now on, and every draft
invoice, follows the desk's rules; nothing issued before is rewritten.

**1. Tax treatment per invoice** (the route rule of DEC-0227 and the `tax_rates` table stay
the source of the rate). **International** (one end outside Canada: VN-CA, CA-VN, CA-US …) is
zero-rated: line amount = the rate, tax 0. **Domestic** (both ends in Canada): GST/HST is
**included** in the amounts and backed out at the **destination** province's rate (ON 13 % HST;
NS 14 %; NB, NL, PE 15 %; every other province and territory 5 % GST). **Added on top** stays
where it exists: a draft switched to "added", and the manual **Issue invoice** path with its
0 / 5 / 13 % picker (the owner decided earlier that direct issue is unchanged); the manual path
now prints on the new layout too. There is no "Sale of Product" in the CRM; none is invented.

**2. Per line, not per total** (replaces DEC-0223's whole-total back-out, in the draft totals
and on the issued invoice). For each line, `gross = qty × quoted rate` (a draft line has no
quantity: qty 1, gross = its amount; a manual-path quote line carries its quantity and its
amount is the gross); `net = round_half_up(gross / (1 + r), 2)`; `tax = round_half_up(net × r,
2)`; when `net + tax ≠ gross` the net is nudged by the cent difference so `net + tax = gross`
exactly; the Rate column is `net / qty` to 4 decimals (ROUND_HALF_UP). Subtotal = Σ net, tax =
Σ line tax, total = Σ gross (the original all-in total). **Added**: net = gross, tax =
round_half_up(net × r) per line. **Zero-rated**: tax 0. Example: 60 × 2.00 at 5 % → Rate
1.9048, Amount 114.29, GST 5.71, Total 120.00. One pure module, `invoice_tax_math`, does the
arithmetic for the draft (its totals, the confirmation echo, the audit), both issue paths, the
invoice document and the PDF, so what staff confirm, what is issued and what is printed agree.
Each surcharge stays its own line under the same rate.

**3. Storage, no schema change** (DEC-0181). An invoice issued from now on stores each line's
**net** in `customer_invoice_lines.amount_cad`, subtotal / tax / total as above, and in
`document_json`: `tax_layout: "invoicing_v1"`, `tax_mode`, `tax_lines` (per line `sequence`,
`quantity`, `unit_price_cad` (4 dp), `net_cad`, `tax_cad`, `gross_cad`, `tax_code`) and
`tax_rows` (`label`, `tax_cad`). An invoice without `tax_layout` (issued before) keeps its
stored gross lines and its figures and reads and prints exactly as before. Revenue
(profitability, close snapshots) stays the pre-tax subtotal; AR, receipts and payments read the
total as before.

**4. Labels, English only on documents.** The Tax column per line: 0 % "Zero-rated"; 5 % "GST";
13 % "HST ON"; 14 % "HST 14%"; 15 % "HST 15%"; another rate from the table "GST" when its label
is GST, else "HST r%". The summary rows: "GST @ 0%", "GST @ 5%", "HST ON @ 13%", "HST @ 14%",
"HST @ 15%" (another rate "GST @ r%" / "HST @ r%"); one row per distinct tax code. No "Prices
include …" sentence on the new layout; "included" never appears in the Tax column.

**5. The invoice PDF** (draft and issued, new layout): English for every customer and **no
Vietnamese accented text at all** — every printed string (bill-to, address, descriptions,
notes, PO) is transliterated (NFKD, combining marks dropped, đ → d, Đ → D). Columns Description
| Qty | Rate | Amount | Tax (Qty blank → 1). Summary Subtotal, the tax row(s), Total (CAD). The
company block: Solaris Express Inc.; 2446 Cawthra Rd Building 1 Unit 8, Mississauga ON
L5A 3K6; solarisexpressinc@gmail.com; GST/HST BN: 795093756RT0001; "Terms: Due on receipt"
when the due date is the issue date (`invoice_due_days` 0, the default), else "Terms: Net N
days"; "Currency: CAD"; "Payment: E-transfer to info@solarisexpress.ca" and "Wire: Bank of
Montreal, 2825 Eglinton Avenue West, Mississauga ON L5M 6J3 · SWIFT BOFMCAM2 · Account
1969380". Footer on every page: "Thank you for your business! We accept payment via E-transfer
to info@solarisexpress.ca". `finance_service.COMPANY` carries the new name, address and
`company_email` (the receipt and the printable quote follow, keeping their own language);
`PAYMENT` and `INVOICE_FOOTER` the payment lines. An older invoice's PDF keeps its old layout
and totals presentation (only the company's details are today's).

**6. Not changed.** The customer quote wording (OD-109 stand-in, DEC-0232: domestic "Prices
include HST 13 %", international zero-rated, tax-inclusive total) — Ben confirmed it. Refunds,
voids, payments, the confirmation rule (DEC-0223), the route rule (DEC-0227), the 0/5/13 manual
picker.

API: the draft view gains `tax_layout`, `tax_lines`, `tax_rows`; the staff invoice detail
gains `tax_layout`, `tax_rows` and per line `unit_price_cad`, `tax_cad`, `gross_cad`,
`tax_code`; the invoice document gains the same per line plus `company_email`, `tax_layout`,
`tax_rows`, `payment_terms`, `payment_etransfer`, `payment_wire`; the receipt and the quote
document gain `company_email`. Staff screens: the draft editor keeps the all-in amounts in
included mode and shows the saved draft "As the invoice will show it" from the server's
breakdown; the invoice detail and print page show the new columns for an `invoicing_v1`
invoice. Superseded assertion AS-43 registered. Stand-ins I-1 … I-13 (RC-UAT-23 notes).

### DEC-0236 — The legal entity on Settings and the label sender is Solaris Express Inc. (owner Ben, 2026-10-24, evening; I-10)

Ben (2026-10-24, about 21:37 ET): the Settings legal-entity name and the shipping-label sender
must say **Solaris Express Inc.**, matching the invoices (DEC-0235). Changed: the
`organization_settings.legal_entity_name` model default, the staff portal's `brand.legalEntity`
string in English and Vietnamese (the login footer), and the demo sender company in `seed.py` and
`scripts/render_sample_labels.py`. A data-only migration (`e7a9c1d3f5b6`) renames a settings row
that still holds **exactly** the old default "Soleil Global Transportation Inc." -- the Settings
screen shows the name read-only, so nobody could have corrected it -- and leaves any other value
alone; its downgrade reverses exactly that. No table or column changes (DEC-0181). Left as they
are on purpose: text that describes Soleil Global Transportation Inc. as the parent company
(`README.md`, `CRM.md`, Soleil's warehouse and mailbox comments) and historical decision and
record text. The printed label carries the "Solaris Express" wordmark and no legal name, as before.

### DEC-0237 — Invoice PDFs stay English only, with customer names without accents (owner Ben, 2026-10-24, evening; I-1)

Ben confirmed stand-in I-1 of DEC-0235: an invoice PDF in English only, with every printed string
transliterated without Vietnamese accents ("Phạm Thị Thu Trang" → "Pham Thi Thu Trang"), is
acceptable on a legal invoice. Nothing changes; the stored data, the staff screens and the
invoice email keep the diacritics.

### DEC-0238 — The cent nudge applies to tiny amounts too (owner Ben, 2026-10-24, evening; I-12)

Ben confirmed stand-in I-12 of DEC-0235: when net + tax differs from the inclusive amount, the
net moves by the cent, however small the line (0.04 at 14 % → 0.03 + 0.01). The arithmetic in
`invoice_tax_math` is unchanged.

### DEC-0239 — The draft editor's included-tax sentence uses the invoice's words (RC-UAT-24; I-11)

Optional polish Ben allowed (2026-10-24, evening). The staff draft editor said "Prices include
GST/HST 13 %: subtotal …"; it now says "Tax included in the price: subtotal before tax …, HST ON
@ 13% …, total …" ("Đã bao gồm thuế trong giá: tạm tính trước thuế …"), with the same summary
labels as the invoice (`summaryLabel` in `InvoiceDraftPage.jsx` mirrors
`invoice_tax_math.summary_label`: GST @ 5%, HST ON @ 13%, HST @ 14%, HST @ 15%). Customer quote
wording (OD-109) and the added-on-top and zero-rated sentences are unchanged.


### DEC-0240 — Required fields show a red asterisk, not "(required)" (owner Ben, 2026-10-25; RC-UAT-25 item 1)

Ben (live UAT, 2026-10-25): labels must not end in "(required)" / "(bắt buộc)". A required field
now shows a red `*` beside its label and no words, in the Staff Portal (Create booking and every
other form built on the staff `Field`, including the Operational timeline's **Record event** form)
and in the Customer Account (registration, sign in, forgotten and reset password, resend
verification, profile, sign-in and security), in English and Vietnamese. One shared component,
`src/shared/RequiredMark.jsx`, is used by both `Field` components; its colour is the new token
`--required-mark` (today `--danger-700`, #B42318, 6.5:1 on white). The star is `aria-hidden` and is
rendered **beside** the `<label>`, not inside it, so a field's accessible name is the label text
alone ("Email address"); "required" reaches assistive technology through `aria-required="true"` on
the control (set by the staff `Field` render props and, in the Customer Account, by `TextInput` /
`SelectInput` through a context). The staff `Field`'s visually hidden "(Required)" is removed for
the same reason. Optional fields keep a word under the field: the staff forms' existing "optional"
hint is unchanged; the Customer Account's "(optional)" / "(không bắt buộc)" moves from the label
to a helper line under the control ("Optional" / "Không bắt buộc", linked by
`aria-describedby`). No grey asterisk anywhere. This reverses the earlier rule that the Customer
Account states "required" in words (RegisterPage header comment updated). Table column values
"Required"/"Optional" in the import format tables are data, not field labels, and are unchanged.
Stand-ins RC25-A1 to A3.

### DEC-0241 — The booking's declared value currency is a list: CAD or VND (owner Ben, 2026-10-25; RC-UAT-25 item 3)

Create booking, step 2 **Route and service**: **Currency** (the declared value currency) is a
`<select>` instead of free text, with "—" (blank; the field stays optional), "CAD — Canadian
dollar" and "VND — Vietnamese dong" ("Đô la Canada", "Đồng Việt Nam"). The list is the CRM's own:
customer payments and vendor bills already accept exactly CAD and VND. The server holds it as
`booking_service.DECLARED_VALUE_CURRENCIES`, publishes it as `declared_value_currencies` in
`GET /shipments/meta` (the screen falls back to the same two codes until meta answers), and now
refuses any other code on draft create and edit (422, field `declared_value_currency`, "Choose
CAD or VND for the declared value currency.") — before, any three letters were accepted. The
shipment CSV import checks the same list per row (`invalid_currency`, "Use CAD or VND for the
declared value currency."). Lower case is accepted and stored upper case. A code stored before
the list (if any exists) is not a trap: re-sending it unchanged on an edit is accepted, a rebook
copies it forward, and the screen keeps it selectable on that draft. No default is filled from
the route: there was no existing route-to-currency rule to reuse. The shipment's recorded-amounts
currency on the Financials tab is a separate field (DEC-0246). Stand-ins RC25-A4 to A6.

### DEC-0242 — The recipient can use a saved address too (owner Ben, 2026-10-25; RC-UAT-25 item 4)

Create booking, step 3 **Sender and recipient**: the recipient card's **Use a saved address**
offers every saved address of the chosen customer except billing ones — recipient and "both"
addresses first, then sender addresses, each sender address marked "(saved as sender)" / "(lưu
là người gửi)" — with the hint "Every saved address of this customer except billing; the
customer's recipient addresses come first." Choosing one fills the recipient fields (name,
company, phone, email, both address lines, city, province or state, postal code, country,
delivery note) exactly as the sender picker does, and the booking stores a snapshot as before;
"Enter details manually" clears them. It reuses the existing customer address book
(`GET /customers/{id}/addresses`, archived addresses excluded) and the existing snapshot path
(`address_id`); the server already accepted any of the customer's addresses for either party.
Why the picker seemed missing: a Customer Account registration saves the customer's address as a
**sender** address only, so the recipient list (recipient/both only) was empty and the picker
was hidden for most customers. The sender picker is unchanged (sender and both). When the
customer has no usable saved address at all, both cards say "This customer has no saved address
yet. Enter the details below." Entering a new recipient does not add it to the address book.
Stand-ins RC25-A7, A8.

### DEC-0243 — The sign-in email is changed by an Admin only (owner Ben, 2026-10-25; RC-UAT-25 item 2)

- **Decision.** A customer can no longer change the sign-in email from the Customer Account.
  "Sign-in and security" shows the email read only, with "Only Solaris Express can change your
  sign-in email. Contact us and we will change it for you." / "Chỉ Solaris Express mới có thể
  đổi email đăng nhập của bạn. Hãy liên hệ với chúng tôi để được đổi." The password change stays
  as built in RC-UAT-21.
- **Customer API.** `POST /api/v1/account/email/change` stays mounted (an old page gets an
  answer, not a 404) and refuses every request with 403 and one sentence, after the session and
  CSRF checks and **before reading the body**: nothing is sent, nothing is written, and the
  answer is identical for every address (no enumeration). `POST /account/email/change/confirm`
  refuses **every** link with the generic token sentence; a live link is consumed and its
  request closed `refused` / `self_service_withdrawn` (audited `customer_account.email_change_refused`);
  the account, its sessions and its customer are untouched. `POST /account/email/change/cancel`
  still answers (it only closes). The Customer Account route table is unchanged (26 routes).
- **Requests and links already out.** Refused at confirmation (above). A request still pending
  is closed `cancelled` (reason `self_service_withdrawn`, audited) the next time the customer
  opens "Sign-in and security"; one never read again dies with its link at the end of the OD-36
  verification period. A password change or reset still closes it as before. No data step is
  needed. The landing page `/account/confirm-email-change` stays, says "This link no longer
  works" and sends the token once so the server closes the request.
- **Admin path.** `POST /api/v1/customer-account/identities/{reference}/sign-in-email` on the
  staff account screen ("Change sign-in email"), guarded by `customer_account:review` +
  `customer_account:deactivate` (Admin only, as reinstatement). Body: the new address, a reason
  code (`customer_request`, `mailbox_lost`, `entered_in_error`) and an optional note (≤ 500).
  The address is normalized (`normalize_email`); the account's own address, a malformed one or
  an unlisted reason is 422; an address held by another account or another customer record
  (merged tombstones excepted) is 409 with a staff-facing sentence naming which
  (`address_refusal`); the unique index decides a true race inside a savepoint (409). Allowed
  for pending-approval, active and suspended accounts; pending-verification, rejected and
  deactivated are refused (409). On success: the identity's address changes; the linked
  customer's email follows (single email rule, the same direct write as the approval); every
  outstanding email-change, password-reset and verification link dies; any pending customer
  request closes; **every** session ends; the old address gets the existing "sign-in email was
  changed" notice and the new address a new notice `account.sign_in_email_set_by_staff` with
  the sign-in link (both in the customer's language, capture only); the password is unchanged.
  Audited `customer_account.sign_in_email_changed_by_staff` with the identity and customer
  references, the reason code, the sessions-ended count and keyed `address_key` digests of both
  addresses (never an address, never the note); history row in `customer_account_email_changes`
  (migration `a5c7e9b1d3f6`).
- **Superseded.** DEC-0231's self-service email change (request, link, confirm, the request
  notice to the current address, the 3-per-hour limit), and with it the RC-UAT-21 stand-ins
  B-3, B-7 (the email-change limit), B-11 (email part), B-12 and B-14. Fourteen assertions
  registered as AS-44 to AS-57 in `docs/customer_account/SUPERSEDED_ASSERTIONS.md`. Stand-ins
  RC25-B1 to B6.

### DEC-0244 — "Received at Solaris" is shown as "Received at warehouse" (owner Ben, 2026-10-25; RC-UAT-25 item 5)

- **Decision.** The event type and operational state keep the stored code
  `received_at_solaris` (no data change, no migration). Every label reads **Received at
  warehouse** / **Đã nhận hàng tại kho**: `VALUE_LABELS` (staff API `event_type_label`), the
  staff catalogues (event types, operational states, the customer's milestone-email choices),
  the public tracking page and the Customer Account (status, milestone-email choice, the
  per-event sentences).
- **Standard update.** Template wording is immutable per key, so the new sentence is a new key
  `received_at_solaris.v2`: "We have received your shipment at our warehouse." / "Chúng tôi đã
  nhận lô hàng của bạn tại kho." It is the only one offered for the event type. The old
  `received_at_solaris.v1` ("…at our facility.") moves to the catalogue's new `retired` list:
  events that carry it still render what the customer was told, and it is never offered again.
  `check_catalogue` now refuses a retired key that is unknown or still offered.
- **Not changed.** The milestone email "received" copy ("Solaris Express has received your
  shipment … in Vietnam.") already names no Solaris facility; left as is. Seeds already write
  "Received at our warehouse. (demo)". Stand-in RC25-B7.

### DEC-0245 — A recorded timeline event can be corrected, published or not (owner Ben, 2026-10-25; RC-UAT-25 item 6)

- **Who.** Holders of `tracking:write` — Admin and Operations, the roles that record and void
  events today. Marketing and the read-only manager cannot.
- **What.** `POST /api/v1/shipments/{id}/events/edit` corrects one recorded event (all its
  package rows): event type, occurred-at (omitted = unchanged), packages (empty = every active
  package; a removed package's row is **voided**, an added package gets a row of the same
  recording), leg, location, country, internal note, and on a published event the
  customer-visible sentence. A reason (≤ 255) is required. Only live, staff-entered events; a
  provider event, a voided event, rows not recorded together, a cancelled booking, a future
  occurred-at, a foreign package or leg, or "nothing changed" is refused. The status is
  recomputed. The staff Operational timeline shows **Edit** on each live event with the warning
  "This event is already published to the customer. Your correction changes what the customer
  sees on the tracking page and in their account. No email is sent about it, and the change and
  your reason are kept in the edit history."
- **No silent rewrite.** An edit never publishes or unpublishes (telling the customer something
  new is a new event; withdrawing is a void). A published event's sentence can be changed
  **only to a standard update offered for its (new) type** — the publish flow's own catalogue
  and check; there is no approval step in the publish flow today, so none is added. Own wording
  already on the event can be kept but not rewritten. A retired standard update can be kept only
  while the type is unchanged. Every edit writes a `shipment_event_revisions` row (before and
  after, the rows touched, the reason, whether it was published and whether the wording changed;
  migration `a5c7e9b1d3f6`) and an audit row `shipment.event_edit` (revision id, rows, changed
  fields, before/after without free text, the reason, the actor).
  `GET /api/v1/shipments/{id}/event-revisions` lists the history (shipment readers); the
  timeline marks edited events and shows "Edit history".
- **Milestone emails.** An edit never queues, sends or withdraws a milestone email, even when it
  changes the type to a later milestone: the customer was emailed (or not) when the event was
  recorded, and a correction is not news. To email the customer, record the milestone as a new
  event. Stand-ins RC25-B8 to B13.

### DEC-0246 — The shipment Financials tab no longer blanks the page on a bad currency (owner Ben, 2026-10-25; RC-UAT-25 item 7)

Ben (2026-10-25) opened a shipment's Financials tab after adding financial info and the page went
blank.

**Root cause: one crash, two missing safeguards on the way to it.** (1) The crash: `formatMoney`
(`frontend/src/utils/format.js`) passed the shipment's recorded currency straight to
`new Intl.NumberFormat(locale, { style: 'currency', currency })`, which throws `RangeError:
Invalid currency code` for any value that is not three ASCII letters (`"CA"`, `"$"`, `"C$"`,
`"VN"`, `"12"`, `"CA "` and `" "` all throw; `"CAD"`, `"VND"` and `"cad"` do not). The
Financials tab renders every amount through it, so a stored code like `CA` threw during render.
(2) How such a code got stored: the tab's own **Recorded amounts** form had a free-text Currency
box (`maxLength={3}`, upper-cased, no format check), and the server accepted anything up to three
characters (`currency: str | None = Field(default=None, max_length=3)`, then `setattr` in
`update_financials` with no validation) — unlike the booking's declared-value currency. (3) Why
the whole page went blank, not just the tab: there was no React error boundary anywhere in
`frontend/src`; with React 18 an uncaught render error unmounts the whole root, so the header,
the tabs and the shell disappeared. Ben saved financial info on shipment 71 with a code that was
not three letters (the exact characters are unknown: stand-in RC25-C1); the save succeeded, the
refetched detail carried the bad code, and every later visit to the tab repeated the crash.
Every other financial shape checked (no master; amount only; unpriced; draft and finalised
quotes; manual, draft, legacy-layout and voided invoices; a VND vendor bill …) reads 200 and
renders without error.

**Decided.** The server accepts only a three-letter code for the recorded amounts (upper-cased;
blank means unknown, stored as null) and refuses anything else with 422, field `currency`, "Use a
three-letter currency code such as CAD." (`shipment_finance_summary_service.recorded_currency`,
called from `PATCH /shipments/{id}/financials`; nothing is half-saved); the screen checks the same
before saving; `formatMoney` no longer throws — a code stored before the fix is shown as entered
("CA 120.00") with a warning asking staff to correct it, never a crash; and each shipment tab
panel sits inside `PanelErrorBoundary`, which shows "This section could not be shown" with the
message and **Try again** (refetches the shipment), keeps the header and tabs, and logs the stack
to the console. No data is rewritten: a bad code already stored stays until staff correct it. No
table or column changes. Any three letters are accepted here, not only CAD and VND (the booking's
declared-value list, DEC-0241, is a separate field). Stand-ins RC25-C1 to C3.

### DEC-0247 — Quote, cost and invoicing on the shipment page (owner Ben, 2026-10-25; RC-UAT-25 item 8)

Ben (2026-10-25): after a shipment is created staff need a clear way to see the cost and invoice
the client right away. Decided: the Financials tab opens with a **Quote and invoice** card (read
from a new read-only `GET /shipments/{id}/financial-summary`, `financial:read`): the master, the
newest quote version still listed (Admin-deleted ones are not), its quoted revenue, and its vendor
cost and gross profit only for a role with `tariff:read` (the rule of the quote and vendor-bill
screens: Admin and Operations; the read-only manager sees revenue only; Marketing has no financial
access). One next step is shown: "Not in a master yet" (→ Workspace), "No quote yet — Price this
shipment" (→ the master's workspace), "Quote not finalised — Finalise quote", "The quote cannot
be invoiced — re-quote it" (expired or Admin-deleted quote), "Ready to invoice — Issue invoice"
(the manual path, `finance_service.issue_invoice`, with its 0 / 5 / 13 % picker,
`financial:write`), "Review draft invoice" (the draft prepared when the customer accepted) or
"Open invoice INV-…" with status and balance. While invoicing is blocked, Issue invoice is shown
disabled with the refusal Issue invoice itself returns (one shared check,
`finance_service.invoiceable_version`, so the words cannot drift; the refusals of `issue_invoice`
are unchanged word for word and in the same order). A role without `financial:write` sees the
button disabled with "Your role cannot issue invoices". The page header gains **Quote & invoice**
(any role with `financial:read`), a secondary button that opens the tab. Payments, refunds and
voids stay on the invoice page, unchanged. The recorded-amounts card stays below, as before. No
table or column changes. Stand-ins RC25-C4 to C7.

### DEC-0248 — Cost and quote method v0.5 is built behind a switch that stays on RC-UAT-25 (Louis, 2026-11-02; method step 1)

Louis (2026-11-02) confirmed `cost-quote-method.md` v0.5 and asked for step 1, backend only: the
new settings, the "packed as one box for Kango" package flag, the per-surcharge allocation class,
the engine and golden tests for scenarios S1–S5, with every existing function kept working.
Decided: the method is a second pure engine, `app/pricing/method_v05.py`, that reuses the
RC-UAT-25 pieces unchanged (`base_freight`, `_line_vendor_fee`, the 2/3 `_cost_split`, `allocate`,
`_piece_fee`, OD-50 `round_chargeable`) and returns the same `Estimate`, so reprice, confirm,
finalise, quote lines and snapshots work for both. `pricing_service.estimate_for` dispatches on
`pricing_method_settings.pricing_method`: `rc25` (seeded, the default) keeps every master on the
RC-UAT-25 engine exactly as before; `v0_5` prices with the method. The switch stays on `rc25`
until the v0.5 screens exist and the side-by-side UAT of the method's rollout step 4 is done, so a
tester never sees v0.5 figures under RC-UAT-25 wording. A snapshot priced under v0.5 records
`method` and the `v05` detail (FX source and rate used, allocation rows, reconciliation); an
RC-UAT-25 snapshot keeps exactly its keys. The method's own settings carry Louis's defaults: FX
Kango fixed 19,500 for cost and quote (reverses OD-54 under v0.5 only), leftover freight spread by
weight, per-box surcharges costed per small box and quoted in full to each trigger, whole-package
surcharges quoted with the cost share, markup none, Air Standard CAD 19/kg under 21 kg of the
customer's own rounded weight (CAD 18 from `pricing_settings` at or above), Sea CAD 8/kg, Air
Express and UPS manual.

### DEC-0249 — The v0.5 settings and per-master inputs are five new tables (method step 1)

Decided: `pricing_method_settings` (one row), `consolidation_package_flags` (keyed by master and
carton sequence, so the flag survives `replace_cartons`; sequence 1 is a one-package master's only
package even with no carton rows), `consolidation_manual_pricing`, `ups_rate_bands` (five empty
placeholder bands) and `surcharge_allocation_classes` (70 Kango rows from the 115-line
`data/surcharge_allocation_rules.csv`, keyed by section and row like `surcharge_rule_policies`, so
a class survives a new tariff version). Migration `b8d1f3a5c7e9`. Nothing existing is altered
(DEC-0181): the method doc's columns on `pricing_settings`, `packages`, `consolidations` and
`surcharge_rules` are these tables instead. No route is added in step 1.

### DEC-0250 — v0.5 cent rounding: each customer's cost half-up, the difference to the customer with the largest cost (method step 1)

The method doc says "CAD split by largest remainder"; the golden case study was computed by the
mockup engine, which rounds each customer's CAD cost half-up and puts the difference to the bill
(Σ customer CAD + unallocated CAD = bill CAD) on the customer with the largest VND cost. The two
differ in S3 (STCA-000203 153.24, not STCA-000202 98.16) and S5 (STCA-000205 57.75). Decided: the
golden figures, so S1–S5 reproduce to the cent. VND stays at cents (OD-60); the case study's VND
figures are the export's whole-dong rounding.

### DEC-0251 — v0.5 per-box surcharges: one Kango charge per small box, packed packages once (method step 1)

Decided: a PARCEL-class rule is charged once per small box holding the item (the item's package,
or the customer's only box), with the band on that box's rounded weight; a staff-entered carton
weight on the line still wins. When the master's package is marked packed as one box, the rule is
charged once on the package weight and split by weight among the triggering customers. On the
quote every trigger pays the full fee with the band on its own rounded weight. A master with more
than one package has no record of which customers are in which package: the packed flag is then
ignored with a provisional note, and whole-package rules use the master's bill weight, as
RC-UAT-25 already does.

### DEC-0252 — Method v0.5 is the default pricing method (Louis, 2026-11-03)

The owner confirmed the cost and quote method v0.5 as the source of truth. Decided:
`pricing_method_settings.pricing_method` defaults to `v0_5` (ORM default, the unsaved default in
`pricing_method_service`, and data migration `c2e4a6b8d0f1`, which sets the existing row to
`v0_5` on upgrade and back to `rc25` on downgrade). `rc25` stays a selectable value: the RC-UAT-25
engine and its snapshot keys are unchanged and still tested.

Consequences, now the expected behaviour (36 RC-UAT-25 tests updated to them, plus new tests
pinning the `rc25` path where a test was about an RC-UAT-25-only mechanism):

* Air Standard CAD 19/kg under 21 kg of the customer's own rounded weight, CAD 18/kg from 21 kg
  (3 kg: 54.00 → 57.00; 6 kg: 108 → 114; 12 kg: 216 → 228).
* Cost and quote convert at Kango's fixed 19,500 VND/CAD, not Vietcombank cash-buy (OD-73 under
  `rc25` only); a stale bank rate no longer blocks a quote unless a Vietcombank source is chosen.
  Customer payments in VND still convert at Vietcombank sell of the invoice date (finance
  unchanged).
* No OD-74 2 % default markup: the markup is the v0.5 setting (`markup_kind` none / fixed_cad /
  percent). The RC-UAT-25 `markup_defaults` row and its admin route are kept and still audited,
  but price only under `rc25`. A per-rule policy still wins under both methods.
* Whole-package surcharges bill non-triggers their 1/3 share (`pkg_surcharge_billing =
  same_as_cost`); `triggers_only` keeps the RC-UAT-25 billing.
* Air Express needs a manual vendor cost per master (`express_manual_cost_missing` blocks).
* The piece fee is its own fee line (key `PIECE`), so `Estimate.piece_fee_vnd` is 0 under v0.5.
* Rows the allocation CSV classes ITEM are priced on the item's own kg and need a weight on the
  line (HCM 22, HCM 41 meat — DEC-0222's full carton holds under `rc25`; open question M-3).
* The OD-48 "defaults pending owner confirmation" provisional note is carried into the v0.5
  engine.

Open questions M-1..M-12 (and Q1–Q9) are held; the step-1 stand-ins stay in force.

### DEC-0253 — Method v0.6 is the confirmed method; the switch value is `v0_6` (Louis, 2026-11-03)

`cost-quote-method.md` v0.6 (decision log §12, entries 12–25) is the source of truth. Decided:
`pricing_method_settings.pricing_method` takes `rc25` or `v0_6`; `v0_5` is accepted as an older
name and stored as `v0_6` (migration `d4f6a8c0e2b4` renames the row; downgrade renames it back).
A quote finalised from now on snapshots `method: "v0_6"`; earlier snapshots keep `v0_5`. The
engine module keeps its step-1 name (`app/pricing/method_v05.py`) and the estimate's detail key
stays `v05` so no consumer breaks; both are the v0.6 method. On the 2026-10-30 rates the v0.6
engine still reproduces every v0.5 golden row (`test_method_v05_golden.py`), so v0.5 → v0.6
differs in the figures by the rate sheet only. The RC-UAT-25 default markup (OD-74, 2 %) is
kept and labelled "RC25 method only" in `GET /pricing/settings` (`default_markup_label`,
`default_markup_in_effect`); it is retired for the confirmed method (Louis Q5).

### DEC-0254 — The 2026-11-03 Kango sheet is a new effective-dated tariff version (Louis Q1)

Decided: the sheet is imported by the normal importer (both origins, Air Standard and Air
Express, every zone: 41 per-bill bands 0.5–20.5 kg and 4 per-kg tiers per product and zone),
effective 2026-11-03, with `scripts/load_kango_rate_sheet.py --effective 2026-11-03 --activate`.
The committed copy is `backend/tests/fixtures/kango_canada_rates_2026-11-03_sanitized.xlsx`
(staff directory removed, header B1 blanked, by `scripts/sanitize_kango_workbook.py`). Prices are
stored as the sheet shows them (Numeric 14,2; the reader's floating-point noise such as
954,748.1499999 is absorbed by the column); all 180 Soleil-zone cells are checked against
`rates_2026-11-03.json`. A booked master keeps the version it was booked under (existing
`tariff_product_id` pin), so old masters keep the 12-Oct / 30-Oct rates. The 12-Oct fixture
stays for the RC-UAT-25 tests. Zone: L5A 3K6 → AIR-CAD zone 2, AIR-CAD EXPRESS zone 3
(`Zone CAD!N821:Q821`); the FSA lookup now removes spaces and upper-cases the postal code as the
sheet's formula `I3` does.

### DEC-0255 — Piece fee: lots of 21 kg and over, vendor cost only, by the carton's customers (Louis Q4)

Decided: each carton whose rounded chargeable weight is under 12 kg on a bill of 21 kg or more
(inclusive, as RC-UAT-25 already read OD-62) costs 300,000 (Air Standard) / 700,000 (Air Express).
It is a cost line only (key `PIECE`, never quoted); it is split by weight among the customers
recorded in that carton (DEC-0258), or among all the master's customers with a provisional note
when that is not recorded. Customer quote = 18 / 19 × own CW + surcharges. Sea has no piece fee.

### DEC-0256 — x.1 kg boxes follow the rounding rule (Louis Q6)

Decided: a per-box surcharge band reads the OD-50 rounded weight of the box Kango sees, for
cost and for quote (5.1 kg → 5.0 → 1–5 kg band, 300,000); a package packed as one box uses its
OD-50 weight for the band. Replaces DEC-0192 for box weights under the confirmed method. Kango
billing 500,000 shows as an estimate-vs-actual variance. **Not changed:** a carton weight staff
type on the fee line is used as typed, so the owner's battery groups (OD-59: 3.6 kg → 700,000)
stand. Open question for Louis: should a typed carton weight round too (3.6 → 3.5 → 300,000)?

### DEC-0257 — Sea: the sea vendor's rate and surcharges, minimum per package (Louis Q8, entry 25)

Decided: under the confirmed method Sea never reads the Kango sea sheet. Cost = sea vendor rate
× bill kg, any weight, no minimum weight, no piece fee; the rate is effective-dated in
`sea_vendor_rates` (60,000 VND/kg from 2026-11-03; a master uses the rate in force on its
booking or creation date). Sell CAD 8/kg × customer OD-50 CW. Surcharges are the vendor's
two, in `sea_surcharge_rules`, on a fee line with section `sea_vendor` (stt = rule id; item kg
required): SEA-FOOD 30,000/kg min 400,000, SEA-FUNCFOOD 40,000/kg min 500,000, at cost. New
class SEA ITEM + MIN: per package and type, total = Σ rate × item kg of that type's owners in
the package; total ≥ minimum → each pays the actual; otherwise the package pays the minimum,
split by item-kg share (largest remainder to the cent); the CAD leftover cent goes to the
largest-cost customer (DEC-0250). On a master with several packages the customer's package must
be recorded, else the line blocks (`sea_package_unknown`). Kango ocean surcharge rows on a Sea
master block (`kango_sea_surcharge_inactive`). Bill weight: the same Kango rounding as air
(open, method §11: confirm the sea vendor's rounding and divisor).

### DEC-0258 — Package customer note and the customer ↔ package record (Louis Q7)

Decided: two new tables (DEC-0181), not columns on `consolidation_cartons`:
`consolidation_package_notes` (`customer_note`, optional text ≤ 200, display only — the
`packages.customer_note` of the method doc) and `consolidation_package_members` (which package a
customer shipment rides in; optional). The record is needed only by per-package rules on a
master with several packages: the sea minimum, the piece fee's carton, and whole-package
surcharges (charged per package on that package's weight, 2/3 rule among that package's
customers); "packed as one box" stays one-package-only for now (provisional note otherwise).
Routes: `GET /consolidations/{id}/packages`, `PATCH .../packages/{seq}/note`,
`PATCH .../members/{shipment_id}/package` (fee permissions, audited). Origin and service were
already required at creation and editable until booking (OD-43); changing either re-prices the
live estimate; a service change revokes the rate confirmation, an origin change does not (the
customer's 18 / 19 price does not move; the cost and margin do).

### DEC-0259 — A per-kg surcharge with no special note is charged on the item's own kg (Louis, 2026-11-03)

Owner rule: any surcharge row charged per kg with nothing in the "ghi chú đặc biệt" (special
notes) column is charged per the item's own kg as is — e.g. HCM row 22, as meat (HCM row 41,
Louis Q3). Decided: under the confirmed method these rows are ITEM (rate × item kg, the owner
pays); on the 2026-11-03 sheet every such air row already is ITEM in
`surcharge_allocation_rules.csv`, and a test pins it. HCM row 14 (its note: full carton, not
split) stays WHOLE_PACKAGE. Supersedes DEC-0222 (meat on the full carton) for the confirmed
method; `rc25` keeps DEC-0222. Two per-kg rows are not in the CSV and do have notes (HCM 44 and
HAN 8, plants, UK/EU frozen only): both are imported as not applying to Canada and are refused,
so neither prices for Canada (corrected 2026-11-03; see DEC-0263).

### DEC-0260 — Method v0.7: sea food minimum on the quote per customer, on cost per package (Louis, 2026-11-03 PM, entries 27–28)

`cost-quote-method.md` v0.7 (decision log §12, entries 26–34) is the source of truth; the switch
value is `v0_7` (migration `e6a8c0e2b4d6`; `v0_5` / `v0_6` are accepted and stored as `v0_7`).
Decided for the SEA ITEM + MIN class (food 30,000/kg min 400,000; functional food 40,000/kg min
500,000): **quote**, per customer per type = max(own item kg × rate, minimum); **cost**, the sea
vendor's minimum once per package per type = max(Σ item kg × rate over that type's owners in the
package, minimum), split among them by item-kg share; the CAD leftover cent goes to the
largest-cost customer (DEC-0250). Quote − cost is surcharge margin. When which package a sea
customer is in is not recorded on a master with several packages, the whole master is one
package with a provisional warning (`sea_package_unknown`), no longer a block (replaces that part
of DEC-0257). Golden: `case_study_results_v0.7.json` S1–S7 (S1–S6 unchanged, S7 changed).

### DEC-0261 — Staff-typed carton weights keep their bands; origin keeps the confirmation (entries 26, 29, 31)

Confirmed by Louis: OD-50 rounding of a per-box band applies to system-computed box weights only;
a carton weight typed on the fee line is used as typed (OD-59 battery 3.6 kg → 700,000), to be
reviewed by Louis manually (closes the DEC-0256 question). Changing a master's origin re-prices
and keeps the rate confirmation; changing its service revokes it (as built, DEC-0258). Sea bill
weight: Kango's rounding and L × W × H / 6000 (closes the method §11 item).

### DEC-0262 — "Packed as one box for Kango" only on a master with one package (entry 30)

Decided: `replace_cartons` refuses a packed flag when it records more than one package, and a
master that comes to have several packages loses its flag; `set_package_flag` refuses `True`
unless the master has at most one package. The engine still ignores a stale flag on a
multi-package master, with its provisional note.

### DEC-0263 — Vietnam → Canada only: surcharge rows for other routes are excluded (entry 32)

Decided: a row whose note restricts it to other routes is excluded, never a fallback: it is
imported with `applies_to_canada = false` (HCM-44 and HAN-08 plants, UK/EU frozen; the SEA USA
section including A102 / A103), refused by the fee picker and blocked by the engine before any
allocation class is read; the rate-sheet diff lists them as `surcharges_excluded_non_canada`.
On mixed-route notes only the Canada rate is used (HCM-41 meat 20,000/kg, curated). HCM-22 is per
item kg (DEC-0259).

### DEC-0264 — Admin "Import Kango rate sheet": upload, diff, confirm, history, rollback (entry 33)

The CRM runs on Louis's PC, so he loads Kango sheets himself. Decided, on the existing tariff
tables (no schema change; `app/services/rate_sheet_service.py`):
`POST /tariffs/rate-sheet/import` parses the upload into a **draft** (both origins, both air
services, all zones, piece fees, FX line, Zone CAD, PHỤ THU) and returns its diff against the
active version — per origin / product / zone / kind (bands and tiers, with min / max delta), the
FX line, piece fees, zones (and the warehouse FSA's zones), surcharge rows added / removed /
changed, and the excluded non-Canada rows; nothing prices differently. Activation only on an
explicit confirm by a designated approver (`POST /tariffs/versions/{id}/approve`, OD-76).
`GET /tariffs/rate-sheet/history` lists every version with effective date, file name, SHA-256,
who / when imported and activated, and its lifecycle events. `POST /tariffs/versions/{id}/rollback`
re-activates an earlier (superseded) version (approver only, audited
`tariff_version.rolled_back`); the active one is superseded. Booked masters keep their pinned
version and finalised quotes their `tariff_version_id`. A re-upload of an identical file stays
refused (same SHA-256): rollback is the way back to it. `scripts/load_kango_rate_sheet.py` stays
the command-line loader. Demo / UAT seed (`app/seed_pricing.py`, used by the UAT seed) now loads
the 2026-11-03 sheet as the active version. Screen in step 2.

### DEC-0265 — Sea and UPS masters book without a Kango product; booking keeps the Kango bill weight (v0.6 fixes)

Found by Louis's review of v0.6. (1) `book_consolidation` resolved a Kango product for every
service, so Sea and UPS masters could not be booked ("Sea is deferred by owner decision OD-43").
Decided: under the confirmed method Sea (sea vendor rate) and UPS (manual) book with no vendor
product, divisor 6000; the stale OD-43 wording is replaced (the RC-UAT-25 method still refuses
them, now saying why). (2) Booking stored the OD-50 chargeable weight of the master's own
dimensions, which the method then used as the bill weight (20 + 21 kg on a 41.3 kg master:
42 kg / 10,920,000 VND open, 41.5 kg / 10,790,000 booked). Decided: under the confirmed method
booking stores `method_v05.vendor_bill_weight` — Σ the recorded packages' CW (else the master's
CW), Kango's rounding (method §6) — the same figure the open estimate uses, so an estimate is
identical before and after booking. RC-UAT-25 keeps its OD-50 figure.

### DEC-0266 — Routes for the method's inputs (v0.6 fix)

Inputs that had service functions but no route: `GET/PATCH /consolidations/{id}/manual-pricing`
(Air Express / UPS cost and sell; financial permissions), `GET/PATCH /pricing/method-settings`
(admin settings; `v0_5` / `v0_6` stored as `v0_7`), `PATCH
/consolidations/{id}/packages/{seq}/packed` (one-package masters only, DEC-0262) and `POST
/pricing/sea-cost` (dated sea vendor rate). Without the first, every Air Express master stayed
blocked on `express_manual_cost_missing` through the app.

### DEC-0267 — Version-neutral names for the confirmed cost and quote method (step 2)

The owner asked for the internal `method_v05` names to go. `app/pricing/method_v05.py` is now
`app/pricing/cost_method.py` (`estimate_method()`), `app/models/pricing_v05.py` is
`app/models/pricing_method.py`, and `is_v05` is `uses_confirmed_method`. The stored
`pricing_method` value is `confirmed` (or `rc25`); `v0_5` / `v0_6` / `v0_7` are still accepted
on input and stored as `confirmed`. Migration `f8b0d2e4a6c8` rewrites saved rows to
`confirmed` (downgrade writes `v0_7`). The method document's version is recorded separately
as `method_detail.method_version` (`"v0.7"`). The estimate key is now `method_detail` (was
`v05`); `pricing_service.snapshot_method_detail()` reads both, because frozen quote
snapshots are never rewritten. No pricing number changes: S1–S7 match
`case_study_results_v0.7.json` to the cent.

### DEC-0268 — Rate-sheet approver is a permission grant (`tariff:approve`), not an address

Owner decision (step 2, item 2): Ben and Louis T may both confirm or roll back a Kango rate
sheet, as a role/permission rather than a hard-coded address. New table
`staff_permission_grants` (migration `a1b3c5d7e9f2`, a new table only, DEC-0181) holds
per-account grants; `tariff:approve` is the only grantable permission. An approver is an
active user whose role carries `tariff:manage` (Admin) **and** who holds the grant: the
grant narrows the Admin role, as the old address list did, and never lifts a non-Admin
above their role. Admins (`staff:manage`) give and take the grant at
`POST/DELETE /staff/{user_id}/grants/tariff:approve` or on Settings → Kango rate sheets;
both are audited. Owner answer (2026-11-04): the migration seeds the grant **for Ben only**
(the current approver), even if a saved approver list names others; no address for Louis is
seeded or hard-coded, because his CRM account email is not confirmed. Louis is added later
by an Admin on the settings screen. An Admin saving the legacy `approver_emails` setting
still syncs the grants, so RC25 behaviour is kept. `scripts/grant_tariff_approver.py <email>` grants it from the
command line.

### DEC-0269 — The phase-15 quote leak scan ignores identifier values

`test_quote_offers_phase15::test_an_accepted_quote_is_listed_until_the_invoice_is_issued`
failed now and then because it searched the whole response text for forbidden words such as
`fx`, and a random public id or token could contain those letters. The scan now covers every
key and every text value except the values of identifier fields (`public_id`, `reference`,
`*_id`, `number`, `token`). A new test proves a forbidden word in a key or in ordinary text
is still caught.

### DEC-0270 — Step 2 screens for the confirmed method

Owner GO for step 2. The workspace gets: service (Air Standard / Air Express / UPS / Sea) and
origin (HCM / HAN) on the new-master form and the master edit form; a Cost vs quote panel
per master, per package and per customer (VND cost, CAD cost, CAD quote, profit, surcharge
margin, warnings, the rules behind each figure) with the customers listed in each package;
a Packages panel (short customer note per package, "packed as one box for Kango" on
one-package masters only, customer → package on multi-package masters); manual Express / UPS
cost and selling rate. Settings gets a Pricing method tab (the method settings and the dated
sea vendor cost; edits need `settings:manage`) and a Kango rate sheets tab (upload → draft →
diff → confirm or discard, history with rollback, approvers list). The old 2 % default markup
on the Pricing tab is labelled "RC25 method only". Every string is in English and
Vietnamese. The screens show what the server computed and do no pricing of their own.

### DEC-0271 — Kango Air Express priced on the rate sheet; a base cost override needs a reason

Owner (Louis, 2026-11-04), replacing the step-1 rule that Air Express is priced by hand: the
Kango Air Express vendor cost comes from Kango's Express table at the warehouse's Express
zone (L5A 3K6, Mississauga = zone 3), with the same bill-weight rounding, piece fee and
surcharge rules as Air Standard. Its selling rate is the one entered for the master, else the
Air Express default rate on Settings → Pricing; a customer's rate is still confirmed per
shipment as before. On any rate-sheet service (Kango Air Standard / Express, Sea) staff may
enter a different vendor base cost for a master; it needs a reason (refused with 422
otherwise), is audited with the reason, and the estimate carries a `base_cost_overridden`
warning. UPS and the new Air Cargo service (DEC-0272) stay priced by hand. S1–S7 are Air
Standard and Sea masters and do not change.

### DEC-0272 — Workspace redesign: master → pieces → customers; Air Cargo; staff service names

Owner outline (Louis, 2026-11-04). The workspace follows his order: master (master tracking
= `vendor_reference`, covering every piece; origin SGN / HAN; service) → master piece #1
(weights, CW, optional last-mile tracking, vendor base cost) → the customers inside it
(profile lookup or a quick new profile, reference code, weights → CW, items with
**suggested** surcharges that staff review and add, quote, confirmation) → add customer →
master piece #2 → … New: table `consolidation_piece_tracking` (migration `b2c4d6e8f0a1`, new
table only, DEC-0181) and `PATCH /consolidations/{id}/packages/{seq}/tracking`;
`POST /consolidations/{id}/customers` books the customer's shipment (draft → confirmed through
the booking service), joins it to the master and places it in the piece in one unit, keeping
nothing when refused. A piece's CW may be lower than its customers' total: shown as
information only. New service `air_cargo`, priced by hand like UPS. Staff screens name the
services "Kango Air Standard", "Kango Air Express", "UPS", "Air Cargo", "Sea"
(`STAFF_SERVICE_LABELS`); customer-facing names never mention the vendor (DEC-0222). Item
surcharge suggestions are computed in the browser from the rule names and notes and never add
a fee by themselves (owner decision 4).

### DEC-0273 — Workspace, owner review round 2: two-part new master, items at add, edit, collapse

Owner review (Louis, 2026-11-05) of the redesigned Workspace; Workspace tab only.

- **New master in two parts**: part 1 is the shipment (master tracking, origin, service); part
  2 is the list of master pieces, as many rows as the shipment has (each becomes a carton).
- **"Master" card is now "Shipment"**; "Book with vendor" moved to a bar fixed at the bottom
  with "Save and close" (every change is still saved by its own button; this refreshes and
  returns to the list).
- **Collapsible sections** with a one-line summary: pieces, customers (collapsed when a piece
  has several), cost vs quote, vendor bill, milestones; "Expand all" / "Collapse all".
- **"Packed as one box for Kango" and the per-package customer note are no longer shown** in
  the workspace: each master piece is the box Kango receives and lists its customers. The
  stored flags and the backend routes are unchanged, so no pricing number moves; the global
  "Per-box fee, cost" setting (Settings → Pricing method) still decides whether per-box fees
  count small boxes or packages.
- **No "Contents" field**: adding a customer takes its item list (name, quantity, optional
  kg); the booking's contents line is written from the item names, and the items are created
  in the same unit as the booking (`POST /consolidations/{id}/customers` with `items`).
- **Edit customer**: `PATCH /consolidations/{id}/customers/{shipment_id}` changes the
  reference code, the package weight and size and the piece; weights and piece follow the
  master lock (owner decision 8); sender and recipient stay locked after confirmation.
- **Remove item** in the workspace; its fee lines are removed first, so a removed item leaves
  nothing charged.
- **Surcharge list**: every Canada-applicable surcharge of the section is listed (it stopped
  at 12), with a count; the search also reads the vendor's note. Suggestions also match when
  the item name sits inside a rule phrase ("mỹ phẩm" → "Hàng Mỹ phẩm, TPCN"). A customer card
  is remounted when the master's origin changes, so no list from the other origin stays open.

### DEC-0274 — One "Cost and quote" card; no per-customer cost on screen

Owner review (Louis, 2026-11-05): the side "Vendor cost" panel and the "Cost vs quote" tables
are combined into one collapsible **Cost and quote** card: headline figures (vendor bill
weight, vendor cost, quote, profit, surcharge margin), the vendor cost of the whole master
(base freight with its basis, piece fee, surcharges, total, FX), the quote by customer
(weight, rate, quote) and, on a multi-piece master, the weights and quote by piece. The
owner's point: the vendor's base rate is charged on the **master pieces**, not on each small
box, so the workspace no longer shows a cost or profit per customer (or per piece); the
customer card shows its rate, freight, surcharges and quote instead. **Display only**: the
pricing engine still allocates cost to customers internally (it drives the per-quote
negative-margin check and the S1–S7 figures, which do not change). Whether that internal
allocation should change is an open question to the owner.

### DEC-0275 — Item weights for surcharges; the battery rule banded on the battery item

Owner review (Louis, 2026-11-05), confirmed method only (the RC-UAT-25 engine is unchanged):

- **Per-kg surcharges use the item's weight.** A per-kg rule (e.g. HCM-32 "Đông y, thuốc nam,
  thuốc bắc", 30,000 VND/kg) on a fee line with no weight of its own now takes the weight
  entered on the item, as `data/surcharge_allocation_rules.csv` says ("rate × item kg",
  ITEM_OWNER). Sea vendor surcharges (per item kg) do the same. A weight typed on the fee
  line still wins; with no weight anywhere the line still asks for one.
- **Battery with a small device (HCM rows 2–3, the OD-59 tiers)** is banded on the **battery
  item's own weight**, not the customer's box or the carton (2 kg → 300,000; 3.6 kg →
  700,000; over 8 kg a manual quote). Kango charges it **once per master piece** that holds a
  battery, on the heaviest battery item there; the customer with the battery pays the full
  fee (100%); when several customers in one piece have batteries, the cost is split among
  them by weight and each one's quote is the full fee on its own battery item. This
  replaces the "carton weight" reading of OD-59 for this rule.
- The fee picker labels the battery field "Battery item weight" and fills it from the item;
  a fee line without its own weight shows the item weight it uses.

S1–S7 contain no such line without a weight and do not change.

### DEC-0276 — Kango surcharges charged per master piece or per shipment

Owner analysis and answers (Louis, 2026-11-06; doc "Kango surcharges (phụ thu): grouping and how
cost and quote are calculated"), confirmed method only, air Vietnam → Canada only:

- **Per master piece (class PARCEL: HCM-01 nail polish, HCM-11 perfume, HCM-02/03 battery,
  HCM-04, 12, 13, 28; HAN-07, 09, 10).** "Kiện" is the master piece. COST: Kango charges once
  per master piece that holds the item type; a banded fee picks its band on the **total kg of
  that item type in the piece** (owner's Case 2: 3 + 4 = 7 kg → 500,000); a flat fee is the flat
  amount. The cost is shared among the customers with the item by their item kg. QUOTE: each
  customer with the item pays the full fee, band on its own kg (Case 2: 300,000 + 300,000).
  Replaces the per-small-box reading (v0.5 §10) and DEC-0275's "heaviest battery item"; the
  "packed as one box" flag and the "Per-box fee, cost" setting no longer change these fees.
- **Rounding (A3):** the item-type kg is rounded by OD-50 before the band (5.1 kg → 5.0, first
  band; 5.2 kg → 5.5, second band). The battery rows keep OD-59's 0.1 kg reading (3.6 kg →
  700,000).
- **Weights:** the item's weight (or a weight typed on the fee line). A banded fee on an item
  with no weight asks for it; a line with no item (older bookings) reads the customer's small
  box. More kg of one type in a piece than the top band (30 kg) is flagged "confirm Kango's
  price, or pack it in another piece". A customer not placed in a piece on a multi-piece
  master: the whole master counts as one piece, with a warning.
- **Per shipment (class LOT: HCM-47 fumigation, "lô hàng" = the whole shipment):** 550,000 once
  for the shipment; every customer with wooden items is billed 550,000; the cost is shared
  among them by weight. Replaces the 2/3 split for this row.
- **HCM-14 (A2)** keeps its rule: full-box kg, 2/3 trigger rule, quote = cost share.
- **Fee picker:** shows the per-piece / per-shipment rule; asks "Weight of this item" for a
  banded fee, no quantity for a per-piece fee (bottles for perfume). The surcharge list API
  returns `allocation_class`.

S1–S7 do not change (their nail-polish lines give the same figures under the new rule).

### DEC-0277 — Workspace in two panes, with data checks

Owner (Louis, 2026-11-06) chose direction B from the three drafts and its demo. Workspace tab
only; no API, pricing or other tab changes.

- **Layout:** a summary bar (AWB, origin · service, master CW, cost, quote, profit, "Complete:
  x/y customers", Save and close, Book); on the left the master's structure (Shipment →
  Piece n with its customers and "+ Add customer" → customers not in a piece → "+ Add master
  piece" → Cost and quote, Vendor bill, Milestones and closing); on the right the one thing
  selected. The selection is in the address (`?sel=c123`, `p1`, `add1`, `cost` …).
- **Same components:** every right-hand screen is the component the workspace already had
  (MasterPanel, MasterLockPanel, PieceSection, CustomerCard, AddCustomerForm, AttachBooking,
  AddPiece, CostQuotePanel, VendorBillPanel, MasterActionsPanel); their rules are unchanged.
- **Data control:** each customer's state in the tree (missing information / not quoted /
  draft quote / quote finalised) and its count of things to fix, from the server's estimate
  (blocking and provisional issues per shipment), its piece placement and its quote versions;
  "Check before booking" on the Shipment screen lists every problem with "Go to ›"; Book with
  problems open asks for confirmation and lists them ("Go and fix" / "Book anyway"); typing on
  a screen and leaving it without saving asks first; previous / next customer buttons; the
  piece screen shows its customers' table (CW, surcharges, quote, status, totals) and the
  surcharges charged per piece (DEC-0276).
- "Expand all / Collapse all" and the bottom bar are gone (one thing at a time; Book is on the
  summary bar).
