# Customer Account — authenticated shipment list and detail allowlists

**Status:** requirements. **Authority:** OD-29, OD-31, OD-32, OD-22, **OD-41**.

**Amended 2026-09-21 by OD-41**, which approves two additional exact-match list
filters. The amendment is §3.2 and §3.3; everything else is unchanged, and in
particular the 17-field list allowlist and the 24-field detail allowlist do not move.

**Amended 2026-10-18 by the owner's UAT round 10 instruction (DEC-0156)**, which adds a
keyword search to the list (§3.2, §3.4). The two allowlists still do not move.

**Amended 2026-10-18 by the owner's UAT round 11 decisions (DEC-0160, DEC-0161)**: the list
gains `booking_reference` (§3, §3.1) and the search reads package references (§3.4).

**Amended 2026-10-19 by the owner's UAT round 12 decisions (DEC-0163, DEC-0164)**: the
detail gains `booking_reference` too, its 25th field (§4, §4.1), and cancelled packages
stay searched (§3.4). Public Tracking stays at 24.

---

## 1. The rule these allowlists exist to enforce

Two schemas, both **standalone**:

* `AccountShipmentListItem` — the list. Minimum safe fields, enough to choose a shipment.
* `AccountShipmentDetail` — one shipment. Initially **exactly the 24 values** Public
  Tracking already publishes, declared here field by field; since UAT round 12 those 24
  plus the customer's own `booking_reference` (DEC-0163).

Neither inherits from `ShipmentDetail`, `ShipmentListItem`, `PublicTrackingResult`, or any
other schema. Neither sets `from_attributes`. Both set `extra="forbid"`. Every value is
assigned explicitly by a service.

**The public 24-field contract does not expand** (OD-31). `PublicTrackingResult` is
untouched, and `backend/tests/test_public_contract_unchanged.py` keeps asserting its exact
shape. "The same 24 values" means the authenticated detail schema **re-declares** them; it
does not reference them. The two may diverge later in either direction, which is precisely
why they are declared apart.

---

## 2. Authorization, before either schema is reached

```
identity.status == 'active'
  AND an active link exists for this identity
  AND shipments.customer_id = <the linked canonical customer id>
```

The last clause is **in the SQL**. The list query is constrained by it; the detail query
re-checks it on the loaded row. A shipment belonging to anybody else produces the same
generic not-found body as a shipment that does not exist — same status code, same shape,
same latency profile (see [`THREAT_MODEL.md`](THREAT_MODEL.md) T-03).

Ownership is the shipper relationship, `shipments.customer_id`, and nothing else. **Not** an
email match on the shipment, **not** a phone match, **not** a customer id supplied by the
browser, **not** possession of a tracking reference (OD-29).

---

## 3. The list allowlist

Every field, its source, and why it is safe. Sixteen fields, plus the two derived flags
below (UAT round 11 added `booking_reference`, DEC-0160).

| # | Field | Type | Source column / derivation | Why it is here |
|---:|---|---|---|---|
| 1 | `shipment_reference` | str | `shipments.public_id` | The identifier the customer and staff both use. Already public |
| 1a | `booking_reference` | str? | `shipments.booking_reference`, trimmed; null when blank | The customer's or partner's own reference for the booking (`DATA_DICTIONARY.md`), so a customer can match a row to their own order. The keyword search reads it, and the row now shows it (DEC-0160). The detail carries the same value since UAT round 12 (§4, field 1a, DEC-0163) |
| 2 | `booked_at` | datetime? | `shipments.booking_date` | The primary way a customer recognises their own shipment |
| 3 | `route_group` | str | `shipments.route_group` | Machine value for grouping and filtering |
| 4 | `route_label` | str | `app.core.public_reference` label for the route group | Human wording; already used publicly |
| 5 | `origin_city` | str? | `shipments.origin_city` | Coarse. Same granularity Public Tracking already shows |
| 6 | `origin_country_code` | str? | `shipments.origin_country_code` | Coarse |
| 7 | `destination_city` | str? | `shipments.destination_city` | Coarse; the main way a customer tells two shipments apart |
| 8 | `destination_country_code` | str? | `shipments.destination_country_code` | Coarse |
| 9 | `status` | str | `shipments.operational_state`, mapped to the public vocabulary | The list's purpose |
| 10 | `status_label` | str | label for the mapped status | Human wording |
| 11 | `package_count_active` | int | count of `shipment_packages` where state is `active` | Size of the shipment |
| 12 | `package_count_cancelled` | int | count where state is `cancelled` | A cancelled package is a fact the shipper should see |
| 13 | `delivered_at` | datetime? | `shipments.delivered_at` | Closure |
| 14 | `cancelled_at` | datetime? | `shipments.cancelled_at` | A cancelled shipment stays visible with a safe state (OD-29) |
| 15 | `last_public_update_at` | datetime? | newest `shipment_events.occurred_at` where `is_public_update` | "Is there anything new" without opening the row |

Plus two booleans derived from existing columns, listed separately because they are
**derived** rather than copied:

| # | Field | Type | Derivation | Why |
|---:|---|---|---|---|
| 16 | `is_cancelled` | bool | `booking_state == 'cancelled'` | Lets the UI mark the row without parsing a status string |
| 17 | `is_rebooked` | bool | `rebooked_to_shipment_id is not null` | A rebooked shipment stays visible with a safe state (OD-29). The **linked shipment's reference is not included** — see §5 |

**Eighteen fields. Nothing else.**

### 3.1 Deliberately excluded from the list, with the reason

| Excluded | Why |
|---|---|
| Recipient name, company, phone, email, address | A third party's personal data. The shipper knows who they sent to; the account does not need to re-publish it to select a row, and a leaked session should not hand over an address book |
| Sender name, address | Same category, and it is the customer's own record, available under "My information" |
| Any money field | OD-32 |
| `contents_description`, `declared_value` | Not needed to select a row; a customs-sensitive free-text field |
| `internal_notes`, `owner_user_id` | Internal (OD-27) |
| `shipments.id`, `customer_id` | Internal row ids |
| `idempotency_key`, `source_system`, `source_record_id` | Internal booking and import mechanics. (`booking_reference` was listed here until UAT round 11; it is field 1a above, DEC-0160) |
| `payment_state` | Financial (OD-32) |
| `is_demo_record` | Internal |

### 3.2 List behaviour

* **Ordering:** newest `booking_date` first, `shipments.public_id` as the tie-break, so the
  order is total and a page boundary cannot duplicate or skip a row.
* **Paging:** the existing page/limit convention, with a server-enforced maximum page size.
* **Filtering:** by status group, by date range, by **exact Solaris shipment reference**
  and by **exact route group** (OD-41, §3.3), and by **keyword** over four fixed columns
  and the shipment's own package references (DEC-0156, DEC-0161, §3.4). Nothing else. The screen offers the keyword box rather than the exact
  reference box; the `reference` parameter stays on the API.
* **Empty is a legitimate answer.** A newly approved account with no qualifying shipments
  gets an empty list and a plain sentence, not an error and not a hint that shipments might
  exist elsewhere.

### 3.3 The two filters added by OD-41

Both are **exact match**, both are applied **after** the ownership clause of §2 so they can
only ever narrow the caller's own rows, and neither reads a column outside the list
allowlist (17 fields when OD-41 was issued, 18 since DEC-0160).

| Filter | Query parameter | Accepted value | Refused |
|---|---|---|---|
| Solaris shipment reference | `reference` | One reference, canonically normalized by the **existing** `app.core.public_reference` parser — the same parser the detail route and Public Tracking use | A substring, a prefix, a wildcard, a fuzzy or free-text term, a carrier tracking number, a package reference, a recipient name, email, phone or address, and anything over the filter length bound |
| Route group | `route_group` | One member of the existing route-group vocabulary | Any other string, in any spelling or case, and any value assembled by the caller |

**The reference filter is not an ownership oracle.** A reference that does not exist, and a
reference belonging to somebody else, both produce **an empty list** — the same status
code, the same body shape and the same headers. The filter narrows rows the ownership
clause already selected, so a foreign reference simply matches none of them; there is no
branch that could answer differently, and no count, header or ordering that varies.

This is deliberately **not** the behaviour of the *detail* route, which answers a generic
404. The two are different questions: asking for one shipment by name has an answer that
can be absent, while filtering a list has an answer that can be empty. Both are safe
because neither distinguishes "no such shipment" from "not yours".

**Validation is this surface's, not the framework's.** A malformed or oversized value is
refused by the service's own parser with the `{code, message, field}` body every other
refusal on this surface uses — never by a FastAPI `Query(...)` constraint, which would
answer with a second failure shape that echoes the submitted value back (DEC-0059, and the
defect Phase 11 recorded in `PROJECT_STATUS.md` §25.14).

**Neither filter can bypass the read limiter.** The `account:read:<identity>` bucket is
consumed before the query string is parsed, so a flood of malformed filters is refused at
the same rate as a flood of valid ones and issues no additional statement.

### 3.4 The keyword search (UAT rounds 10 and 11, DEC-0156, DEC-0161)

| Query parameter | Matches | Never reads |
|---|---|---|
| `q` | A shipment whose `public_id`, `booking_reference`, `origin_city` or `destination_city` **contains** the keyword, or one of whose **own** packages' `package_reference` does (since UAT round 11, DEC-0161), ignoring case and accents (one fold, `search_fold`, on both sides) | Recipient or sender name, company, address, postal code, phone or email; contents; notes; cancellation reasons; carrier tracking numbers; any column the caller names |

* **Applied after §2's ownership clause**, like every filter, so it only narrows the
  caller's own rows. A keyword that matches only somebody else's shipment returns the same
  empty page, byte for byte, as one that matches nothing.
* **Safe by construction.** `%`, `_` and `\` in the keyword are escaped and the `LIKE`
  pattern is a bound parameter. Over 64 characters is refused by the service with this
  surface's `{code, message, field}` body (field `q`), never echoed. Empty is no search.
  The keyword is never logged. The read limiter is consumed first.
* **`booking_reference` is searched and, since UAT round 11, shown** (field 1a, DEC-0160),
  so a row found by it says why. Until then it was searched but not published.
* **Package references (DEC-0161).** An `EXISTS` over `shipment_packages` correlated on
  `shipment_id`, inside the keyword clause and so after the ownership clause: a package
  can only find the shipment it belongs to, and only if that shipment is the caller's. A
  shipment with several matching packages is one row; cancelled packages count, as the
  detail shows them (confirmed by the owner in UAT round 12, DEC-0164). The package
  references themselves are not added to the list row.

**Composition.** All four filters may be combined. They are conjunctive: each one narrows,
none widens, and the ownership clause is first in every case.

---

---

## 4. The detail allowlist

**The 24 fields of the current public contract, re-declared, plus `booking_reference`
(field 1a, UAT round 12, DEC-0163): 25 fields.** Source of truth for the 24:
`backend/app/schemas/public_tracking.py::PublicTrackingResult`, which does not gain 1a.

| # | Field | Type | Group |
|---:|---|---|---|
| 1 | `shipment_reference` | str | Identity |
| 1a | `booking_reference` | str? | Identity. `shipments.booking_reference`, trimmed; null when blank. The customer's or partner's own reference for the booking, the same value as the list's field 1a (DEC-0163). Authenticated detail only |
| 2 | `matched_reference_type` | str | Identity |
| 3 | `selected_package_reference` | str? | Identity |
| 4 | `route_group` | str | Route |
| 5 | `route_label` | str | Route |
| 6 | `origin` | place (city, country_code, country_label) | Route |
| 7 | `destination` | place | Route |
| 8 | `status` | str | Status |
| 9 | `status_label` | str | Status |
| 10 | `package_count_active` | int | Status |
| 11 | `package_count_cancelled` | int | Status |
| 12 | `package_count_delivered` | int | Status |
| 13 | `progress_summary` | str | Status |
| 14 | `packages` | list of (reference, status, status_label, is_selected, is_cancelled, delivered_at) | Status |
| 15 | `estimated_delivery_at` | datetime? | Dates |
| 16 | `delivered_at` | datetime? | Dates |
| 17 | `cancelled_at` | datetime? | Dates |
| 18 | `timeline` | list of approved public milestones | Timeline |
| 19 | `tracking_state` | enum | Timeline |
| 20 | `last_public_update_at` | datetime? | Timeline |
| 21 | `carrier_link` | (carrier_name, url)? | Timeline |
| 22 | `data_mode` | enum | Presentation |
| 23 | `help_url` | str? | Presentation |
| 24 | `timezone` | str | Presentation |

The nested shapes (`place`, `package`, `timeline entry`, `carrier link`) are re-declared too,
with the same fields and the same exclusions — in particular a timeline entry carries the
**approved public wording only**, never `internal_detail`, never the recording staff member,
never the internal event id, never the leg.

### 4.1 Why the authenticated view starts at parity rather than richer

An authenticated shipper could justifiably see more than an anonymous reference-holder. But
"could justifiably" is a decision, and each additional field is a separate one. Starting at
parity means release 1 adds **authentication and ownership** without also adding a new
disclosure surface, and every later addition arrives as its own reviewed change to this
table rather than as a schema that grew while nobody was counting.

Candidates a later phase may propose, none of them in release 1: recipient city at finer
granularity, contents description, declared value, per-leg progress, document attachments.

The first such addition is `booking_reference` (UAT round 12, DEC-0163): the customer's
own reference for their booking, already on their list row since DEC-0160, so the detail
of a shipment found by it says why. It is not added to Public Tracking.

---

## 5. Cancelled, rebooked and return shipments (OD-29, OD-22)

| Case | Release 1 behaviour |
|---|---|
| **Cancelled** shipment | Visible, in both list and detail, with the cancelled state and `cancelled_at`. Not hidden, not deleted, not silently dropped from the count |
| **Rebooked** shipment | Visible, flagged `is_rebooked`. The **reference of the linked replacement is not disclosed** in release 1: the replacement is itself a shipment, and it is visible on its own row if and only if it belongs to the same customer. Linking the two in the response would be a second disclosure decision |
| **Return event statuses** (`return_in_progress`, `returned`) | Visible where already supported, exactly as Public Tracking shows them today |
| **Linked return-shipment records** | **Governed by OD-22, which is open.** Until it is answered, a separate return shipment is treated like any other shipment: visible if and only if its own `customer_id` is the linked customer. No return-specific linking, labelling or workflow is added |
| **Draft** booking (`booking_state = 'draft'`) | **Not visible.** A draft is internal work in progress, and Public Tracking already refuses it |
| **Demo** record | Not visible in production, exactly as the public surface already refuses it |

---

## 6. The disclosure preview shown to staff before approval (OD-29)

Computed from this same ownership rule, over the candidate customer, before the link is
made:

| Shown to the approver | Derivation |
|---|---|
| Count of shipments that become visible | `count(*)` over the visibility rule |
| Oldest shipment date | `min(booking_date)` |
| Newest shipment date | `max(booking_date)` |
| Whether cancelled shipments are included | true when any candidate has `booking_state = 'cancelled'` |
| Whether rebooked shipments are included | true when any candidate has `rebooked_to_shipment_id` or `rebooked_from_shipment_id` |

The approver acknowledges this explicitly; the acknowledgement, with these figures, is part
of the approval audit record. The figures are **staff-facing only** and never returned to a
customer-facing route — a count of matching shipments is itself an enumeration oracle.

---

## 7. Test obligations

1. `AccountShipmentDetail` has exactly 25 top-level fields (24 until UAT round 12,
   DEC-0163), asserted by name against a frozen list in the test, and is **not** a subclass
   of any public or staff model.
2. `AccountShipmentListItem` has exactly 18 fields (17 until UAT round 11, DEC-0160),
   asserted by name.
3. `PublicTrackingResult` still has exactly 24 fields — the existing test, unmodified.
4. For a customer with shipments and another customer with shipments, every list response
   contains only the caller's references; requesting the other customer's reference by hand
   returns the generic not-found body.
5. A cancelled shipment and a rebooked shipment appear, with safe states.
6. A draft and a demo shipment do not appear.
7. Every **Never** field from [`FIELD_MATRIX.md`](FIELD_MATRIX.md) §3.4 is asserted absent
   from both schemas, against a record where each is populated.
8. No response on this surface contains any of `currency`, `selling_amount`,
   `shipping_cost`, `surcharges_amount`, `discount_amount`, `refund_amount`, `payment_state`,
   `declared_value`, `declared_value_currency` — asserted by scanning the serialized body,
   not only the schema.
9. **(OD-41)** The reference filter matches exactly: the whole reference returns the row, a
   prefix of it returns nothing, and a different casing or separator spelling of the same
   reference still returns the row because normalization runs first.
10. **(OD-41)** An unknown reference and another customer's reference produce **identical**
    empty responses — same status, same body, same headers.
11. **(OD-41)** A reference filter over the length bound, and an unknown route group, both
    produce this surface's validation body and not FastAPI's.
12. **(OD-41)** A refused-by-the-limiter request carrying a malformed filter issues no
    query at all.
13. **(OD-41)** The four filters compose, and every combination is still constrained by the
    ownership clause.
