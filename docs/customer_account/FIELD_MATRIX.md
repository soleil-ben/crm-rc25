# Customer Account — field-by-field customer data matrix

**Status:** requirements only. **Authority:** OD-27, OD-28, OD-38.

Every column the CRM holds about a customer appears in this document exactly once, with one
of four dispositions. A column that is not listed does not exist yet; a column added later
is **invisible and uneditable by default** and reaching any other disposition requires
editing this table.

| Disposition | Meaning |
|---|---|
| **Direct** | The customer may change it and it applies immediately, with no staff approval |
| **Proposal** | The customer may submit a change; Operations or Admin must approve before canonical data moves |
| **Read-only** | Visible to the customer, not changeable by them |
| **Never** | Not visible to the customer, in any response, at any time |

---

## 1. The default, stated first

**Never.** A field reaches the customer only by being written into this table and into a
response allowlist. There is no "return the customer row" path on this surface; every field
is copied across individually by a service.

---

## 2. Registration submission (OD-27)

These are the only fields a registration form may accept. Each lands in a **pending
proposal**, not in `customers`.

| Submitted field | Canonical target | Notes |
|---|---|---|
| Customer type | `customers.category` (`individual` \| `business`), `customers.business_type` when business | Enumerated; free text is refused |
| Legal name | `customers.full_name` for an individual; `customers.business_name` for a business | See §6: the CRM has no separate legal/display pair today |
| Display name | **no column today** — see §6 | Proposed new column, decided in the implementation phase, not here |
| Primary contact name | `customers.full_name` (business) or the default sender address `contact_name` | See §6 |
| Email | `customers.email_entered`, normalized to `email_normalized` | Normalization reuses `app.core.normalization`. Always the account's verified sign-in email: an `email` in the customer block that differs is not used (one email per customer, DEC-0138) |
| Phone | `customers.phone_entered`, normalized to `phone_e164` / `phone_region` | Same service as the Staff Portal |
| Preferred language | `customers.preferred_language` | `en` \| `vi` \| `fr` \| `other` (UI English-only in release 1, OD-39) |
| Pickup / sender address(es) | `customer_addresses` with `role = sender` or `both` | Multiple permitted. The form calls the first one **Address** and asks for it before billing (DEC-0145, DEC-0150). At registration its country, line 1, city and province or state are **required** (DEC-0151); the postal code is **optional** in every country (DEC-0159), and a typed one is kept as typed, held to its 30-character bound and, for Canada and the United States, to a lenient shape: Canada `A1A 1A1` with or without the space, any case; the United States `12345` or `12345-6789`. A blank one is always allowed and other countries are not checked; a misshapen one is refused beside the field, on the form and by the server, in the same words (DEC-0165); line 2, who the driver asks for, the pickup phone and "Notes for driver (buzz code, contact concierge, security,...)" (`delivery_note`) stay optional |
| Billing address | `customer_addresses` row | See §6: `AddressRole` has no `billing` member today. "Billing address is the same as the address above" (the request flag `billing_same_as_shipping`, not a field) has the server copy the address here. The form starts with it **ticked** (DEC-0158), and since UAT round 12 so does the API: a request that omits the flag is treated as ticked, and one that sends billing parts must send `false` (DEC-0166). Unticked, the same four parts are required and the postal code is optional, shape-checked against the billing country as above (DEC-0145, DEC-0152, DEC-0159, DEC-0165) |
| Notification preferences | new `customer_notification_preferences` rows | Operational only; not marketing |
| Marketing consent choice | `consent_events` (append-only), written **at approval**, never at registration | Explicit, separate, **unchecked by default**, timestamped |
| Terms/privacy acknowledgement | new `customer_terms_acknowledgements` row | Versioned, timestamped, append-only, tied to the identity (OD-37) |

**Nothing else.** A registration form field not in this table is a defect. The two
request-level controls beside these fields, `billing_same_as_shipping` and the password's
second copy `password_confirmation` (DEC-0146), are not customer fields and are never
stored.

---

## 3. After approval: what the customer may change

### 3.1 Direct — applies immediately, no staff approval (OD-27, OD-28)

| Field | Column | Why it is safe to apply directly |
|---|---|---|
| Preferred language | `customers.preferred_language` | Presentation only. It identifies nobody and merges nothing |
| Operational notification preferences | `customer_notification_preferences` (non-marketing rows) | The customer's own choice about operational messages about their own shipments |

Both are audited. Neither can suppress a legally required operational message, and neither
touches marketing consent or suppression.

### 3.2 Proposal — Operations or Admin must approve (OD-27, OD-28)

| Field | Column | Why approval is required |
|---|---|---|
| Legal name | `customers.full_name` / `business_name` | Identity-bearing; feeds `name_match_key` and duplicate detection |
| Display name | proposed column (§6) | Identity-bearing in customer-facing output |
| Primary contact name | `customers.full_name` / address `contact_name` | Identity-bearing |
| Email | `customers.email_entered` → `email_normalized` | Identity-bearing, a duplicate key, and the account's own login address. **One email per customer** (DEC-0138): approving a link makes the record's email the verified sign-in email, shown to staff in the preview and audited; while an active or suspended account holds the link, staff cannot change it, and the edit form shows the field read-only with the rule; the account must be deactivated first (DEC-0142) |
| Phone | `customers.phone_entered` → `phone_e164` | Identity-bearing and a duplicate key |
| Billing address | `customer_addresses` | Financial and legal correspondence target |
| Pickup / sender addresses | `customer_addresses` (`sender`, `both`) | Operational instruction to drivers and staff. A proposed Canadian or United States postal code is held to the registration shapes by the server, refused beside the field (DEC-0165) |
| Customer type | `customers.category`, `business_type` | Changes segmentation, pricing conversations and reporting |

A proposal never writes canonical data. Approval does, in one transaction, through the
existing customer service, with the existing audit record and the existing duplicate review.

### 3.3 Read-only — visible, not editable

| Field | Column | Why visible |
|---|---|---|
| Customer public id | `customers.public_id` | It is the customer's own reference and staff quote it on the phone |
| Booking reference of each of their own shipments | `shipments.booking_reference` | The customer's or partner's own order or PO number. On each row of **My shipments** (DEC-0160) and on the shipment's own page (DEC-0163); never on Public Tracking |
| Approved current values of every §3.2 field | as above | The customer must see what is on file to propose a correction to it |
| Account state and linked-customer status | `customer_identities.status` | Their own account |
| Their own submitted proposals and each proposal's state | `customer_data_proposals` | Their own submissions |
| Their own consent history | `consent_events` filtered to this customer | Append-only; see §4 |
| Their own terms acknowledgements | `customer_terms_acknowledgements` | Their own record |

### 3.4 Never — not visible, not editable (OD-27)

| Field or entity | Where it lives | Why never |
|---|---|---|
| Internal tags | `tags`, `customer_tags` | Internal classification; a tag can be a commercial judgement about the customer |
| Lifecycle status | derived by `activity_service` from thresholds | An internal health judgement, not a fact about the customer |
| Referral source | `referrals`, `customers.source_system`, `source_record_id` | Reveals another customer, or an internal acquisition channel. **Exception:** if a referral source is explicitly collected during registration, that submitted value is the customer's own answer and is visible to them (OD-27). Nothing derived or staff-entered becomes visible with it |
| Internal notes | `customers.notes`, `shipments.internal_notes` | Staff prose about the customer |
| Interactions | `interactions` (all rows, both visibilities) | Staff records of contact, including internal-only |
| Follow-up tasks | `follow_up_tasks` | Internal work |
| Service issues | `service_issues` | Internal handling of a complaint |
| Assigned staff | `customers.owner_user_id`, `shipments.owner_user_id` | Names a staff member |
| Audit information | `audit_events` | Internal accountability record |
| Duplicate scores and match candidates | `duplicate_service` output | Discloses the existence of other customer records |
| Suppression administration | `contact_suppressions` | A customer may not read, create, or release a suppression |
| Financial data | `shipments.currency`, `selling_amount`, `shipping_cost`, `surcharges_amount`, `discount_amount`, `refund_amount`, `payment_state`, `declared_value*` | OD-32, release 1 |
| Staff permissions and roles | `users.role`, permission sets | A different population entirely |
| Integration state | `integration_*` tables | No provider is connected; the state says what Solaris is trying, not what the customer needs |
| Archive and merge state | `is_archived`, `archived_at`, `archive_reason`, `merged_into_customer_id`, `merged_at`, `customer_id_aliases` | Internal record management; a merge discloses another record's existence |
| Demo flags | `is_demo_record` | Internal |
| Match keys | `name_match_key`, `phone_match_key`, `email_normalized` | Internal derived keys used for matching |
| Internal ids | `customers.id`, `shipments.id`, every integer primary key | References are public; row ids are not |
| `do_not_contact`, `service_restriction_note` | `customers` | Operational controls the customer cannot lift |
| Marketing-fit fields | `primary_shipping_purpose`, `shipping_frequency`, `estimated_monthly_shipments`, `primary_route_group`, `preferred_contact_channel`, `best_contact_time`, `contact_timezone`, `route_interests` | Staff-maintained commercial profile. Not exposed in release 1; a later phase may propose some of them, by editing this table |

---

## 4. Consent, suppression and notification preferences

**Three separate concepts. They are never one control** (OD-27, OD-38).

| | What it is | Customer may |
|---|---|---|
| **Operational notification preference** | Whether the customer wants a message about their own shipment events | change directly |
| **Marketing consent** | Permission to send marketing | grant or withdraw; explicit, separate, **unchecked by default**, timestamped, **append-only** |
| **Global suppression** | A block on **marketing** email to an address. Account email (verification, reset, the registration-attempt notice, approval and rejection notices) is not blocked (DEC-0139) | **nothing** — cannot view administration, cannot remove, cannot bypass |

Rules that hold without exception:

1. Every consent change appends a new `consent_events` row. **Nothing is updated in place
   and nothing is deleted**, which is the existing Phase 1 behaviour and stays.
2. A marketing-consent grant while a suppression is in force **does not** lift the
   suppression and does not make the address contactable. Since DEC-0127 the customer who
   has opted in is told, in one plain sentence, that marketing email cannot currently reach
   the address (`marketing.delivery_blocked`, a boolean). The reason, source and date of the
   block are never reported.
3. A withdrawal always takes effect, immediately, without staff approval. Withdrawal is the
   one consent direction a customer may always exercise.
4. An operational preference cannot switch off a message required for the shipment to be
   handled correctly, and cannot be used to switch marketing on.
5. **One address** (DEC-0138). Consent and suppression apply to the customer record's
   email, which for a linked customer is the account's verified sign-in email. A
   registration's opt-in is recorded for that address.
6. **A suppression blocks marketing only** (DEC-0139). A suppressed address registers,
   verifies, recovers its password and receives the decision notice like any other; its
   opt-in stays ineffective while the suppression is in force, and nothing the customer
   reads names the suppression or its reason. Shipment and other operational email will
   not read it either (DEC-0143).

---

## 5. What the approver sees (OD-28)

For every proposal, before the approve control is usable:

| Shown | Source |
|---|---|
| Proposed value | `customer_data_proposal_fields.proposed_value` |
| Current canonical value | the customer row at approval time |
| Normalized value where relevant | `app.core.normalization` |
| Duplicate implications | `duplicate_service`, existing exact/probable review |
| Affected account | `customer_identities` |
| Actor | the approving staff user |
| Audit outcome | the record that will be written |

Approval is **transactional and idempotent**: the same approval applied twice produces one
canonical change and one audit record. A proposal whose canonical value changed underneath
it since submission is **refused, not merged** — the approver sees the drift and decides
again.

---

## 6. Fields the CRM does not have yet — stated, not invented

The owner's registration list names three things the schema has no column for today:

| Owner's field | Today | Proposed resolution |
|---|---|---|
| **Display name** | no column | Add `customers.display_name`, nullable, in the implementation phase. Until then, a display-name proposal has nowhere canonical to land |
| **Legal name distinct from display name** | `full_name` and `business_name` only | Either add `customers.legal_name` or define `full_name` as the legal name and `display_name` as the new one. **Decided in the implementation phase, with a migration, not here** |
| **Billing address** | `AddressRole` is `sender` \| `recipient` \| `both` | Add a `billing` member, or a boolean `is_billing` on `customer_addresses`. Same phase, same migration |

These are recorded here rather than assumed because each is a schema change with an
`alembic check` consequence (DEC-0089), and this phase writes no migrations.

---

## 7. Field-level test obligations

1. A response builder that serializes a whole ORM customer fails the build — enforced by
   `from_attributes=False` and by a test that asserts no Customer Account schema sets it.
2. Every **Never** row is asserted absent from every Customer Account response, by name, for
   a customer whose record has that field populated. Absence is asserted against a populated
   record, never an empty one.
3. A direct-edit request naming a proposal field is refused; a proposal request naming a
   never field is refused.
4. A marketing-consent grant against a suppressed address leaves the suppression in force
   and returns only `marketing.delivery_blocked: true` about it (DEC-0127): no reason, source
   or date.
5. Approving the same proposal twice changes canonical data once.
