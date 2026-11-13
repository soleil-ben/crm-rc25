# Owner decisions OD-23 … OD-39 — Customer Account

**These are owner answers, recorded as decided. They are not recommendations, not options,
and not this project's proposals.** Decided **2026-09-19**.

The machine-readable records are in `docs/OWNER_DECISIONS.json`; the generated totals are in
`docs/OWNER_DECISIONS.md`. This document is the readable copy, with the consequence each
answer has for the work.

**What the owner authorized overall:** an authenticated **Customer Account** surface, in
which customers may register, submit customer/profile information, and view their authorized
shipment history and tracking. **Public booking is not authorized.** Booking creation,
cancellation, staff functions, financial access, recipient accounts and provider
synchronization remain outside this scope.

---

### OD-23 — Registration mode

**Approved.** Open registration with email verification **and** explicit staff approval.

Registration creates a **pending customer identity** and a **pending customer-data
proposal**. It must not directly create, overwrite, merge or link a canonical CRM customer.
An unapproved account cannot view shipment history. Generic responses must prevent
disclosure of whether an email address or a matching customer exists.

**Consequence.** Registration has no write path to `customers`. Every registration becomes
Operations queue work, and that cost is the price of never linking automatically.

---

### OD-24 — Account approval

**Approved.** Operations performs explicit account approval; Admin may also approve as an
override. **No automatic approval.**

Approval, rejection, linking and override actions must be audited **without** storing
passwords, tokens or unnecessary customer data in audit payloads.

**Consequence.** Two new staff permissions and an approval queue in the Staff Portal. No
timer, no rule and no bulk action may move an account to `active`.

---

### OD-25 — Account-to-customer cardinality

**Approved.**

* One customer identity links to **at most one** canonical customer in release 1.
* The data model must support **multiple identities linked to one customer later**.
* Release 1 permits only **one approved active customer identity per canonical customer**.
* **No identity may access multiple canonical customers** in release 1.

The future limitation must not be enforced through a schema design that would make later
company access require rebuilding identity ownership.

**Consequence.** The link is a separate table with partial unique indexes, not a column on
the identity. Relaxing to company access later drops an index and adds a role value.

---

### OD-26 — Company and multiple-user access

**Approved.** Deferred from release 1. Design the relational model to support multiple users
per company/customer later; do **not** implement invitations, company administrators, shared
access or multi-customer access in the first release.

---

### OD-27 — Customer-editable fields

**Approved**, with the field policy in full. The field-by-field table is
[`FIELD_MATRIX.md`](FIELD_MATRIX.md).

**Submitted during registration:** customer type; legal name; display name; primary contact
name; email; phone; preferred language; billing address; pickup/sender addresses;
notification preferences; explicit marketing-consent choice.

**Directly editable after approval, without staff approval:** preferred language;
non-marketing operational notification preferences.

**Proposals requiring Operations approval:** legal name; display name; primary contact name;
email; phone; billing address; pickup/sender addresses; customer type.

**Never customer-visible or customer-editable:** internal tags; lifecycle status; referral
source *unless explicitly collected during registration*; internal notes; interactions;
assigned staff; audit information; internal duplicate scores; suppression administration;
financial data; staff permissions; integration state.

**A customer cannot remove global suppression.** Marketing consent must remain explicit,
separate, **unchecked by default**, append-only and timestamped.

---

### OD-28 — Staff approval rules

**Approved.** Operations or Admin must approve every identity-sensitive or canonical
customer-data change. Preferred language and operational-notification preferences may apply
directly. **No automatic merge.** Exact and probable duplicates enter the **existing** review
process.

Approval must show: the proposed value; the current value; the normalized value where
relevant; duplicate implications; the affected account; the actor; the audit outcome.

---

### OD-29 — Shipment ownership and history

**Approved.** Shipment visibility is based **only** on the canonical customer's shipper
relationship. Do **not** authorize through email, phone, browser-supplied customer ID, or
possession of a tracking reference.

After account approval, historical qualifying shipments linked to that shipper become
visible. **Before approval, staff must see and explicitly acknowledge:**

* how many historical shipments will become visible;
* the oldest and newest shipment dates;
* whether cancelled or rebooked shipments are included.

Cancelled and rebooked shipments remain visible with safe states. Return event statuses
remain visible where already supported. Linked return-shipment records remain governed by
**OD-22**, which is still open.

---

### OD-30 — Recipient access

**Approved.** No authenticated recipient access in release 1. Recipients continue using
Public Tracking. Do not infer recipient ownership from recipient email, phone, address or
tracking-reference possession.

---

### OD-31 — Authenticated shipment field allowlist

**Approved.** Release 1 uses an authenticated shipment **list** containing only the minimum
safe list fields, and a **standalone** authenticated shipment-**detail** schema containing
exactly the existing **24** public-tracking fields initially.

The customer-account schema must be separately declared **field by field**. It must not
inherit from staff shipment schemas or public tracking schemas. **The public 24-field
contract remains unchanged.** The authenticated list may contain only safe identifiers and
summary fields needed to select one of the customer's authorized shipments, and every list
field and source column must be documented explicitly —
[`SHIPMENT_ALLOWLISTS.md`](SHIPMENT_ALLOWLISTS.md).

---

### OD-32 — Customer financial visibility

**Approved.** No financial, revenue, cost, profit, invoice, balance or payment information is
visible in release 1.

---

### OD-33 — Customer-account MFA

**Approved.** Optional TOTP, **disabled by default**, may be designed for the later hardening
phase. It is **not** part of the first customer-identity implementation phase. Customer MFA
must remain **separate from staff MFA decision OD-17**. The architecture must avoid
preventing required customer MFA later.

---

### OD-34 — Production email delivery

**Approved.** Development-only email capture may be used for implementation and testing. **No
production email provider is selected.** Production launch of customer registration is
**blocked** until an owner-approved provider is selected using verified documentation and any
applicable data-residency requirements. Do not send real email or integrate a provider in the
requirements phase.

---

### OD-35 — Deletion and privacy requests

**Approved.** Requests are **staff-executed and audited**. No self-service hard-delete button.
The process must support identity deactivation, access revocation, export/request handling,
and legally required deletion or correction where applicable.

**No compliance claim is made and no SLA is invented.** Legal review must determine the
applicable response period and retention exceptions.

---

### OD-36 — Customer-account retention

**Approved.** Align canonical data retention with **OD-01** when OD-01 is decided.
Verification and reset tokens must expire and become unusable promptly **regardless of
OD-01**. Do not implement canonical deletion schedules until OD-01 is answered. Proposed
retention categories are documented separately in [`DATA_MODEL.md`](DATA_MODEL.md) §10.

---

### OD-37 — Terms and privacy acknowledgement

**Approved.** Required during registration. The acknowledgement must be **versioned,
timestamped, append-only, tied to the customer identity**, and capable of recording the
**presented language and document version**.

Production registration remains **blocked** until approved legal text and version identifiers
are supplied. **No pre-checked consent.** Terms/privacy acknowledgement must remain separate
from marketing consent.

---

### OD-38 — Notification preferences

**Approved.** Preferences are explicit, separate and **unchecked by default**. Operational
notifications and marketing consent are separate concepts. A customer preference **cannot
remove or bypass global suppression**. Every consent change remains append-only and audited
under the existing privacy rules.

---

### OD-39 — Language launch policy

**Approved.** **English-only** for the first customer-account release. Vietnamese
customer-account UI remains **disabled** until a qualified reviewer approves:

* customer-facing UI;
* verification and password-reset messages;
* privacy and terms wording;
* operational notification wording.

Do not ship partially translated customer-account screens. Existing Vietnamese Public
Tracking remains governed by its existing documented status and **OD-09**.

---

### OD-40 — Linked-customer merge policy

*Answered 2026-09-20, after the seventeen above, to close the gate Phase 10 left open.*

**Approved.** A customer merge **must be refused** when either the source customer or the
intended surviving customer has an active Customer Account identity link.

The merge must **not**:

* automatically move the identity link;
* silently preserve a link on a tombstoned customer;
* expand the linked identity's shipment history;
* revoke the link automatically;
* suspend or deactivate the identity automatically;
* treat a merge as implicit approval of a new disclosure scope.

Return a safe **staff-visible conflict** requiring explicit Customer Account
reconciliation.

A future phase may implement a dedicated merge-with-account reconciliation workflow
containing a fresh duplicate review, a disclosure preview, an acknowledgement, session
handling and an explicit owner-approved link transition. **That workflow is not part of
Phase 10.**

**Why this policy is necessary**

* moving a link may expose a different or larger shipment history;
* **OD-29** requires explicit history-disclosure acknowledgement;
* the surviving customer may already have an identity;
* rollback and audit semantics differ among move, revoke and suspend;
* a tombstoned link is invalid;
* refusing the merge is the safest reversible behaviour.

**Where it is implemented.** `backend/app/services/customer_account_link_policy.py` holds
the definition of an effective link and the refusal;
`customer_service.merge_customers` enforces it centrally, before any write, for every
caller rather than only for the route (DEC-0107).

### OD-41 — Additional authenticated shipment-list filters

*Answered 2026-09-21, with the Phase 12 instruction, refining the release-1 filter set.*

**Approved.** Exactly **two** additional filters on the authenticated Customer Account
shipment list, and no others.

**1. Exact Solaris shipment reference.**

* exact match only, after the existing canonical normalization;
* only the customer's **own** Solaris shipment reference;
* **no** substring, prefix, fuzzy or general free-text search;
* **no** carrier tracking-number search;
* **no** package-reference search;
* **no** recipient name, email, phone or address search;
* bounded input;
* validation inside the established Customer Account error boundary, not a
  framework-generated constraint response;
* an unknown reference and a foreign one both produce an **empty list** with equivalent
  safe behaviour;
* malformed input cannot bypass the account read limiter;
* no ownership leak through counts, errors, headers or query order.

**2. Exact route group.**

* the existing validated route-group vocabulary only;
* no arbitrary SQL and no free-text value;
* an invalid value uses the established safe validation response;
* filtering stays scoped by the effective linked customer;
* no cross-customer counts.

Both must compose safely with the status and date-range filters.
[`SHIPMENT_ALLOWLISTS.md`](SHIPMENT_ALLOWLISTS.md) and the related requirements are amended
**before** the filters are implemented, and backend tests land **before** any screen
consumes them.

**Consequence.** `SHIPMENT_ALLOWLISTS.md` §3.2 previously approved two filters and declined
free-text search in as many words, so Phase 11 refused the reference and route filters its
own instruction named and recorded the refusal (`PROJECT_STATUS.md` §25.15). This decision
answers that refusal in the narrow form: exact match, on values the list already returns,
applied after the ownership clause so they can only narrow. **It does not reopen free-text
search**, which stays declined, and it adds no field to the 17-field list allowlist.

---

---

## What these answers change about the register

| | Before | After |
|---|---:|---:|
| Records | 22 | **41** |
| Answered | 0 | **19** |
| Open | 22 | **22** |

**No previously open decision was answered by this phase.** OD-01, OD-06, OD-08, OD-09,
OD-17, OD-18, OD-19, OD-21, OD-22 and the rest remain exactly as they were. Three of them
now also constrain the Customer Account:

| Still open | Effect on the Customer Account |
|---|---|
| **OD-01** — retention periods | Canonical retention cannot be implemented (OD-36) |
| **OD-22** — return workflow | Linked return-shipment records stay governed by it (OD-29) |
| **OD-09** — Vietnamese wording | Unrelated to the English-only launch, but the same reviewer question recurs in OD-39 |
| **OD-17** — staff MFA | Explicitly **not** answered by OD-33, which is about customers |
