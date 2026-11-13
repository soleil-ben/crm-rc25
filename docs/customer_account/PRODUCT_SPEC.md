# Customer Account — product specification

**Status:** requirements only. Nothing described here is built.
**Authority:** OD-23 … OD-39. Where this document and the register differ, the register wins.

---

## 1. What this surface is for

A Solaris Express customer who has shipped with the company can create an account, confirm
who they are, ask for their customer record to be corrected, and look at the shipments they
sent. That is the whole of release 1.

The reason to build it is narrow and worth stating, because it bounds the design: today a
customer who wants to know where their parcel is either holds a tracking reference or
telephones. Public Tracking serves the first. The Customer Account serves the second — the
customer who has shipped nine times, holds none of the references, and wants the list.

**It is not a booking channel, not a payment channel, not a support inbox, and not a second
staff tool.**

---

## 2. Who can use it

| | Release 1 |
|---|---|
| A customer who has shipped with Solaris (the **shipper**) | Yes, after registration, verification and staff approval |
| A recipient of a shipment | **No** (OD-30). Public Tracking, as today |
| A company with several staff who ship | **One** account in release 1 (OD-25, OD-26). The data model must not prevent more later |
| A prospective customer who has never shipped | May register; sees no shipment history, because there is none linked |
| Solaris staff | Not through this surface. Staff use the Staff Portal |

---

## 3. The five things a customer can do

### 3.1 Register

Open registration (OD-23). The customer supplies the registration fields listed in
[`FIELD_MATRIX.md`](FIELD_MATRIX.md) section 2, an explicit terms and privacy
acknowledgement (OD-37), and an explicit, unchecked-by-default marketing-consent choice
(OD-27, OD-38).

Registration creates two things and **no third**:

1. a **pending customer identity** — an account that cannot yet sign in to anything useful;
2. a **pending customer-data proposal** — the submitted information, held as a proposal.

It does **not** create, overwrite, merge into, or link to a canonical CRM customer. Not
even when the submitted email matches one exactly. The link is an act of staff (OD-23,
OD-24, OD-28).

The response to a registration attempt is **generic** and identical whether or not the email
is already registered and whether or not it matches a customer (OD-23). See
[`THREAT_MODEL.md`](THREAT_MODEL.md) T-02.

### 3.2 Verify an email address

A hashed, single-use, expiring token is sent to the address (OD-23). Verification proves
control of the mailbox. It is **not** approval and grants no access to shipment history.

### 3.3 Wait for approval, then sign in

Operations — or Admin as an override — approves the account and links it to exactly one
canonical customer (OD-24, OD-25). Before approval the customer can sign in and see their
own submitted profile and the account's state; they see **no shipment history at all**
(OD-23).

### 3.4 View and propose changes to their own information

After approval:

* **Two fields apply immediately**: preferred language, and non-marketing operational
  notification preferences (OD-27, OD-28).
* **Everything else identity-bearing is a proposal** that Operations approves before it
  touches the canonical customer: legal name, display name, primary contact name, email,
  phone, billing address, pickup/sender addresses, customer type (OD-27).
* A long list of fields is **never visible and never editable** — internal tags, lifecycle
  status, internal notes, interactions, assigned staff, audit information, duplicate scores,
  suppression administration, financial data, staff permissions, integration state
  (OD-27). See [`FIELD_MATRIX.md`](FIELD_MATRIX.md) for the field-by-field table.
* A customer **cannot remove a global suppression** (OD-27, OD-38). A preference is a
  preference; a suppression is an operational control that outranks it.

### 3.5 View their shipment history and tracking

Visibility follows **one** rule: the shipment's shipper is the canonical customer this
identity is linked to (OD-29). Not the email on the shipment, not the phone, not a
customer id supplied by the browser, and not possession of a tracking reference.

Two screens:

* an **authenticated list** of that customer's shipments, carrying only the fields needed
  to choose one, filterable by status group, booking-date range, exact Solaris shipment
  reference and exact route group (OD-41) and by nothing else;
* an **authenticated detail** view of one of them, carrying a standalone allowlist that
  initially holds exactly the 24 values Public Tracking already publishes.

Both allowlists are declared field by field in
[`SHIPMENT_ALLOWLISTS.md`](SHIPMENT_ALLOWLISTS.md). Cancelled and rebooked shipments remain
visible with safe states; return event statuses remain visible where already supported, and
linked return-shipment records remain governed by OD-22, which is still open.

**No financial value appears anywhere on this surface** (OD-32).

---

## 4. What staff see and do

The Customer Account creates four new pieces of staff work, all inside the existing Staff
Portal, all audited, none automatic (OD-24, OD-28):

1. **Account approval queue** — pending identities, with the linking decision.
2. **Proposal queue** — customer-submitted changes to canonical data.
3. **Rejection and suspension** — with a reason code.
4. **Privacy and deletion requests** — staff-executed, never self-service (OD-35).

### 4.1 The approval screen must show, before the button is pressable

For the **link** decision (OD-24, OD-28, OD-29):

* the proposed values and the current canonical values side by side, plus the normalized
  value where normalization applies;
* duplicate implications from the existing duplicate-review service — exact and probable
  matches, in the existing review process, with **no automatic merge**;
* the affected account, the actor, and what will be written to the audit log;
* **the history disclosure preview**: how many historical shipments become visible, the
  oldest and newest shipment dates, and whether cancelled or rebooked shipments are
  included.

The preview is not decoration. Approval is the moment a person gains sight of records they
could not see before, and the approver should know the size of what they are opening.
Acknowledging it is an explicit step (OD-29).

### 4.2 What staff may never do from here

* Approve automatically, by rule, by timer, or in bulk without seeing each link (OD-24).
* Merge two canonical customers as a side effect of approval (OD-28).
* Reveal, in any customer-facing response, that a match exists (OD-23).

---

## 5. Language

**English only in release 1** (OD-39). The Vietnamese Customer Account UI stays disabled
until a qualified reviewer approves the customer-facing UI, the verification and
password-reset messages, the privacy and terms wording, and the operational notification
wording — all four.

Partially translated Customer Account screens do not ship. Existing Vietnamese Public
Tracking is unaffected and remains governed by its existing documented status and OD-09.

---

## 6. What this surface refuses to do

| Refusal | Why |
|---|---|
| Confirm whether an email is registered or matches a customer | Account and customer enumeration (OD-23) |
| Show a shipment because the caller knows its reference | Possession of a reference is not ownership (OD-29) |
| Show anything to a pending account | An unapproved account has no linked customer (OD-23) |
| Show a price, cost, invoice or balance | OD-32 |
| Let a customer merge, create or delete a canonical customer | OD-23, OD-28, OD-35 |
| Let a customer lift a suppression | OD-27, OD-38 |
| Send real email in tests or in the requirements phase | OD-34 |
| Grant access to a second canonical customer | OD-25 |

---

## 7. Release-1 screen inventory (proposed)

| Screen | Authentication | Notes |
|---|---|---|
| Sign in | none | Generic failure text only |
| Register | none | Terms acknowledgement, marketing consent unchecked |
| "Check your email" | none | Identical for every outcome |
| Verify email (token landing) | token | Single-use, expiring |
| Forgot password / reset | none / token | Generic response; token single-use, expiring |
| Account pending | identity session | State, and what happens next. No shipment data |
| My information | identity session, approved | Direct fields, proposal fields, submitted proposals and their state |
| My shipments (list) | identity session, approved | List allowlist only |
| Shipment detail | identity session, approved | Detail allowlist only |
| Notification preferences | identity session | Operational preferences direct; marketing consent append-only |
| Sign out | identity session | Revokes the session server-side |

No screen in this inventory displays another person's data, a financial value, or an
internal field.

---

## 8. Out of scope, recorded so it is not re-argued

Booking creation, booking cancellation, quotes, payments, invoices, document upload, support
ticketing, live chat, recipient accounts, company/multi-user access, invitations, address
books beyond the customer's own pickup/sender addresses, provider synchronization, push
notifications, SMS, a mobile application, and customer-visible staff notes.

Each of these is deferred, not rejected. Re-opening any of them is an owner decision with a
new OD number.
