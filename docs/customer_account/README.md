# Customer Account — Phase 8 requirements

**Phase 8 is documentation and design only.** No application model, migration, API route,
authentication code, frontend screen, cookie, email integration, dependency, provider
adapter or UniUni code is added by this phase. Every file listed below is prose.

---

## 1. The three surfaces, and the names for them

| Name | What it is | Status |
|---|---|---|
| **Staff Portal** | The existing internal CRM. "Portal", unqualified, means this and only this. | Built, Phases 1–7 |
| **Public Tracking** | The existing unauthenticated tracking page and its 24-field contract. | Built, Phase 3 |
| **Customer Account** | The new **authenticated customer self-service** surface. | **Requirements only** |

**The new surface is never called "the portal."** Not in code, not in documentation, not in
a commit message, not in customer-facing copy. The word is already taken by the staff
application, and a document in which "the portal" means two different things is a document
in which an authorization rule can be read two ways.

Nothing is shared across the three surfaces that could make one of them speak for another:
**not one cookie, not one response schema, not one authorization dependency, not one session
realm.** Each of those is stated as a hard constraint in
[`IDENTITY_AND_AUTHORIZATION.md`](IDENTITY_AND_AUTHORIZATION.md) and
[`SESSION_COOKIES_AND_CSRF.md`](SESSION_COOKIES_AND_CSRF.md), and each is a test in
[`ACCEPTANCE_CRITERIA.md`](ACCEPTANCE_CRITERIA.md).

---

## 2. What the owner authorized, exactly

The owner lifted **one** deferral: the `CRM.md` deferral of an authenticated customer
self-service surface, for a limited first release.

**Authorized in release 1**

* A customer may **register** an account.
* A customer may **submit customer and profile information**.
* A customer may **view their authorized shipment history and tracking**.

**Not authorized, and still deferred**

* **Public booking** — deferred, unchanged by this decision.
* Booking **creation** or **cancellation** by a customer.
* Any **staff function**.
* Any **financial** access — cost, revenue, price, invoice, balance, payment.
* **Recipient accounts** — recipients continue to use Public Tracking (OD-30).
* **Provider synchronization** — no adapter, no provider request, no webhook (DEC-0075).

A capability that is not on the authorized list is out of scope. The list is not a starting
point to grow from during implementation; growing it is a new owner decision.

---

## 3. The contradictions this phase is required to resolve, resolved

**3.1 The owner has lifted only the Customer Account deferral.** The lift is specific. It
does not reopen booking, provider work, recipient access, or anything else `CRM.md` defers.

**3.2 Public booking remains deferred.** A customer with an account can see what was booked
for them. They cannot book, and the Customer Account contains no path toward booking in
release 1 — no draft, no quote, no "request a pickup" form.

**3.3 `CRM.md` remains a historical owner brief and is not silently rewritten.** It is the
owner's brief of September 2026 and has been untouched since Phase 1, through seven phases
and every decision recorded since. Its section on deferred scope still says the customer
portal is deferred, **and that remains a true record of what was asked for then**. Under this
project's conventions an owner decision is recorded in `docs/DECISIONS.md` and
`docs/OWNER_DECISIONS.md`, not by editing the brief so that it appears always to have said
the current thing.

**3.4 The decision log supersedes that one deferral, for this later phase.** OD-23 through
OD-39 in `docs/OWNER_DECISIONS.json` are the authority for the Customer Account.
Where `CRM.md` and the register disagree **about this surface**, the register is later and
governs; where they disagree about anything else, they do not disagree, because nothing else
was lifted.

**3.5 `Design.md` needs a new Customer Account section.** It has none: its fourteen product
sections cover the Staff Portal and Public Tracking. `Design.md` is an owner-supplied design
specification (version 1.0, September 2026) of the same standing as `CRM.md`, so this phase
**proposes** that section as a separate document —
[`DESIGN_SECTION_PROPOSAL.md`](DESIGN_SECTION_PROPOSAL.md) — for the owner to accept, rather
than editing the brief in place. Until it is accepted, no Customer Account screen has an
approved visual specification, and that is a launch blocker for the frontend phase, not for
this one.

**3.6 Customer Account is mobile-friendly, and is not Public Tracking.** `Design.md`
section 2 sets "desktop first for staff, mobile first for public tracking". The Customer
Account is **mobile-friendly** — a customer checking a shipment is usually on a phone — but
it is a distinct surface with its own navigation, its own authenticated state, and its own
screens. It does not reuse the Public Tracking page, its components, or its layout rules by
default.

**3.7 The public 24-field contract does not expand.** `PublicTrackingResult` stays at
exactly 24 fields. The Customer Account gets its **own** detail schema, declared field by
field, which *initially* carries the same 24 values — declared separately, not inherited.
The two contracts may diverge later in either direction, and the whole point of declaring
them separately is that neither can move the other by accident.

**3.8 Customer Account history does not replace Public Tracking.** Public Tracking stays
exactly as it is: unauthenticated, reference-based, for anyone holding a reference —
including every recipient, who gets no account in release 1. The Customer Account is an
addition for the person who shipped.

---

## 4. Deliverables in this phase

| # | Deliverable | File |
|---|---|---|
| 1 | Customer Account product specification | [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) |
| 2 | Identity and authorization architecture | [`IDENTITY_AND_AUTHORIZATION.md`](IDENTITY_AND_AUTHORIZATION.md) |
| 3 | Field-by-field customer data matrix | [`FIELD_MATRIX.md`](FIELD_MATRIX.md) |
| 4 | Authenticated shipment list and detail allowlists | [`SHIPMENT_ALLOWLISTS.md`](SHIPMENT_ALLOWLISTS.md) |
| 5 | Proposed relational model and data dictionary | [`DATA_MODEL.md`](DATA_MODEL.md) |
| 6 | State machines | [`STATE_MACHINES.md`](STATE_MACHINES.md) |
| 7 | Threat model | [`THREAT_MODEL.md`](THREAT_MODEL.md) |
| 8 | Rate-limit and abuse-control design | [`RATE_LIMITS_AND_ABUSE.md`](RATE_LIMITS_AND_ABUSE.md) |
| 9 | Cookie, CSRF and session separation | [`SESSION_COOKIES_AND_CSRF.md`](SESSION_COOKIES_AND_CSRF.md) |
| 10 | Email-delivery abstraction and development capture | [`EMAIL_DELIVERY.md`](EMAIL_DELIVERY.md) |
| 11 | Owner-decision records OD-23 … OD-39 | [`OWNER_DECISIONS_23_39.md`](OWNER_DECISIONS_23_39.md), and the register itself |
| 12 | Acceptance criteria | [`ACCEPTANCE_CRITERIA.md`](ACCEPTANCE_CRITERIA.md) |
| 13 | Existing UAT impact map | [`UAT_IMPACT_MAP.md`](UAT_IMPACT_MAP.md) |
| 14 | Proposed Customer Account UAT pack | [`../UAT/CUSTOMER_ACCOUNT_UAT_PACK.md`](../UAT/CUSTOMER_ACCOUNT_UAT_PACK.md) |
| 15 | Phased implementation plan | [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) |
| — | Proposed `Design.md` section, for owner acceptance | [`DESIGN_SECTION_PROPOSAL.md`](DESIGN_SECTION_PROPOSAL.md) |

---

## 5. Standing schema requirement (DEC-0089)

Every future schema phase — including every Customer Account implementation phase —
must end with **`alembic check` green** against a database at head, and must reach green by
making the models and the schema agree, never by widening the autogeneration exclusion.

The exclusion is one literal table name, `role_merge_provenance`, owned by migration
`a1c7f4d92b30`. **No Customer Account migration may drop, rename, map or repurpose that
table.** If a generated migration proposes touching it, the generation was run against a
tree where the hook was missing: discard it and regenerate.
`backend/tests/test_alembic_autogenerate_exclusion.py` fails if the exclusion set grows, and
`docs/OPERATIONS.md` section 11 is where the rule lives for whoever writes the next
migration.
