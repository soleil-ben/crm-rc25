# Product specification

Working scope for the Solaris Express CRM, distilled from `CRM.md` into what is built,
what is deferred, and the definitions the numbers depend on.

`CRM.md` remains the source of truth. Where this file summarizes, `CRM.md` governs.

---

## 1. Purpose

One system serving three needs:

1. A secure internal staff portal for customer records, segmentation, follow-ups, and
   later shipments, labels, and tracking.
2. A public Solaris-branded tracking page (Phase 3).
3. A durable link between customer history and shipment activity, so staff know who to
   follow up with, who ships repeatedly, who is going quiet, and which route each
   customer prefers.

The goal is a practical operating tool for retention and service. It is deliberately not
a freight TMS, an accounting system, an ad platform, an inventory system, or a marketing
automation suite.

Primary audience: individual parcel shippers, including English- and Vietnamese-speaking
customers. Secondary: small businesses and online sellers.

---

## 2. Scope

### Built in Phase 1

Customer database with duplicate review and merge · address book · interaction timeline ·
follow-up tasks · consent history and suppression · tags · referrals · derived activity
metrics and lifecycle status · saved dynamic segments · dashboard from real queries ·
staff authentication with four roles · audit log · permission-gated CSV export ·
English-first localization-ready UI.

### Built in Phase 3

Public English/Vietnamese tracking at `/track` and `/track/:reference`, outside the staff
session · a separate public API with an explicit response allowlist and standalone schemas
· exact lookup on a parent Solaris ID or a package reference with forgiving normalization
and strict validation · one generic failure for invalid, unknown, draft, and
production-demo lookups · a sanitized timeline reading only approved public updates ·
honest tracking states with no synchronization claim · a validated, never-fetched carrier
link · public rate limiting with `Retry-After` · cache, referrer, robots, frame, and
permissions headers · no third-party resource of any kind, with self-hosted fonts. See
section 8.

### Built in Phase 2

Four route groups with server-enforced direction validation · draft bookings that carry no
customer-facing identifier · transactional confirmation issuing a permanent Solaris
Shipment ID · idempotent, concurrency-safe confirmation · route locking and an audited
cancel-and-rebook · sender and recipient address snapshots · multi-package records with
stable references and dual-unit measurements · ordered transport legs with package
associations and retired-or-active carrier reference placeholders · manual operational
events with separate occurred and recorded times and a separate approved public update ·
derived package progress and overall status · internal 4 × 6 label PDFs with Code 128 and
QR, single, selected, batch, and reprint · reprint history · internal barcode and
reference search · the six-step booking workflow and shipment detail screens.

### Built in Phase 4A — provider-neutral integration foundation

**No provider account is connected**, and no request has ever been made to a carrier or to
ShipStation by this application.

A durable webhook inbox with database-enforced deduplication and bounded payloads · an
authenticity boundary where a forged event is stored and never applied, and an unsigned
notification may only enqueue an authenticated read · a durable job queue with an atomic
claim, expiring leases, bounded retries, `Retry-After` handling, and a failed-job review
queue · at most one pending refresh per tracking assignment · a normalized provider-event
layer preserving raw provider status for audit without ever publishing it · provider events
applied through the existing Phase 2 status reducer, so every invariant still holds · a
narrow adapter contract describing capabilities, with an **empty** production registry · a
tested SSRF policy that makes no network request · a `--once` worker with redacted logs ·
permission-gated integration health reporting `not_configured` and explicit absences.

### Built in Phase 5A — reporting, CSV export, and CSV customer import

Nine server-calculated reports over a bounded, validated period cut at local midnight in
the organization's timezone · every metric reconciled in tests against an independent
calculation · no comparison, trend, or percentage-change figure anywhere, because none can
be honestly derived from one period · the financial report absent rather than masked for a
role without financial access, and cost columns absent rather than null without cost access
· CSV exports for customers, shipments, packages, marketing-segment audiences, and report
results, each with an explicit column allowlist, streaming, formula-injection escaping, and
UTF-8 output that preserves Vietnamese · export permission enforced independently of record
access · a staged CSV customer import — template, field contract, preview, duplicate
review, explicit commit — where the preview writes nothing at all and the commit
re-validates the same file from scratch · idempotency on `(source_system,
source_record_id)` enforced by a partial unique index, so re-importing a file creates
nothing · probable duplicates held for a decision and never merged · consent deliberately
not importable · a Vietnamese staff catalogue at full key parity, awaiting owner
confirmation of the wording.

**Provider integration remained deferred throughout** (DEC-0075). No adapter was
registered, no allowlist was populated, no request was made, and no report displays a
carrier freshness figure.

### Planned

| Phase | Contents |
|---|---|
| 4B | The verified provider adapter itself: authentication, webhook receipt, event mapping, reconciliation, staff mapping UI, and `connected_api`. Blocked on nine questions about the real account (`docs/INTEGRATIONS.md` section 9) |
| 5 | Import/export and deduplication at scale, metric validation, security and workflow tests, label QA, backup/restore rehearsal, staff training, deployment proposal |

### Explicitly deferred

The owner marked **Lead & Marketing Information** as *Chưa cần bây giờ — not needed now*.
Lead Source, Acquisition Channel, First Contact Method, Campaign, and Interested Service
are absent from the interface. No lead pipeline, campaign builder, or attribution engine
exists. An extension point is documented (DEC-0025) without building empty navigation.

Also deferred: bulk email and SMS, automated promotional sequences, loyalty points,
referral rewards, online payment collection, courier rate shopping, postage purchasing,
full quotation workflows, accounting integrations, warehouse inventory, and customer
account registration.

The initial booking workflow is **staff-assisted**. A public booking application and
authenticated customer shipment history are later phases.

---

## 3. Route groups

Four launch route groups. The requested "modes" are route groups; actual transport mode
and service type are stored separately.

| Route group | Code | Shipment ID format |
|---|---|---|
| Vietnam → Canada | `VCA` | `SX-VCA-` + 12 characters |
| Canada → Vietnam | `CAV` | `SX-CAV-` + 12 characters |
| Domestic Canada | `CAD` | `SX-CAD-` + 12 characters |
| US Cross Border | `XUS` | `SX-XUS-` + 12 characters |

The 12-character suffix uses a cryptographically secure, unambiguous uppercase alphabet
(no I, O, 0, or 1). Public IDs never encode a phone number, name, timestamp, or customer ID.

### Route and direction matrix

Enforced on the server, so a bypassed frontend cannot book an out-of-scope lane.

| Route group | Permitted direction | Origin | Destination |
|---|---|---|---|
| `VCA` | Vietnam → Canada | VN | CA |
| `CAV` | Canada → Vietnam | CA | VN |
| `CAD` | Canada → Canada | CA | CA |
| `XUS` | Canada → United States **or** United States → Canada | CA / US | US / CA |

The direction is also checked against the sender and recipient country codes, so a
mismatched address is rejected rather than quietly accepted. **United States → United
States is out of scope**, is named explicitly in the error, and is never silently
classified as cross border.

`XUS` accepts an explicit direction; when none is supplied and the addresses uniquely
determine one, that direction is used (DEC-0042).

### Identifier lifecycle

| Event | Effect on the Solaris ID |
|---|---|
| Draft saved or edited | none — a draft has no ID |
| Confirmation | ID issued, exactly once, inside the transaction |
| Route correction | **not possible** — the route locks; use cancel-and-rebook |
| Cancel and rebook | original keeps its ID and meaning; the replacement gets a new one when confirmed |
| Cancellation | the ID retires with the record and is **never reused** |
| Carrier assigned, changed, or relabelled | none |
| Package cancelled or label reprinted | none, for either the shipment ID or the package reference |

Package references are `{Solaris ID}-{sequence:02d}`. Sequences are never renumbered, so
cancelling package 2 of 3 does not free `-02`. A package reference lookup resolves to the
same shipment and identifies which package was scanned.

---

## 4. Metric definitions

Every number in the product resolves to one of these. They are implemented once, in
`activity_service.py` and `dashboard_service.py`, and used everywhere.

### Qualifying shipment

An outbound customer shipment that is **confirmed**, has a **first physical handoff
timestamp**, is **not cancelled or voided**, and is **not a return**. Counted **once** at
the parent shipment level regardless of packages, legs, carrier labels, or duplicate
tracking events.

Drafts and label-created-only records do **not** qualify. A label-created event means
booking information was received, not that Solaris has the parcel. Returns stay linked to
their original shipment and do not count as another outbound purchase.

### Customer activity

| Metric | Definition |
|---|---|
| First / Last shipment date | Earliest / latest first-handoff timestamp among qualifying shipments |
| Total shipments | Count of qualifying shipments |
| Bookings | Non-draft bookings including cancellations — shown **separately** so demand is distinguishable from actual shipping |
| Delivered shipments | Qualifying shipments with a final delivery timestamp |
| Repeat customer | At least two qualifying shipments |
| Observed primary route | Most frequent route group among qualifying shipments; kept separate from the declared route |
| Referral count | Distinct referred customer records |
| Qualified referrals | Referred customers who completed a qualifying shipment |

### Lifecycle status

Configurable thresholds, defaulted to `CRM.md`: **New** = exactly one qualifying shipment
within 30 days; otherwise **Active** = shipped within 60 days; **At risk** = 61–90 days;
**Inactive** = over 90 days; **Prospect** = no qualifying shipments; **Archived** = manual.

These are initial business assumptions, not industry benchmarks. Administrators can change
them, and every definition is displayed in the interface. Service restrictions and
do-not-contact are stored independently of lifecycle status.

### Period repeat-shipper share

Customers who shipped during the selected period **and** hold at least two qualifying
lifetime shipments as of period end, divided by all customers who shipped during that
period.

This is **not** a cohort retention rate and is never labelled as one. Cohort retention is
a separate future metric.

### Financial rules

Revenue excludes sales tax. Gross profit is recorded revenue minus recorded direct costs,
**only** where costs are known. Missing values mean **Unknown**, never zero. Currencies
are reported separately and never combined without a recorded, dated conversion. Financial
data coverage is always displayed so partial records cannot masquerade as a complete
customer-value model.

### Observed versus declared

Declared shipping frequency and declared primary route are what the customer told staff.
Observed monthly shipments and observed route come from actual qualifying shipments in the
stated date range. The two are stored in different fields and displayed with different
labels, and neither overwrites the other.

---

## 5. Statuses

Booking state, operational state, payment state, customer lifecycle, task status, consent
status, and provider source are **distinct types**. They are never collapsed into one
ambiguous status field.

Normalized operational states (Phase 2–3): Booked, Awaiting parcel, Received at Solaris,
Processing, Departed origin, In transit, Customs processing, Arrived destination, Out for
delivery, Partially delivered, Delivered, Delivery attempted, Exception, Return in
progress, Returned, Cancelled, Tracking unavailable.

Two rules, now implemented in `event_service`:

- Delivery to an intermediate Solaris warehouse is a **milestone**, not delivery, when the
  customer's destination is elsewhere. Only a `delivered_to_recipient` event can complete a
  package; warehouse receipt, arrival at destination, and a collection-point handover are
  separate event types and the service refuses to flag them as final delivery.
- Overall **Delivered** requires final-recipient completion for all active packages. One
  of three delivered is **Partially delivered**, shown as "1 of 3 packages delivered".
  Cancelled packages are counted separately and never distort the ratio.

A package's state is the latest event by occurred time, so a late or older event cannot
regress a newer valid state. `occurred_at` and `recorded_at` are stored separately, so a
late entry is visible as one rather than passing for a fresh scan.

Route-specific timelines only. A domestic shipment must never display invented customs
milestones; map only what the source actually reports. Staff choose from a fixed vocabulary
of 15 event types, and nothing invents a milestone that was not entered.

### Internal labels

One portrait PDF page per selected active package, exactly 288 × 432 points, black and
white. Each page carries the route code and name, the Solaris Shipment ID, the package
reference, a Code 128 barcode of that reference, a QR pointing at the configured tracking
base, "Package 1 of 3", the booking date, the recipient and destination, gross weight in
the unit it was recorded in, optional handling note and warehouse location, and the fixed
warning **SOLARIS INTERNAL LABEL — NOT CARRIER POSTAGE.**

This supplements the carrier's own label. It is not postage, it never covers a carrier
barcode, and no courier's design is imitated. The system records that a PDF was generated
and downloaded; it does not know whether a printer produced anything.

---

## 6. Privacy and consent

- All CRM notes are internal. Public shipment updates are a separate concept requiring
  explicit visibility selection (Phase 3).
- Consent is an append-only event log per channel and address, with basis, evidence
  reference, and dates. A single overwritten checkbox is not acceptable.
- Suppression is global to a channel and address, so it survives merges and re-imports and
  cannot be cleared by writing a consent event.
- Unknown or imported contact information is **not** marketing eligible.
- Promotional eligibility is separate from operational contact preferences. A shipment, a
  referral, or receiving someone's parcel does not create marketing consent.
- A shipment recipient does not become a marketing customer. Booking customer, payer,
  sender, and recipient are separate concepts.
- Public tracking (Phase 3) returns an explicit minimal allowlist, never a serialized
  internal record.

CASL requirements must be verified against official CRTC guidance before campaigns are
implemented. Legal conclusions are not encoded into the CRM from assumptions.

---

## 7. Acceptance criteria

`CRM.md` section 17 lists twenty criteria. `PROJECT_STATUS.md` maps each one to its
implementation and validation status, marking which belong to later phases.

Phase 1 owns: AC-1 (persistence, validation, accents), AC-2 (server-side authorization),
AC-14 (shipment counting rules), AC-15 (dynamic segments, consent and suppression
survival), AC-16 (duplicate review, no blind merges), AC-17 (currency and unknown-value
handling), AC-19 (Vietnamese and English names in tests), AC-20 (clean-environment start),
and the customer half of AC-5 and AC-18.

Phase 2 owns: AC-3 (route prefixes, no duplicate bookings or IDs), AC-4 (three-package
label PDFs), the shipment half of AC-5 (snapshots survive an address-book edit), AC-6 (the
ID survives carrier assignment and relabelling), AC-7 (partial delivery), AC-8 (an
intermediate warehouse is not delivery), and the booking-to-label half of AC-18.

Phase 3 owns AC-12 (public lookups expose no private details), the public half of AC-18,
and the public-tracking half of AC-19.

Phase 4A owns the **infrastructure** halves of AC-9, AC-10, and AC-11, demonstrated
against a deterministic fake adapter rather than a provider:

* **AC-9** — duplicate webhooks create one inbox row, one normalized event, one timeline
  entry, one delivered count, no revenue change, and no follow-up task; older events do not
  overwrite newer valid state. Demonstrated including two concurrent deliveries from
  separate sessions.
* **AC-10** — a forged or unverified event cannot mutate shipment or package state, and the
  resource-fetch policy refuses every unsafe URL. **No network request is made at all**;
  the transport is injected and production supplies none.
* **AC-11** — a provider outage preserves the last known status, applies bounded retries
  with jitter, honours `Retry-After`, and produces at most one pending refresh per
  assignment.

**Still deferred**, and genuinely so: the *provider* halves of AC-9, AC-10, and AC-11 —
the same properties against a real account — and the connected-provider half of AC-13.
Each needs a verified adapter, which needs the nine answers in `docs/INTEGRATIONS.md`
section 9.

---

## 8. Public tracking (Phase 3)

A customer with a Solaris Shipment ID or a package reference — typed, pasted, or scanned
from a label's QR code — can see where their parcel is, in English or Vietnamese, without
an account.

### What it is

| | |
|---|---|
| Routes | `/track` and `/track/:reference` |
| API | `GET /api/v1/public/track/{reference}` |
| Authentication | none, and none is possible |
| Languages | English and Vietnamese, switchable on every screen |
| Lookup | exact match on a parent Solaris ID or a package reference; nothing else |

The exact response allowlist, the forbidden list, the normalization rules, and the
tracking-state vocabulary are in `docs/DATA_DICTIONARY.md`.

### What a customer sees

The Solaris Shipment ID; the route; coarse origin and destination city and country; the
normalized status with a text label; how many packages are active, cancelled, and
delivered; each package's reference and status, with the scanned one identified; the
approved public timeline; an honest statement of how the shipment is tracked; an estimated
delivery date only when one was genuinely supplied and always labelled as an estimate; and
a validated public carrier link only when one is safe to show.

### What a customer never sees

Their own name, the recipient's name, any address line, postal code, email, or phone; the
booking reference; any internal identifier; internal notes or event detail; any monetary
figure; carrier tracking numbers as a field; consolidation references; staff identities;
audit history; proof-of-delivery documents; or anything belonging to another customer.

`backend/tests/test_public_privacy.py` scans the raw JSON recursively for both forbidden
names and forbidden values, so a rename cannot make it pass.

### Status rules on the public page

The same rules the staff portal applies, because they come from the same service:

- Delivery to an intermediate Solaris warehouse is a **milestone**, not delivery.
- A collection-point handover is **Out for delivery** under the current documented
  default, not Delivered.
- One of three packages delivered is **Partly delivered**, shown as "1 of 3 packages
  delivered".
- Overall **Delivered** requires final-recipient completion for every active package.
- A cancelled package is counted separately and never distorts the ratio.
- A domestic shipment shows no customs milestone, because no customs event was recorded.
  Nothing invents a milestone to fill a visual gap.

### Honesty about tracking

Phase 4 provider synchronization does not exist, and the page says so rather than
implying otherwise. There is no "last carrier update", no "last successful synchronization",
and no freshness age anywhere in the response or on the page. Every event in the system was
typed by a person and is labelled "Manual update". A stored carrier link is displayed and
**never fetched**. Nothing polls anything.

The page states which of these is true for each shipment: updates entered by Solaris staff;
a carrier link only; no updates published yet; tracking unavailable; the booking was
cancelled; or demo data.

### Failure states

One response for every unsuccessful lookup — invalid reference, unknown reference, draft,
or a demo record in production. Same status, same body, same message, same headers, so a
lookup cannot confirm that an identifier exists. Rate limiting returns a generic 429 with
`Retry-After` and a customer-friendly wait message.

### Privacy of the page itself

`no-store`, `no-referrer`, and `noindex, nofollow, noarchive` on every public response and
on the page. A constant document title that never contains the reference. No third-party
font, script, stylesheet, analytics, error tracker, social widget, advertising pixel, or
embedded map. Nothing but the chosen language reaches browser storage — no reference, no
result. A failed lookup leaves no trace of a previous successful one.
