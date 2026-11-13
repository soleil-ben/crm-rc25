# Data dictionary

Every field implemented in Phases 1 to 3: type, required status, validation, default, who
may edit it, and whether it is derived. The public tracking response contract is the last
section. **Derived fields are never stored** — they are
computed from records on read (`CRM.md` section 4).

Permission names come from `backend/app/core/permissions.py`.

---

## `customers`

### Identity and contact

| Field | Type | Required | Validation | Default | Edit | Derived |
|---|---|---|---|---|---|---|
| `id` | int PK | yes | internal only, never exposed as the customer-facing ID | auto | — | no |
| `public_id` | str(20) unique | yes | `STCA-000001`, allocated from a durable counter inside the create transaction; immutable | auto | none | no |
| `full_name` | str(200) | **yes** | trimmed, whitespace collapsed, NFC normalized; accents and original spelling preserved | — | `customer:update` | no |
| `legal_name` | str(200) | no | the registered or legal name as submitted; trimmed. **Feeds no match key** | null | approval only (Phase 10) | no |
| `display_name` | str(200) | no | what the customer prefers to be called; presentation only. **Feeds no match key, no duplicate rule and no constraint** | null | approval only (Phase 10) | no |
| `name_match_key` | str(200) | no | accent-folded lowercase key, **matching only** | auto | none | yes |
| `phone_entered` | str(60) | conditional | stored exactly as typed | null | `customer:update` | no |
| `phone_e164` | str(30) | no | country-aware parse; null when the number cannot be parsed | null | none | yes |
| `phone_region` | str(4) | no | detected region code | null | none | yes |
| `phone_match_key` | str(30) | no | E.164, else the last 9 significant digits | null | none | yes |
| `email_entered` | str(320) | conditional | trimmed | null | `customer:update` | no |
| `email_normalized` | str(320) | no | syntax validated, lowercased; **deliverability is not checked** | null | none | yes |

**Table constraint `ck_customers_contactable`:** `email_normalized IS NOT NULL OR
phone_match_key IS NOT NULL`. A customer needs a name plus at least one usable contact
method. Unusual international numbers are accepted: when E.164 parsing fails the entered
value is kept and a digit-only fallback key is used, so the record is still creatable.

### Name precedence (Phase 10)

Four name-ish concepts now exist and the order between them is decided once, here.
`FIELD_MATRIX.md` section 6 left it open; Phase 10 is the phase that first has to write a
customer from a registration, so it is the phase that answers it.

| Concept | Column | Meaning |
|---|---|---|
| Contactable name | `full_name` | **Unchanged.** The name of the person to talk to. Required. The only name any existing query, display or match key reads |
| Legal name | `legal_name` | The registered or legal name, as the applicant submitted it. Null for every row created before Phase 10 and for every row nobody supplied one for |
| Company name | `business_name` | **Unchanged.** The trading entity. Set from `legal_name` when a business registration is approved; separate so a later trading-name change does not rewrite the legal one |
| Preferred name | `display_name` | Presentation only |

**How an approved registration resolves them:**

| Customer type | `full_name` | `legal_name` | `business_name` | `display_name` |
|---|---|---|---|---|
| Individual | submitted legal name, else the primary contact name | submitted legal name | — | submitted display name |
| Business | submitted primary contact name, else the legal name | submitted legal name | submitted legal name | submitted display name |

A registration supplying neither a legal name nor a contact name is **refused**, because
`full_name` is not nullable and inventing one would be worse than declining.

**Nothing rewrites an existing row.** Adding the two columns set them null everywhere and
changed the meaning of nothing; `merge_customers` fills a blank one from the source record,
like every other column it fills, so a merge cannot silently drop a legal or preferred name.

### Location and language

| Field | Type | Required | Validation | Default | Edit | Derived |
|---|---|---|---|---|---|---|
| `city` | str(120) | no | free text | null | `customer:update` | no |
| `province_state` | str(120) | no | free text, country-agnostic | null | `customer:update` | no |
| `country_code` | str(2) | no | uppercased ISO-3166-1 alpha-2 | null | `customer:update` | no |
| `preferred_language` | enum | yes | `en \| vi \| fr \| other \| unknown` | `unknown` | `customer:update` | no |

Language is **never inferred** from a name or a shipping lane; the form says so.

### Segmentation (declared, not observed)

| Field | Type | Required | Validation | Default | Edit | Derived |
|---|---|---|---|---|---|---|
| `category` | enum | yes | `individual \| business` | `individual` | `customer:update` | no |
| `business_type` | enum | no | `online_seller \| retailer \| other`; cleared when category is not business | null | `customer:update` | no |
| `business_name` | str(200) | no | cleared when category is not business | null | `customer:update` | no |
| `primary_shipping_purpose` | enum | yes | 8 values incl. `unknown` | `unknown` | `customer:update` | no |
| `primary_route_group` | enum | no | `VCA \| CAV \| CAD \| XUS` | null | `customer:update` | no |
| `shipping_frequency` | enum | yes | declared expectation, 6 values incl. `unknown` | `unknown` | `customer:update` | no |
| `estimated_monthly_shipments` | numeric(10,2) | no | `>= 0`; explicitly separate from actual history | null | `customer:update` | no |

### Contact preference, ownership, restriction

| Field | Type | Required | Validation | Default | Edit | Derived |
|---|---|---|---|---|---|---|
| `preferred_contact_channel` | enum | no | 6 channels | null | `customer:update` | no |
| `best_contact_time` | str(120) | no | free text | null | `customer:update` | no |
| `contact_timezone` | str(64) | no | IANA name | null | `customer:update` | no |
| `owner_user_id` | FK users | no | `ON DELETE SET NULL` | null | `customer:update` | no |
| `do_not_contact` | bool | yes | service restriction, **stored independently of lifecycle status and of marketing consent** | false | `customer:update` | no |
| `service_restriction_note` | str(400) | no | free text | null | `customer:update` | no |
| `notes` | text | no | internal only | null | `customer:update` | no |

### Lifecycle, provenance, merge

| Field | Type | Required | Validation | Default | Edit | Derived |
|---|---|---|---|---|---|---|
| `is_archived` | bool | yes | manual state; outranks the derived lifecycle | false | `customer:archive` | no |
| `archived_at` / `archive_reason` | datetime / str(255) | no | set on archive | null | `customer:archive` | no |
| `created_at` (**Date Added**) | datetime UTC | yes | system timestamp | now | none | no |
| `source_system` / `source_record_id` | str | no | import idempotency pair | null | import | no |
| `source_created_at` | datetime | no | original date preserved on import, separate from `created_at` | null | import | no |
| `is_demo_record` | bool | yes | flags synthetic seed data | false | seed only | no |
| `merged_into_customer_id` | FK customers | no | set on merge; makes the record read-only | null | `customer:merge` | no |
| `merged_at` | datetime | no | set on merge | null | `customer:merge` | no |

---

## Derived customer activity (computed, never stored)

Computed by `activity_service.compute_customer_activity`.

**Qualifying shipment** = `booking_state = confirmed` **and** `first_handoff_at IS NOT
NULL` **and** `cancelled_at IS NULL` **and** `is_return = false`. Counted once at the
parent shipment level regardless of packages, legs, or carrier labels.

| Derived field | Definition |
|---|---|
| `total_qualifying_shipments` | count of qualifying shipments |
| `total_bookings` | non-draft bookings, including cancelled — shown separately so demand is distinguishable from shipping |
| `delivered_shipments` | qualifying shipments with `delivered_at` set |
| `first_shipment_at` / `last_shipment_at` | `MIN` / `MAX` of `first_handoff_at` over qualifying shipments |
| `is_repeat_customer` | qualifying count `>= 2` |
| `observed_primary_route_group` | most frequent route group over qualifying shipments |
| `route_counts` | qualifying shipments per route group |
| `lifecycle_status` | see below |
| `days_since_last_shipment` | days since `last_shipment_at` |
| `referral_count` | distinct referred customer records |
| `qualified_referral_count` | referred customers with at least one qualifying shipment |
| `open_task_count` / `overdue_task_count` | open tasks; overdue = open with `due_at` in the past |
| `next_follow_up_at` | `MIN(due_at)` over open tasks |
| `last_follow_up_at` | `MAX(completed_at)` over completed tasks |
| `unresolved_issue_count` / `has_service_issue` | open or in-review service issues |

### Lifecycle status

| Status | Rule |
|---|---|
| `archived` | `is_archived` is true — manual, outranks everything below |
| `prospect` | no qualifying shipments |
| `new` | exactly one qualifying shipment within `lifecycle_new_days` (default 30) |
| `active` | last shipment within `lifecycle_active_days` (default 60) |
| `at_risk` | last shipment within `lifecycle_at_risk_days` (default 90) |
| `inactive` | last shipment older than `lifecycle_at_risk_days` |

Thresholds are administrator-editable settings, not constants. Definitions are shown in
the UI. Service restrictions and do-not-contact are stored separately and never appear
here.

---

## `customer_addresses` (address book)

| Field | Type | Required | Notes |
|---|---|---|---|
| `customer_id` | FK customers | yes | `ON DELETE CASCADE` |
| `label` | str(120) | no | e.g. "Family in Vietnam" |
| `role` | enum | yes | `sender \| recipient \| both`, default `both` |
| `contact_name` | str(200) | **yes** | accents preserved |
| `company_name`, `phone_entered`, `phone_e164`, `email_entered` | | no | phone normalized as above |
| `address_line1/2`, `city`, `province_state`, `postal_code`, `country_code` | | no | international-tolerant |
| `delivery_note` | str(400) | no | |
| `is_default_sender` / `is_default_recipient` | bool | yes | at most one of each per customer, enforced in the service |
| `is_archived` | bool | yes | soft delete |

Edit: `address:write`. **Confirmed shipments keep their own address snapshot, so editing
an entry here never rewrites shipment history** (AC-5). Snapshot columns arrive in Phase 2.

---

**Billing addresses (Phase 10).** `role` gained a fourth value, `billing`. It required no
schema change: the column is a `String(20)` with no check constraint. A billing row is a
correspondence target, never a collection or delivery point — the booking pickers select on
`sender`/`both` and `recipient`/`both`, which were changed from exclusion filters to
inclusion filters in the same phase so that a `billing` row cannot appear in either.

An approved registration creates **one** `billing` row from its `billing_address.*` group,
with `is_default_sender` and `is_default_recipient` both false, and one `sender` row per
`pickup_address.N.*` group, of which the first submitted becomes the default sender.

## `interactions`

| Field | Type | Required | Notes |
|---|---|---|---|
| `customer_id` | FK customers | yes | `ON DELETE CASCADE` |
| `shipment_id` / `task_id` | FK | no | `ON DELETE SET NULL` |
| `occurred_at` | datetime UTC | yes | defaults to now |
| `channel` | enum | yes | phone, email, sms, messaging app, in person, other |
| `direction` | enum | yes | inbound, outbound, internal |
| `subject` | str(200) | **yes** | |
| `body` / `outcome` | text / str(200) | no | |
| `visibility` | enum | yes | `internal` by default — **all CRM notes are internal**; public shipment updates are a separate Phase 3 concept |
| `is_follow_up_completion` | bool | yes | set when written by task completion; drives Last Follow-up Date |
| `author_user_id` | FK users | no | `ON DELETE SET NULL` |

Edit: `interaction:write`.

---

## `follow_up_tasks`

| Field | Type | Required | Notes |
|---|---|---|---|
| `customer_id` | FK customers | yes | `ON DELETE CASCADE` |
| `shipment_id` | FK shipments | no | `ON DELETE SET NULL` |
| `subject` | str(200) | **yes** | |
| `detail` | text | no | |
| `purpose` | enum | yes | 7 values, default `general` |
| `priority` | enum | yes | low, normal, high, urgent |
| `status` | enum | yes | not scheduled, scheduled, in progress, waiting for customer, completed, cancelled |
| `due_at` | datetime UTC | conditional | **required** when status is scheduled or in progress |
| `assignee_user_id`, `created_by_user_id`, `completed_by_user_id` | FK users | no | `ON DELETE SET NULL` |
| `completed_at`, `outcome`, `cancelled_reason` | | no | set on completion or cancellation |
| `source_rule` | str(60) | no | which automation rule created it |
| `dedupe_key` | str(160) unique | no | prevents duplicate rule-created tasks |

**Overdue is derived**, never stored: an unfinished task whose `due_at` is in the past.
Completing one task never touches another. A completed task cannot be reopened; create a
follow-on task instead. Edit: `task:write`.

---

## `consent_events` (append-only)

| Field | Type | Required | Notes |
|---|---|---|---|
| `customer_id` | FK customers | yes | `ON DELETE CASCADE` |
| `channel` | enum | yes | `email \| sms` |
| `address_value` | str(320) | yes | normalized email or phone key |
| `status` | enum | yes | unknown, consented, withdrawn, suppressed |
| `basis` | enum | yes | express, implied business relationship, not recorded |
| `obtained_at`, `withdrawn_at`, `expires_at` | datetime | no | |
| `source`, `evidence_reference`, `note` | str | no | |
| `recorded_at` | datetime UTC | yes | |
| `recorded_by_user_id` | FK users | no | `ON DELETE SET NULL` |

The current state is the **latest event** for a channel/address pair; earlier events are
never overwritten. Recording `consented` requires a basis other than "not recorded".
Edit: `consent:write`.

**Marketing eligible** requires all of: a usable address, latest status `consented`, no
unexpired-consent violation, no active suppression, `do_not_contact` false, and the
customer not archived. Unknown or imported contact information is **not** eligible.

---

## `contact_suppressions`

| Field | Type | Required | Notes |
|---|---|---|---|
| `channel` + `address_value` | | yes | **unique together**; global, not customer-scoped |
| `reason` | str(200) | yes | |
| `created_at`, `created_by_user_id` | | | |
| `released_at`, `released_by_user_id`, `release_reason` | | no | release requires `suppression:release` (admin) and is audited |

Being global is what makes suppression survive merges and re-imports (AC-15). Writing a
consent event cannot clear it.

---

## `tags`, `customer_tags`, `customer_route_interests`, `customer_id_aliases`, `referrals`

| Table | Key columns | Notes |
|---|---|---|
| `tags` | `slug` unique, `name`, `color_token` | manual vocabulary; `tag:write` |
| `customer_tags` | unique `(customer_id, tag_id)` | set union on merge |
| `customer_route_interests` | unique `(customer_id, route_group)` | relational, so segments can filter on it |
| `customer_id_aliases` | `alias_public_id` unique | former IDs kept after a merge; lookup resolves to the survivor |
| `referrals` | `referred_customer_id` unique; check `referrer <> referred` | one referrer per customer; self-referral rejected by constraint and service |

---

## `service_issues`

`customer_id`, optional `shipment_id`, `title`, `detail`, `status`
(`open \| in_review \| resolved \| closed`), `opened_at`, `resolved_at`,
`opened_by_user_id`. Open and in-review issues drive the unresolved count and the
service-recovery segment.

---

## `saved_segments`

| Field | Type | Notes |
|---|---|---|
| `slug` | str(80) unique | generated from the name |
| `name`, `description` | | |
| `definition_json` | text | a **validated** AND/OR filter tree, not free-form SQL; every field and operator is whitelisted before compilation |
| `is_system` | bool | built-in segments cannot be edited or deleted; "Save as copy" instead |
| `is_shared` | bool | |
| `owner_user_id` | FK users | `ON DELETE SET NULL` |

Edit: `segment:write`. Marketing eligibility is deliberately **not** a filter field.

---

## `shipments`

Phase 1 created this table with only the columns its derivation rules needed. Phase 2
**extended** it (migration `6b767a8a58fe`) with the booking reference, the sender and
recipient address snapshots, declared value, and the cancel/rebook links. Tracking
assignments and provider events remain Phase 4 work.

| Field | Type | Notes |
|---|---|---|
| `public_id` | str(30) unique | **null until a booking is confirmed**, so drafts never expose a customer-facing ID |
| `idempotency_key` | str(120) unique | retried confirmations return the original booking |
| `customer_id` | FK customers | `ON DELETE RESTRICT` — history is never cascade-deleted |
| `route_group` | enum | `VCA \| CAV \| CAD \| XUS` |
| `direction`, `service_type`, `transport_mode` | | mode and service stored separately from the route group |
| `booking_state` | enum | draft, confirmed, cancelled |
| `operational_state` | enum | the 17 normalized states from `CRM.md` section 10 |
| `payment_state` | enum | unrecorded, unpaid, partially paid, paid, refunded |
| `booking_date`, `confirmed_at`, `first_handoff_at`, `estimated_delivery_at`, `delivered_at`, `cancelled_at` | datetime UTC | `first_handoff_at` is the qualifying trigger |
| `package_count`, `packages_delivered_count` | int | supports "1 of 3 delivered" in Phase 2 |
| `is_return`, `return_of_shipment_id`, `rebooked_from_shipment_id` | | returns stay linked but are not another outbound purchase |
| `currency`, `selling_amount`, `shipping_cost`, `surcharges_amount`, `discount_amount`, `refund_amount` | str(3), numeric(12,2) | optional and manual; **null means Unknown, never zero** |
| `owner_user_id`, `internal_notes`, `source_system`, `source_record_id`, `is_demo_record` | | |

Three independent state fields; never overloaded into one status.

---

### Phase 2 additions

| Field | Type | Required | Validation | Default | Edit | Derived |
|---|---|---|---|---|---|---|
| `booking_reference` | str(60) | no | free text; the customer's or partner's own reference | null | `shipment:write` | no |
| `sender_address_id` / `recipient_address_id` | FK customer_addresses | no | `ON DELETE SET NULL`; **provenance only** — the snapshot is authoritative | null | draft only | no |
| `sender_name` / `recipient_name` | str(200) | **yes at confirmation** | accents preserved | null | draft only | no |
| `sender_company` / `recipient_company` | str(200) | no | | null | draft only | no |
| `sender_phone_entered` / `recipient_phone_entered` | str(60) | no | stored exactly as typed | null | draft only | no |
| `sender_phone_e164` / `recipient_phone_e164` | str(30) | no | country-aware parse; null when unparseable | null | none | yes |
| `sender_email` / `recipient_email` | str(320) | no | syntax validated | null | draft only | no |
| `sender_address_line1/2`, `recipient_address_line1/2` | str(255) | no | | null | draft only | no |
| `sender_city` | str(120) | no | | null | draft only | no |
| `recipient_city` | str(120) | **yes at confirmation** | needed for the label destination block | null | draft only | no |
| `sender_province_state` / `recipient_province_state` | str(120) | no | country-agnostic | null | draft only | no |
| `sender_postal_code` / `recipient_postal_code` | str(30) | no | | null | draft only | no |
| `sender_country_code` / `recipient_country_code` | str(2) | **yes at confirmation** | normalized ISO 3166-1 alpha-2; an unrecognized value is rejected, never silently dropped | null | draft only | no |
| `sender_country_input` / `recipient_country_input` | str(80) | no | what the staff member typed, kept for display | null | draft only | no |
| `recipient_delivery_note` | str(400) | no | | null | draft only | no |
| `declared_value` | numeric(12,2) | no | `>= 0`; describes the goods, **not** what the customer paid | null | `shipment:write` | no |
| `declared_value_currency` | str(3) | no | three letters | null | `shipment:write` | no |
| `rebooked_to_shipment_id` | FK shipments | no | set when this booking is cancelled and replaced | null | `shipment:cancel` | no |
| `cancelled_by_user_id` | FK users | no | `ON DELETE SET NULL` | null | `shipment:cancel` | no |
| `confirmed_by_user_id` | FK users | no | `ON DELETE SET NULL` | null | none | no |

**Removed in Phase 2:** `packages_delivered_count`. It was an unused stored counter;
delivered progress is derived from `shipment_packages` instead (DEC-0030).

**Address snapshots are copies.** They are written from the address book at draft or
confirmation time and never rewritten afterwards, which is what makes AC-5 hold. The
`*_address_id` columns record where the values came from; nothing reads through them.

**Route locking.** `route_group` and `direction` are editable only while
`booking_state = 'draft'`. After confirmation the service refuses a change, because the
Solaris ID already encodes the route (CRM.md section 6). Correcting a route is
cancel-and-rebook.

---

## `booking_confirmations`

One row per confirmed booking. This table is the concurrency and idempotency control
(DEC-0031); it is not a log.

| Field | Type | Required | Notes |
|---|---|---|---|
| `shipment_id` | FK shipments | yes | **unique** — a draft can be confirmed exactly once, which is what stops a double-click or two concurrent requests producing two bookings |
| `idempotency_key` | str(120) | yes | **unique** — a retried request finds this row and returns the original booking |
| `request_fingerprint` | str(64) | yes | SHA-256 of the material booking data; reusing a key for different data is a conflict, not a silent return |
| `public_id` | str(30) | yes | the Solaris ID issued by this confirmation |
| `confirmed_at` | datetime UTC | yes | |
| `confirmed_by_user_id` | FK users | no | `ON DELETE SET NULL` |
| `generation_attempts` | int | yes | how many suffixes were tried before a unique one landed |

The fingerprint covers customer, route group, direction, service, transport mode, booking
reference, contents, declared value and currency, both address snapshots, and every
package's canonical measurements. It deliberately excludes everything confirmation itself
sets, so a genuine retry matches.

---

## `shipment_packages`

| Field | Type | Required | Notes |
|---|---|---|---|
| `shipment_id` | FK shipments | yes | `ON DELETE CASCADE` |
| `sequence` | int | yes | unique per shipment; **never renumbered**, so a cancelled package does not free its number |
| `package_reference` | str(40) unique | no | `SX-VCA-7K9D2M4R8T6W-01`; **null until the parent booking is confirmed**, so a draft exposes no public reference |
| `is_active` | bool | yes | false once cancelled; the reference is retained |
| `cancelled_at` / `cancellation_reason` | datetime / str(255) | no | |
| `length_value`, `width_value`, `height_value` | numeric(10,2) | no | **as entered** |
| `dimension_unit` | enum | yes | `cm \| in`, default `cm` |
| `length_cm`, `width_cm`, `height_cm` | numeric(10,2) | no | canonical centimetres, derived once on write |
| `weight_value` | numeric(10,3) | no | as entered |
| `weight_unit` | enum | yes | `kg \| lb`, default `kg` |
| `weight_kg` | numeric(10,3) | no | canonical kilograms |
| `contents_summary` | str(400) | no | |
| `handling_note` | str(200) | no | printed on the label when present |
| `warehouse_location` | str(60) | no | printed on the label when present |
| `operational_state` | enum | yes | derived from this package's events; `event_service` is the only writer |
| `delivered_to_recipient_at` | datetime | no | set **only** by a `delivered_to_recipient` event |
| `created_by_user_id` | FK users | no | `ON DELETE SET NULL` |

**Table constraint `ck_shipment_packages_positive_measurements`:** every supplied canonical
measurement must be `> 0`. `NULL` means "not recorded", which is a different and
legitimate answer; zero is rejected.

All arithmetic uses `Decimal`. `12.5 lb` stores `12.500` entered and `5.670` canonical
exactly — a binary float would make measurement equality a question rather than a fact.

**Conversions:** `1 in = 2.54 cm` exactly; `1 lb = 0.45359237 kg` exactly.

---

## Derived package progress (computed, never stored)

Computed by `package_service.progress`.

| Derived value | Definition |
|---|---|
| `total` | all package rows, active and cancelled |
| `active` | `is_active` rows |
| `cancelled` | `total - active` |
| `delivered` | active rows with `delivered_to_recipient_at` set |
| `summary` | `"{delivered} of {active} packages delivered"` |

Cancelled packages are counted separately and never inflate or deflate the ratio, so
"1 of 3 delivered" stays truthful after a package is withdrawn.

---

## `shipment_legs`

| Field | Type | Required | Notes |
|---|---|---|---|
| `shipment_id` | FK shipments | yes | `ON DELETE CASCADE` |
| `sequence` | int | yes | unique per shipment; the leg order |
| `leg_type` | enum | yes | `origin_pickup \| consolidation_linehaul \| destination_handling \| final_delivery` |
| `provider_name` / `service_display` | str(80) / str(120) | no | **display only**; a carrier name never implies an integration |
| `origin_label` / `destination_label` | str(160) | no | |
| `origin_country_code` / `destination_country_code` | str(2) | no | normalized ISO code |
| `is_final_recipient_delivery` | bool | yes | false for a leg that ends at a Solaris facility |
| `consolidation_reference` | str(60) | no | internal master reference; never exposes other customers |
| `status` | enum | yes | `planned \| in_progress \| completed \| cancelled` |
| `scheduled_at` / `completed_at` | datetime | no | |
| `internal_notes` | text | no | never customer-facing |

Edit: `tracking:write`.

## `shipment_leg_packages`

`leg_id` + `package_id`, **unique together**. This association is why one package can
travel on several legs and several packages can share one leg.

## `leg_tracking_references`

| Field | Type | Required | Notes |
|---|---|---|---|
| `leg_id` | FK shipment_legs | yes | `ON DELETE CASCADE` |
| `package_id` | FK shipment_packages | no | null means the reference covers the whole leg (a consolidated master reference) |
| `carrier_name` | str(80) | yes | from a documented list, or Other |
| `tracking_number` | str(120) | yes | as typed |
| `public_url` | str(500) | no | validated https carrier link; **stored and displayed, never fetched** |
| `source_mode` | enum | yes | Phase 2 accepts `manual` and `external_link` only; `connected_api` is refused until Phase 4 verifies a provider |
| `is_active` | bool | yes | |
| `retired_at` / `retired_reason` | datetime / str(255) | no | a superseded reference is retired, never overwritten |

Assigning, changing, or retiring a carrier reference never alters the Solaris Shipment ID
or a package reference (AC-6).

---

## `shipment_events` (manual operational events)

| Field | Type | Required | Notes |
|---|---|---|---|
| `shipment_id` | FK shipments | yes | `ON DELETE CASCADE` |
| `package_id` | FK shipment_packages | no | an event with no package applies to every active package, and one row is written per package |
| `leg_id` | FK shipment_legs | no | `ON DELETE SET NULL` |
| `event_type` | enum | yes | 15 normalized types |
| `operational_state` | enum | yes | the normalized state the type maps to |
| `occurred_at` | datetime UTC | yes | when it happened; cannot be in the future |
| `recorded_at` | datetime UTC | yes | when staff entered it — **stored separately**, so a late entry cannot look like a fresh scan |
| `location_label` | str(160) | no | |
| `location_country_code` | str(2) | no | normalized ISO code |
| `internal_detail` | text | no | **never customer-facing** |
| `is_public_update` | bool | yes | explicit approval; default false |
| `public_update_text` | str(400) | no | required when `is_public_update`; supplying it without the flag is rejected |
| `is_final_recipient_delivery` | bool | yes | only a `delivered_to_recipient` event may set it |
| `source` | str(20) | yes | `manual` in Phase 2 |
| `is_voided` / `voided_at` / `voided_reason` | | no | corrections void an event; nothing is deleted |
| `recorded_by_user_id` | FK users | no | `ON DELETE SET NULL` |

Edit: `tracking:write`.

### Event type to operational state

| Event type | Operational state | Completes a package? |
|---|---|---|
| `booked` | Booked | no |
| `awaiting_parcel` | Awaiting parcel | no |
| `received_at_solaris` | Received at warehouse | **no** — a warehouse is a milestone |
| `processing` | Processing | no |
| `departed_origin` | Departed origin | no |
| `in_transit` | In transit | no |
| `customs_processing` | Customs processing | no |
| `arrived_destination` | Arrived destination | **no** |
| `out_for_delivery` | Out for delivery | no |
| `delivered_to_collection_point` | Out for delivery | **no** — a collection point is not confirmed final delivery |
| `delivered_to_recipient` | Delivered | **yes** — the only type that does |
| `delivery_attempted` | Delivery attempted | no |
| `exception` | Exception | no |
| `return_in_progress` | Return in progress | no |
| `returned` | Returned | no |

### Derived shipment status

Computed by `event_service.recompute_status`, in this order:

1. Booking cancelled → **Cancelled**.
2. No active packages → **Cancelled** (an honest neutral state, not a delivery claim).
3. Every active package delivered → **Delivered**, with `delivered_at` the latest of them.
4. Some but not all delivered → **Partially delivered** (AC-7).
5. Any active package in Exception, Delivery attempted, or Return in progress → that state.
6. Otherwise the **least advanced** active package's state, which is why a warehouse
   receipt for one parcel does not advance the whole booking.

A package's own state is the latest event by `(occurred_at, recorded_at, id)`. States are
never ranked to decide whether an update may apply, so a late older event cannot regress a
newer valid state (DEC-0037).

`shipments.first_handoff_at` — the qualifying-shipment trigger — is set by the earliest
event representing real custody, and is never moved once set.

---

## `label_print_jobs` and `label_print_job_packages`

| Field | Type | Notes |
|---|---|---|
| `shipment_id` | FK shipments | `ON DELETE CASCADE` |
| `kind` | enum | `single \| selected \| all_active` |
| `is_reprint` | bool | true when this shipment already had a generation record |
| `page_count` | int | one page per selected active package |
| `document_sha256` | str(64) | PDF generation is deterministic, so an identical reprint has an identical digest |
| `generated_at` | datetime UTC | |
| `generated_by_user_id` | FK users | `ON DELETE SET NULL` |

`label_print_job_packages` stores `job_id`, `package_id`, and the `package_reference`
**as printed**, so a reprint can be shown to carry the same identifiers.

These record that a PDF was *generated and downloaded*. Nothing here claims a physical
printer produced a label, because no print system reports back (CRM.md section 8).
Read: `shipment:read`. Generate: `label:generate`.

---

## `users`, `user_sessions`, `organization_settings`, `audit_events`, `counters`

| Table | Notes |
|---|---|
| `users` | `email` unique, `password_hash` (Argon2), `role`, `is_active`, `timezone`, `last_login_at`. No shared accounts. |
| `user_sessions` | `session_token_hash` and `csrf_token_hash` (SHA-256 digests only), created/last-seen/expires/revoked timestamps, IP, user agent |
| `organization_settings` | brand, legal entity, office timezone, default currency, tracking base URL, the three lifecycle thresholds, the three automation-rule toggles, `is_demo_environment` |
| `audit_events` | `occurred_at`, actor, `action`, `entity_type`, `entity_id`, `summary`, redacted `detail_json`, IP. Secrets are replaced with `[redacted]` and personal values with `[changed]`. |
| `counters` | durable allocator for `STCA-000001`; incremented inside the caller's transaction |
| `role_merge_provenance` | **Migration-owned, not application data.** Created by Alembic revision `a1c7f4d92b30` to make the Customer Service merge reversible (DEC-0088). Holds `user_id`, `previous_role`, `migration_id`, `recorded_at` — and deliberately nothing else: no credential, no session token, no profile field. No ORM model maps it and no route reads it. The downgrade restores each role from it, deletes only the rows that migration wrote, and drops the table when nothing else has rows in it |

`users.role` holds one of **four** values: `admin`, `operations`, `marketing`,
`read_only_manager`. `customer_service` was a fifth until September 2026 and appears in
rows written before revision `a1c7f4d92b30`; the migration maps it to `operations`
(DEC-0088). Historical `audit_events` rows still record it by name, correctly — they
describe what was true when they were written.

Audited actions in Phase 1: customer create/update/archive/restore/merge, referral
create, address create/update/archive, consent record, suppression release, task
create/update/complete, segment create/update/delete, settings update, staff
create/role change/activate/deactivate, customer export, login, logout, session revoke,
service issue resolve.

Added in Phase 2: `shipment.draft_create`, `shipment.update`, `shipment.confirm` (with the
issued ID and the number of generation attempts), `shipment.cancel`, `shipment.rebook`,
`shipment.financials_update`, `package.create`, `package.update`, `package.cancel`,
`shipment.leg_create`, `shipment.leg_update`, `shipment.leg_delete`,
`shipment.tracking_reference_add`, `shipment.tracking_reference_retire`,
`shipment.event_record`, `shipment.event_void`, and `shipment.label_generate`.

Redaction still applies: an event's `internal_detail` is a personal-detail key and is
recorded as `[changed]`, never copied into the audit payload.

---

## Timezone

All timestamps are stored in **UTC**. The frontend renders them in the configured office
timezone (`America/Toronto` by default) and shows the zone where it matters
operationally.

---

## The public tracking response (Phase 3)

This section is the contract for `GET /api/v1/public/track/{reference}`. It is not a
summary of the code — it is the list the code is checked against, by
`backend/tests/test_public_privacy.py`, which scans the raw JSON recursively for both
forbidden names and forbidden values.

Nothing here is stored. The public response is assembled on read from Phase 2 tables;
**Phase 3 added no columns and no migration.**

### The allowlist

Every field the public endpoint may return. A field is present because a line in
`public_tracking_service.build_result` assigns it.

| Field | Type | Meaning | Source |
|---|---|---|---|
| `shipment_reference` | str | The Solaris Shipment ID | `shipments.public_id` |
| `matched_reference_type` | `shipment` or `package` | Which form was submitted | the request |
| `selected_package_reference` | str or null | The package that was scanned, when one was | `shipment_packages.package_reference` |
| `route_group` | `VCA`/`CAV`/`CAD`/`XUS` | Route code | `shipments.route_group` |
| `route_label` | str | English route name; the page localizes from the code | `ROUTE_GROUP_LABELS` |
| `origin.city` | str or null | **Coarse** origin city | `shipments.sender_city` |
| `origin.country_code` | str(2) or null | ISO code | `shipments.sender_country_code` |
| `origin.country_label` | str or null | English country name, else the code | derived |
| `destination.*` | | The same three fields for the destination | `shipments.recipient_city` / `recipient_country_code` |
| `status` | enum | Normalized operational state | `shipments.operational_state` |
| `status_label` | str | English label; the page localizes from the code | `value_label` |
| `package_count_active` | int | Active packages | derived |
| `package_count_cancelled` | int | Cancelled packages, counted separately | derived |
| `package_count_delivered` | int | Active packages delivered to the recipient | derived |
| `progress_summary` | str | "1 of 3 packages delivered" | `package_service.progress` |
| `packages[].package_reference` | str | Stable package reference | `shipment_packages` |
| `packages[].status` / `status_label` | enum / str | That package's normalized state | derived |
| `packages[].is_selected` | bool | Whether this is the scanned package | the request |
| `packages[].is_cancelled` | bool | Shown as cancelled, never hidden | `is_active` |
| `packages[].delivered_at` | datetime or null | Final-recipient delivery time | `delivered_to_recipient_at` |
| `estimated_delivery_at` | datetime or null | **Only** when genuinely supplied | `shipments.estimated_delivery_at` |
| `delivered_at` | datetime or null | Overall delivery time | derived |
| `cancelled_at` | datetime or null | Cancellation time | `shipments.cancelled_at` |
| `timeline[].status` / `status_label` | enum / str | The milestone's normalized state | `shipment_events.operational_state` |
| `timeline[].message` | str | **The approved public wording** | `shipment_events.public_update_text` |
| `timeline[].occurred_at` | datetime | When it happened | `shipment_events.occurred_at` |
| `timeline[].location` | place or null | Coarse location, the same three fields | `location_label`, `location_country_code` |
| `timeline[].package_references` | str[] | Which packages a grouped milestone covers | derived |
| `timeline[].source_label` | `manual_update` | Never claims a provider reported anything | constant |
| `tracking_state` | enum | How this shipment is tracked — see below | derived |
| `last_public_update_at` | datetime or null | Newest approved **manual** update | derived |
| `carrier_link.carrier_name` | str | Carrier whose page is linked | `leg_tracking_references.carrier_name` |
| `carrier_link.url` | str | Validated public carrier link | `leg_tracking_references.public_url` |
| `data_mode` | `live` or `demo` | Whether the record is synthetic | `shipments.is_demo_record` |
| `help_url` | str or null | Configured contact link, or absent | `PUBLIC_HELP_URL` |
| `timezone` | str | IANA zone the page renders times in | `organization_settings.office_timezone` |

The failure body is two keys and nothing else: `code` and `message`.

### The forbidden list

None of these may appear at any depth of a public response, by name **or** by value. The
value half is what makes the test rename-proof: a name-only check is defeated by a
refactor, and a refactor is exactly when this breaks.

| Category | Fields |
|---|---|
| Customer identity | database id, `customers.public_id` (`STCA-…`), full name |
| Sender and recipient | name, company, and any address-book identifier |
| Contact | email and phone in any form, entered or normalized |
| Address | address lines 1 and 2, postal code, province/state, delivery note |
| Internal identifiers | every row id — shipment, package, leg, event, user — plus `booking_reference`, `idempotency_key`, `source_system`, `source_record_id` |
| Internal narrative | `internal_detail`, `internal_notes`, CRM notes, `cancellation_reason`, `voided_reason`, `retired_reason`, void state |
| Money | `declared_value`, selling amount, costs, surcharges, discounts, refunds, currency, payment state, any coverage figure |
| Carrier and consolidation | `tracking_number` as a field of its own, `consolidation_reference`, master references, raw provider payloads or statuses, transport legs |
| Staff | any staff name, email, or id; `recorded_by`, `generated_by`, owner |
| Audit | audit entries and history of any kind |
| Proof of delivery | signatures, images, documents |
| Authentication | session or CSRF values, credentials, permissions, role |
| Operational detail | contents description and summary, measurements, weight, handling note, warehouse location |
| Other customers | anything belonging to another shipment sharing a consolidation |

**One deliberate nuance.** A public carrier tracking *link* is the carrier's own address
for that parcel, and every carrier's public tracking page embeds the tracking number in
its URL. `CRM.md` section 10 permits "an optional validated public carrier link"; what it
forbids is exposing the number *separately*, as a field a scraper can read without
following a link. So the number may appear inside `carrier_link.url` and nowhere else —
there is no `tracking_number` field beside it, and
`test_the_carrier_tracking_number_appears_only_inside_the_approved_link` pins that
distinction down so removing the exclusion cannot quietly widen it.

### Reference normalization and validation

Two jobs, deliberately separate (`app/core/public_reference.py`).

**Normalization is forgiving**, because a handheld scanner, a phone keyboard, and a
pasted email each mangle an identifier differently:

| Input | Handling |
|---|---|
| Lowercase | Uppercased |
| Leading and trailing spaces, tabs, newlines | Removed |
| Internal spaces (`SX -CAV- 7K9…`) | Removed |
| Zero-width space, ZWNJ, ZWJ, byte-order mark | Removed |
| En dash, em dash, figure dash, non-breaking hyphen, minus sign, fullwidth hyphen, underscore | Converted to `-` |
| Surrounding quotes, brackets, guillemets; a trailing full stop or comma | Stripped from the ends only |
| Anything over 120 characters | **Refused** as not a reference, producing the ordinary generic 404 (see below) |

The dash conversion matters more than it looks. Mail clients and word processors
autocorrect a hyphen between capitals into an en dash, so a customer who received their ID
by email often pastes `SX–CAV–…`. The internal search *removes* those characters, which
would turn the identifier into an unrecognizable run of letters; the public normalizer
converts them, so the separator survives.

**Validation is strict**, and runs after normalization. Full match only:

```text
shipment:  SX-(VCA|CAV|CAD|XUS)-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{12}
package:   the same, plus -(0[1-9]|[1-9][0-9])
```

The alphabet is imported from `identifier_service`, so the validator and the generator
cannot drift apart. `-00` is rejected because sequence numbering starts at 1. A value that
does not match is never sent to the database.

There is **no** partial search, no customer-name search, no phone or email search, and no
booking-reference search on the public surface.

### Generic not-found behaviour

Seven different situations produce **one** response — same status, same body, same
message, same headers:

1. the reference is not a Solaris reference at all;
2. it is well formed but was never issued;
3. it belongs to a draft, which has no customer-facing identifier;
4. it belongs to a demo record and the environment is production;
5. it is longer than 120 characters;
6. it is empty — `/api/v1/public/track/` or `/api/v1/public/track`;
7. it carries extra path separators — `/track/SX-CAV-…/01/02`.

Rows 5 to 7 are the **Phase 3 correction** (DEC-0059). They previously escaped the
application's policy: 5 produced FastAPI's 422 with the constraint named and the
submitted value echoed back, and 6 and 7 produced Starlette's router 404,
`{"detail": "Not Found"}`. None of the three consumed a rate-limit allowance. The route
now takes the reference as a catch-all `{reference:path}` parameter with no framework
constraint, and the 120-character bound is enforced in `parse_public_reference`, where
exceeding it means the same thing as any other malformed value.

```json
{
  "code": "tracking_not_found",
  "message": "We could not find tracking information for that reference. Check the Solaris Shipment ID or package reference on your label or receipt and try again."
}
```

The message names neither the format nor existence. A lookup therefore cannot be used to
confirm that an identifier exists, which is what keeps the high-entropy identifier the
only thing standing between a stranger and a customer's parcel status.

### Tracking states

`tracking_state` says how a shipment is tracked. Phase 4 provider synchronization does not
exist, so no value here implies anything is fetched, polled, or synchronized.
`connected_api` is deliberately **absent from the vocabulary** rather than present and
unused, so it cannot be selected by accident.

| Value | Meaning |
|---|---|
| `cancelled` | The booking was withdrawn. Checked first: it is the most useful thing to say. |
| `manual_updates` | Staff-entered, audited milestones. The only real source of events today. |
| `external_link_only` | A validated public carrier link exists; Solaris publishes no milestones. |
| `demo` | A synthetic record with no other honest story to tell. |
| `tracking_unavailable` | No tracking information at all. |
| `no_public_milestones` | Confirmed; nothing published yet. |

**Demo is a fallback, not an override.** `data_mode` and the persistent banner it drives
already say a record is synthetic, twice and in the reader's language; having
`tracking_state` say it a third time displaced the one thing that line exists to say. A
demo row with published milestones therefore reports `manual_updates` exactly as a real
one would.

There is no `last_synced_at`, no `last_carrier_update`, and no freshness age. Those belong
to Phase 4 and are reserved rather than approximated. `last_public_update_at` is the
occurred time of the newest approved **manual** update, and is labelled as exactly that.

### What the public timeline may read

An event appears only when **all** of these hold:

* `is_voided` is false;
* `is_public_update` is true — a staff member explicitly ticked it;
* `public_update_text` is present and non-empty — they wrote customer-facing wording;
* the event belongs to the matched shipment.

`internal_detail` is not read by the query and is not reachable from the result shape. An
internal-only event still influences the derived overall status — that is the point of
deriving status from events — but its text, its location detail, and its existence never
appear as a timeline entry.

Ordering is `(occurred_at, recorded_at, id)`, newest first, so two milestones stamped the
same minute do not swap places between requests. Rows that agree on state, wording,
occurred time, and location are grouped into one entry listing the references they cover
(DEC-0045); the grouping is display only and package progress is unaffected.

**Public update text is not translated.** It is free text a staff member wrote, stored in
whatever language they wrote it, and shown verbatim. The surrounding page — status names,
route names, labels, dates — is fully bilingual, but a sentence typed by a person can only
be shown as typed. `docs/STAFF_GUIDE.md` records what that means for staff writing
updates for Vietnamese-speaking customers.

---

# Phase 4A — provider-neutral integration infrastructure

Five tables, added by migration `9d7dc78dd25c`. **None of them names a provider**, and
none of them can hold a credential. No row exists in any of them on a fresh installation,
and none is created by the seed command.

**No provider is connected. No request has ever been made to a carrier or to ShipStation
by this application.** These tables are the part of the integration whose correctness does
not depend on which product the account turns out to hold.

## What is never stored, anywhere in these tables

| Never stored | Why |
|---|---|
| Authorization or proxy-authorization header | No column exists. `redaction.safe_headers` keeps four diagnostic headers by allowlist and **drops** the rest rather than masking them — a masked entry still records that the header was present |
| API keys, access tokens, session cookies | No column exists; `credential_ref` holds the *name* of an environment variable, never its value |
| Signature values | Verified on arrival and then forgotten. Keeping one would put a value derived from the shared secret in the database for no operational purpose |
| Complete request header sets | No column exists |
| Unbounded bodies | A payload over `INTEGRATION_WEBHOOK_MAX_BYTES` is **refused** and stored as a digest with `payload_omitted = true` |
| Exceptions or stack traces | `safe_exception_summary` returns the exception *type name*; provider client exceptions routinely carry the request URL and sometimes its headers |
| Raw provider status on a public response | `raw_status` is preserved here for audit and is absent from the public allowlist |

`backend/tests/test_integration_privacy.py` and `test_migrations_phase4a.py` assert this
structurally — a future column called `api_key` fails the build.

---

## `integration_connections`

A provider account this installation may talk to. **There are none.**

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `provider_key` | str(40) | Which adapter serves it. An application key, never a product name guessed from marketing material |
| `provider_api_version` | str(40) null | The API generation. Explicit because CRM.md section 9 forbids treating provider generations as interchangeable |
| `connection_key` | str(80) | Account identifier within the provider. **Not a credential.** Defaults to `unassigned` |
| `display_label` | str(120) null | What staff call it |
| `state` | str(30) | `not_configured` \| `disabled` \| `verification_required` \| `connected` \| `error` |
| `is_enabled` | bool | |
| `credential_ref` | str(120) null | The **name** of an environment variable, for example `SOLARIS_PROVIDER_API_KEY`. Never the value |
| `last_success_at`, `last_success_operation` | datetime, str(60) | Null until something genuinely succeeds |
| `last_error_at`, `last_error_code`, `last_error_summary` | datetime, str(40), str(400) | `last_error_code` is a `ProviderErrorKind` value, never a provider status code. The summary is redacted |
| `disabled_at`, `disabled_reason`, `disabled_by_user_id` | | Who switched it off, and why |

Unique on `(provider_key, connection_key)`.

**Why the table exists with no rows.** Deduplication has to be *scoped* to an account —
two accounts on one provider can legitimately emit the same event id — and a health panel
that can only ever say one thing needs somewhere for the second thing to come from later.

---

## `integration_webhook_inbox`

One durably stored inbound notification, written and committed **before** anything is
parsed, mapped, or applied. An acknowledgement is therefore a statement about storage
rather than a promise about business effect (CRM.md section 9).

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `provider_key`, `provider_api_version` | str(40) | Stored per row: a provider can run two generations at once during a migration, and a payload records which contract it was written against |
| `connection_key` | str(80) | Scope for deduplication. Non-null; `unassigned` before any account exists |
| `connection_id` | FK null | `SET NULL` |
| `received_at` | datetime | When it arrived. **Not** when anything happened |
| `content_type` | str(120) null | Enforced against a configured allowlist on arrival |
| `payload_bytes` | int | Length as received, before any bounding |
| `payload_text` | text null | The bounded body — whole, or absent. Never truncated |
| `payload_omitted` | bool | True when the body was refused for size and only its digest is kept |
| `payload_sha256` | str(64) | Over the exact bytes received. Survives the body being omitted |
| `provider_event_id` | str(200) null | When the provider supplies one |
| `payload_fingerprint` | str(64) | Adapter digest over the immutable event fields. Always present |
| `dedupe_key` | str(200) | Whichever of the two above is authoritative. **Non-null**, so the unique constraint constrains |
| `dedupe_basis` | str(30) | `provider_event_id` or `payload_fingerprint`. Informational, and deliberately **not** part of the unique key |
| `verification_state` | str(30) | See the authenticity table below |
| `verification_detail`, `verified_at` | str(255), datetime | Why, and when. Never a signature value |
| `processing_state` | str(30) | `pending` \| `running` \| `processed` \| `duplicate` \| `rejected` \| `failed` \| `failed_terminal` |
| `attempt_count`, `next_attempt_at` | int, datetime null | |
| `processed_at`, `rejected_at`, `failed_at` | datetime null | |
| `error_code`, `error_summary` | str(40), str(400) | Category and redacted phrase |
| `lease_owner`, `lease_token`, `lease_expires_at` | | Lease held while a worker processes it |
| `created_at`, `updated_at` | datetime | |

**Unique:** `(provider_key, connection_key, dedupe_key)` —
`uq_integration_webhook_inbox_dedupe`.

**The link to a normalized event** is stored once, on
`integration_provider_events.inbox_item_id`, and navigable from either side through the
`normalized_event` relationship. A column on both tables would be a circular foreign key
SQLite cannot express through SQLAlchemy metadata ordering, and one stored link cannot
disagree with itself (DEC-0073). `resulting_shipment_event_id` reads through it.

### Deduplication, and what a duplicate may and may not do

An event is recognized by its **provider event id** when the provider supplies one, and
otherwise by a **stable fingerprint** the adapter computes over the immutable fields of the
event. The adapter chooses those fields because only it knows which ones the provider
rewrites between deliveries — a fingerprint over a retry counter or a delivery timestamp
would change on every redelivery and defeat the mechanism entirely.

A duplicate delivery **may** receive a successful acknowledgement: the event really was
received, the first time. It must not create a second timeline entry, a second delivered
count, a second shipment-state change, a second revenue figure, a second follow-up task,
or an audit action implying a separate business event — and it does not, because it creates
no new inbox row, no new job, and no new normalized event.

**Concurrent duplicate deliveries from separate sessions produce one inbox record and one
downstream effect.** That is a database guarantee, not an application check
(DEC-0060), and `test_integration_inbox.py` demonstrates it with two sessions on separate
connections.

### Authenticity states

| State | Meaning | May it become a normalized event? |
|---|---|---|
| `pending` | Received; authenticity not yet assessed | No |
| `signature_missing` | The adapter declares signatures and the payload carried none | **No.** No job is created; no retry can help |
| `signature_invalid` | A signature was present and did not verify | **No.** Forged. Stored for review, never retried |
| `signature_valid` | Present and verified | Yes |
| `unsigned_untrusted` | The provider offers no signature this adapter can check | **No** — but it may enqueue an authenticated read |
| `verified_by_read` | Confirmed by an authenticated read against the provider | Yes |

**The unsigned-webhook rule.** When a provider has no trustworthy signature mechanism, a
notification is a hint that something may have changed. The only thing it may cause is one
authenticated question to the provider, and the *answer* is what may move a parcel. The
status claimed in the notification body is ignored entirely — a notification claiming
delivery, answered by a provider saying "in transit", leaves the parcel in transit.

Bounds are configurable: `INTEGRATION_WEBHOOK_MAX_BYTES` (256 KB) and
`INTEGRATION_WEBHOOK_CONTENT_TYPES` (`application/json`).

---

## `integration_provider_events`

The normalized mapping layer. Preserves what the provider said, for audit and for
debugging a mapping, while the rest of the application sees only Solaris vocabulary.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `provider_key`, `provider_api_version`, `connection_key` | | |
| `provider_event_id` | str(200) null | |
| `provider_event_fingerprint` | str(64) | Always present, so the unique constraint holds |
| `tracking_assignment_id` | FK `leg_tracking_references` null | A tracking assignment *is* a `leg_tracking_references` row in this schema (DEC-0041) |
| `shipment_id`, `package_id`, `leg_id` | FK null | |
| `raw_status` | str(120) null | **Exactly what the provider called it.** Never published |
| `raw_status_detail` | str(1000) null | The provider description, bounded. Internal only, like `internal_detail` |
| `normalized_event_type` | str(40) | A `ShipmentEventType` value |
| `normalized_state` | str(30) | The `OperationalState` it maps to |
| `occurred_at` | datetime **null** | When the provider says it happened. Null when the provider said nothing |
| `occurred_at_timezone` | str(60) null | The zone the provider stated, when it stated one |
| `occurred_time_provenance` | str(30) | `provider_utc` \| `provider_offset` \| `local_no_timezone` \| `missing` |
| `received_at` | datetime | Separate from `occurred_at`, always |
| `verification_source` | str(30) | `signature_valid` or `verified_by_read`. Nothing else can produce a row here |
| `mapping_version` | str(40) | Which revision of the adapter mapping produced these values |
| `inbox_item_id` | FK unique null | The delivery this came from |
| `application_state` | str(30) | `pending` \| `applied` \| `skipped_duplicate` \| `skipped_superseded` \| `rejected` |
| `applied_shipment_event_id` | FK null | The shipment event this produced, when it produced one |
| `applied_at`, `application_detail` | datetime, str(255) | Why it was not applied, in application vocabulary |
| `corrects_event_id` | self FK null | A provider correction pointing at the event it corrects |
| `is_voided`, `voided_at` | bool, datetime | Withdrawn by a later correction. The row stays; only its effect is undone |

**Unique:** `(provider_key, connection_key, provider_event_fingerprint)`.

### Occurred time, and the rule about missing information

`occurred_at` and `received_at` are separate columns and always will be. A late delivery is
visible as a late delivery, which is what keeps an out-of-order event from looking like a
fresh scan.

| Provenance | What the provider supplied | What happens |
|---|---|---|
| `provider_utc` | An unambiguous UTC instant | Used |
| `provider_offset` | An explicit offset | Converted to UTC, and recorded as having come with an offset |
| `local_no_timezone` | A wall-clock time with no zone | **Stored and flagged.** Never silently treated as UTC |
| `missing` | No time at all | **The event is recorded and not applied.** `received_at` is never substituted |

A delivery time invented from the moment a message arrived is a fabricated milestone, and
the customer plans around it (DEC-0068).

### Applying a normalized event

Applying goes through `event_service.record_event` with `source = "provider"`, so every
Phase 2 invariant governs it. Nothing is re-implemented (DEC-0067). The consequences:

* one delivered package of three stays **Partially delivered**;
* an intermediate warehouse receipt is a **milestone**, not delivery — only
  `delivered_to_recipient` sets `delivered_to_recipient_at` (DEC-0036);
* a collection-point handover does not complete a shipment;
* an older **In transit** cannot regress **Delivered**: package state is the latest event
  by occurred time, and a late arrival is simply not the latest (DEC-0037);
* a **provider event never overwrites a manual one** — it never voids, edits, or deletes a
  staff row, and at an identical occurred time the manual row wins the tie (DEC-0066);
* **Solaris IDs and package references never change**;
* a provider event carries **no public update text**. `is_public_update` is false; the
  provider description goes to `internal_detail`.

Duplicate and out-of-order events remain durable and produce no business effect. A
provider re-reporting one milestone under a fresh event id produces two inbox rows, one
normalized event, and one timeline entry.

---

## `integration_jobs`

The durable queue. Queue state lives in the database, so it survives a process restart
unchanged.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `job_type` | str(50) | `process_webhook_inbox_item` \| `verify_notification` \| `reconcile_tracking_assignment` \| `refresh_tracking_assignment` \| `retry_provider_operation` |
| `provider_key`, `connection_key`, `connection_id` | | |
| `tracking_assignment_id`, `inbox_item_id`, `shipment_id` | FK null | |
| `status` | str(30) | `pending` \| `running` \| `succeeded` \| `failed` \| `failed_terminal` \| `cancelled` |
| `available_at` | datetime | When it may next be claimed |
| `attempt_count`, `max_attempts` | int | |
| `priority` | int | Lower runs first. A delivery notification does not queue behind a bulk refresh |
| `dedupe_key` | str(200) null | The job's **permanent** identity, kept for audit |
| `active_dedupe_key` | str(200) null **unique** | The same value while pending or running; NULL once it stops |
| `lease_owner`, `lease_token`, `lease_expires_at` | | |
| `last_attempt_at`, `next_retry_at` | datetime null | |
| `provider_retry_after_seconds` | int null | What the provider asked for, as received, so the backoff decision is auditable |
| `error_code`, `error_summary` | str(40), str(400) | Category and redacted phrase |
| `completed_at`, `failed_at` | datetime null | |
| `requires_review` | bool | The failed-job review queue, as a column |
| `manual_retry_count`, `last_manual_retry_at`, `last_manual_retry_by_user_id` | | Who intervened, and how often |

**Unique:** `active_dedupe_key`.

### Deduplication, leasing, and crash recovery

**At most one pending or running refresh per active tracking assignment.** The claim is the
unique `active_dedupe_key`, nulled when the job stops — so concurrent enqueues collide in
the database while a completed job stops constraining and a later legitimate reconciliation
is not blocked by history (DEC-0062).

**Claiming is atomic without `SELECT ... FOR UPDATE`**, which SQLite does not have. The
selection query is a hint; the decision is a conditional `UPDATE` whose `WHERE` clause
repeats every condition — still pending, still due, unleased or expired. Exactly one worker
sees `rowcount == 1` (DEC-0061).

**A crash strands nothing.** A lease expires and `reclaim_expired` returns the row to
pending. A **live** lease cannot be stolen: the same predicate refuses it. Reclaiming does
**not** reset the attempt count, or a poison payload would loop forever.

**Terminal jobs are not retried automatically.** Only an audited operator retry moves one,
and that retry adds one attempt rather than restarting the loop.

### Retry and `Retry-After`

| Failure kind | Treatment |
|---|---|
| `retryable` | Exponential backoff with **full jitter** |
| `rate_limited` | The provider's `Retry-After` used **exactly**, bounded by `INTEGRATION_RETRY_MAX_SECONDS` |
| `authentication` | Bounded to `INTEGRATION_AUTH_MAX_ATTEMPTS` (2), far below the general allowance |
| `malformed_payload`, `mapping`, `permanent` | **Terminal on the first attempt.** No retry changes a payload that does not parse or a status nothing maps to |

Backoff is `min(base * 2^(attempt-1), cap)` with the delay drawn uniformly from
`[0, window)`. Full jitter rather than none, because otherwise every failed job retries in
lockstep and a provider that has just come back up is hit by the whole backlog at once. A
provider `Retry-After` is **not** jittered: the provider said when to come back, and
spreading that out is ignoring it.

**A failed refresh never replaces a known status with "unknown".** Nothing is written on
the failure path; the shipment keeps the last state it legitimately had.

---

## `integration_worker_heartbeats`

| Column | Notes |
|---|---|
| `worker_name` | Unique. The lease owner identity |
| `mode` | `once` or `continuous` |
| `started_at`, `last_seen_at` | |
| `jobs_claimed`, `jobs_succeeded`, `jobs_failed` | Cumulative for this worker identity |
| `stopped_at` | Set on graceful shutdown, so a stopped worker is distinguishable from a dead one |

A row exists **only because a worker wrote it**. The health service reports a heartbeat
only when one is present, so "no worker has run" displays as exactly that rather than as a
stale timestamp or a reassuring default.

---

## Integration health

Every value is a real count or an explicit absence.

| Field | Today | Why |
|---|---|---|
| `any_provider_configured` | `false` | The adapter registry is empty |
| `connections[0].state` | `not_configured` | The only truthful state a registry with nothing in it can report |
| `provider_api_version` | `null` | Unverified |
| `last_success_at` | `null` | Nothing has ever succeeded, because nothing has ever run |
| `stale_assignment_count` | **`null`, not `0`** | No freshness rule exists. `0 stale` claims everything is fresh, which is stronger and falser than "we cannot tell" (DEC-0065) |
| `worker` | `null` unless a worker reported | |
| job and inbox counts | Real counts | |

Read with `integration:read` (admin, read-only manager). The retry and disable actions
need `integration:manage` (admin only) (DEC-0064).

---

# Phase 5A — reporting, import provenance, and export columns

Nothing in this section is stored. The reports are computed on request; the export column
lists are the privacy contract for what may leave the system; the two import tables hold
counts and outcomes and no cell value from any file.

## Report periods

Every report is bounded by a half-open interval `[start, end)`.

| Rule | Value |
|---|---|
| Timezone | `organization_settings.office_timezone` (default `America/Toronto`) |
| Start | Local midnight at the beginning of `from`, converted to UTC |
| End | Local midnight at the beginning of the day **after** `to`, converted to UTC |
| Maximum span | 731 days (two years plus a leap day) |
| Maximum distance from today | 50 years |
| Default when unspecified | The last 30 days, ending today |

**Why local rather than UTC.** A parcel handed over at 23:30 on 30 September in Mississauga
is September business. Cutting on UTC midnight would move it into October for four hours of
every day, and nothing on the report would say so. The offset is not a constant —
`America/Toronto` observes daylight saving — so the boundary is resolved through `zoneinfo`
for the specific date, never by adding a fixed number of hours (DEC-0076).

**Why half-open.** An inclusive end would either drop the last evening or count a shipment
on the boundary in two adjacent periods. Half-open intervals tile, which is the property
that makes adjacent periods sum to the whole.

`tzdata` is a declared backend dependency, and `create_app` refuses to start if the
configured timezone cannot be resolved. Before Phase 5A no timezone database was installed
on the development machine, so every "office timezone" conversion in the product had
silently been UTC since Phase 1; `zone()` now raises rather than substituting UTC, and
`office_timezone` is validated at the settings boundary.

### Bucket granularity

Derived from the span, never chosen by the caller, so the axis label always describes what
the buckets actually are.

| Span | Granularity | Bucket label |
|---|---|---|
| 1–31 days | `day` | `YYYY-MM-DD` |
| 32–182 days | `week` | `YYYY-MM-DD` of the Monday, in the organization timezone |
| 183–731 days | `month` | `YYYY-MM` |

A bucket with no activity is emitted as `0`. That is a **known** count, not an unknown
value: we know how many parcels were handed over last Tuesday, and the answer is none. It
is distinct from a *share* over an empty denominator, which is `null`.

## Rules common to every report

| Rule | Decision |
|---|---|
| **Qualifying shipment** | `booking_state = 'confirmed'` AND `first_handoff_at IS NOT NULL` AND `cancelled_at IS NULL` AND `is_return = false` — unchanged from Phase 1 |
| **Packages** | Never counted as shipments. Every shipment metric counts rows in `shipments`, once |
| **Transport legs** | Never counted as shipments. A shipment with four legs is one shipment |
| **Drafts** | Excluded everywhere except the booking-state distribution |
| **Cancelled bookings** | Excluded from qualifying figures; present in the booking-state distribution |
| **Rebooked shipments** | The cancelled original carries `cancelled_at` and is excluded; the replacement qualifies. A cancel-and-rebook pair contributes **one** shipment |
| **Returns** | `is_return = true` excluded from qualifying counts; reported on their own row |
| **Merged customers** | `merged_into_customer_id IS NOT NULL` excluded from every customer count. The merge moved their shipments to the survivor |
| **Missing values** | Unknown. Never converted to zero, never averaged over as zero |
| **Comparisons** | None computed. No prior-period delta, trend, or percentage change exists in Phase 5A |
| **Currency** | Never combined. Grouped by `currency`; shipments with none counted separately |
| **Carrier freshness** | Not reported. No provider is connected, so no such value exists (DEC-0075) |

## The nine reports

| Key | Scope | Metric | Definition |
|---|---|---|---|
| `customer_growth` | period | `created` | Customers whose `created_at` falls in the bucket, excluding merged records |
| | | `cumulative` | Customers with `created_at` before the bucket end, excluding merged records. Computed independently, not by running-summing `created` |
| `customer_lifecycle` | **current** | count per status | Derived lifecycle status over all non-merged customers, using the administrator-configured thresholds |
| `route_mix` | period | `count` | Qualifying shipments with `first_handoff_at` in the period, by `route_group` |
| | | `share` | `count / total`; `null` when the total is zero |
| `shipment_volume` | period | `count` | Qualifying shipments per bucket per `route_group`, bucketed by `first_handoff_at` in the organization timezone |
| `shipment_status` | period | booking states | All shipments with `booking_date` in the period, by `booking_state`. The only report where drafts appear |
| | period cohort, **current** state | operational states | Qualifying shipments with `first_handoff_at` in the period, by their *current* `operational_state` |
| | period | `returns` | `is_return = true`, confirmed, uncancelled, `first_handoff_at` in the period |
| `repeat_customers` | period | `shipping_customers` | Distinct non-merged customers with ≥1 qualifying shipment in the period |
| | | `repeat_customers` | Of those, the ones with ≥2 qualifying shipments where `first_handoff_at < period_end` — lifetime **as of the period end** |
| | | `first_time_customers` | `shipping_customers − repeat_customers` |
| | | `share` | `repeat / shipping`, or `null` when nobody shipped. **Not a cohort retention rate** |
| `follow_up_workload` | period | `created`, `completed` | Tasks created in the period; tasks with status `completed` whose `completed_at` falls in it |
| | **current** | `open_now`, `overdue_now` | Tasks currently open; open tasks with `due_at` in the past |
| `shipment_exceptions` | **current** | `count` by route | Shipments in `exception`, `delivery_attempted`, or `return_in_progress`, excluding cancelled |
| | **current** | by tracking source | The same shipments by the source mode of their **active** tracking references: `manual`, `external_link`, `none`. A shipment with references in more than one mode counts under each, so this column can total more than the shipment count |
| `financial_summary` | period | `recorded_revenue` | Per currency: Σ(`selling_amount` + `surcharges_amount` − `discount_amount` − `refund_amount`) over shipments where `selling_amount` is recorded |
| | | `recorded_cost` | Σ(`shipping_cost`) where recorded. **Absent** without `financial_cost:read` |
| | | `gross_profit` | `revenue − cost`, only when both are recorded for that currency; otherwise `null` |
| | | coverage | `shipments_with_revenue`, `shipments_with_cost`, `shipments_total`, `unknown_currency_shipments` |

### Permission gating is structural

`report:read` opens every report. The financial report is **absent from the response** for
a caller without `financial:read` — not empty, not null, not masked — and asking for it by
key reads as an unknown report rather than a 403, so the caller does not learn it exists.
Without `financial_cost:read` the `recorded_cost` and `gross_profit` keys are absent from
every row and from the column list.

---

## `import_batches`

One row per **committed** import. A preview writes nothing, so an abandoned preview leaves
no row here (DEC-0078, DEC-0079).

| Field | Type | Required | Notes |
|---|---|---|---|
| `public_id` | str(20) unique | yes | `IMP-000001`, from the same durable counter mechanism as customer IDs |
| `kind` | str(30) | yes | `customers`. The column exists so adding shipment import later is not a migration of this table |
| `file_name` | str(255) | no | Operator-supplied metadata about the upload, **not** content from it |
| `content_sha256` | str(64) | yes | Digest of the exact bytes committed. This is what lets a commit refuse a file that changed since it was previewed |
| `source_system` | str(60) | yes | `csv_import` unless the file named its own |
| `conflict_policy` | str(30) | yes | `skip` or `fill_blanks`. There is deliberately no `overwrite` |
| `row_count`, `created_count`, `matched_count`, `skipped_count`, `rejected_count` | int | yes | The durable completion summary |
| `committed_at` | datetime UTC | yes | |
| `committed_by_user_id` | FK users | no | `ON DELETE SET NULL` |

## `import_batch_rows`

What happened to one row of one committed import. **No name, email, phone, or address.**

| Field | Type | Required | Notes |
|---|---|---|---|
| `batch_id` | FK import_batches | yes | `ON DELETE CASCADE` |
| `row_number` | int | yes | 1-based as the operator sees it in the spreadsheet: the header is row 1 |
| `outcome` | str(20) | yes | `created` / `matched` / `skipped` / `rejected` |
| `reason_code` | str(60) | no | e.g. `duplicate_skipped`, `duplicate_not_reviewed`, `missing_contact`. A code, never a message containing a value |
| `customer_id` | FK customers | no | `ON DELETE SET NULL` |
| `source_record_id` | str(120) | no | The key the row was reconciled on |

Unique on `(batch_id, row_number)`.

## Import idempotency

`customers.source_system` and `customers.source_record_id` existed from Phase 1. Phase 5A
adds the constraint that makes them mean something:

```sql
CREATE UNIQUE INDEX uq_customers_source_record ON customers (source_system, source_record_id)
  WHERE source_system IS NOT NULL AND source_record_id IS NOT NULL;
```

`source_record_id` is the file's own column when it supplies one; otherwise it is
`row:<sha256 of the normalized identity>[:40]`, over the accent-folded name key, the
lowercased normalized email, and the phone match key. Most spreadsheet exports have no
stable key, and without one a second import would create a second copy of every person.

The index is **partial** because most customers are created by hand and carry neither
column. A plain unique index over two nullable columns is safe on SQLite, which treats
NULLs as distinct, but is not safe everywhere, and `CRM.md` section 3 requires a PostgreSQL
migration to stay practical.

## Fields an import may write

`full_name` (required), `email`, `phone`, `city`, `province_state`, `country_code`,
`preferred_language`, `category`, `business_name`, `business_type`,
`primary_shipping_purpose`, `primary_route_group`, `shipping_frequency`,
`estimated_monthly_shipments`, `preferred_contact_channel`, `best_contact_time`,
`contact_timezone`, `notes`, `tags`, `source_system`, `source_record_id`,
`source_created_at`.

Any other column is reported as unrecognized and its values are dropped. Headers are
matched after case-folding, accent-folding, and punctuation normalization; two headers that
normalize to the same field are refused as ambiguous rather than resolved by picking one.

**Consent is not importable and there is no code path for it.** A CSV cannot carry consent
evidence, and `CRM.md` section 11 requires that imported contact information is not
automatically marketing eligible and that an import cannot override a suppression.

---

## Export column allowlists

These lists are the privacy contract: a field not written here does not leave the system
through an export (DEC-0080). Columns marked with a permission are **absent** — header and
value together — for a caller without it.

### `customers` (`export:customers`)

`customer_id`, `full_name`, `phone`, `email`, `city`, `province_state`, `country_code`,
`preferred_language`, `category`, `business_name`, `declared_primary_route`,
`observed_primary_route`, `lifecycle_status`, `qualifying_shipments`, `bookings`,
`first_shipment_at`, `last_shipment_at`, `repeat_customer`, `do_not_contact`,
`email_marketing_eligible`, `sms_marketing_eligible`, `archived`, `date_added`,
`source_system`, `source_record_id`.

Deliberately absent: internal notes, service-restriction notes, interactions, consent
history, audit entries.

### `shipments` (`export:shipments`)

`solaris_shipment_id`, `customer_id`, `customer_name`, `route_group`, `direction`,
`service_type`, `transport_mode`, `booking_state`, `operational_state`, `payment_state`,
`is_return`, `package_count`, `packages_active`, `packages_delivered`, `origin_city`,
`origin_country`, `destination_city`, `destination_country`, `booking_date`,
`first_handoff_at`, `estimated_delivery_at`, `delivered_at`, `cancelled_at`.

With `financial:read`: `currency`, `selling_amount`, `discount_amount`, `refund_amount`.
With `financial_cost:read`: `shipping_cost`, `surcharges_amount`.

Deliberately absent: street address lines, postal codes, recipient phone and email, sender
contact details, internal notes, carrier tracking numbers.

### `packages` (`export:shipments`)

`package_reference`, `solaris_shipment_id`, `customer_id`, `sequence`, `route_group`,
`active`, `operational_state`, `length_cm`, `width_cm`, `height_cm`, `weight_kg`,
`entered_dimension_unit`, `entered_weight_unit`, `contents_summary`, `warehouse_location`,
`delivered_to_recipient_at`, `cancelled_at`.

One row per package. This is the only file where a package is a row; every shipment metric
still counts the parent shipment once.

### `marketing_segment` (`export:marketing_segment`)

`customer_id`, `full_name`, `channel`, `address`, `preferred_language`, `city`,
`country_code`, `consent_status`, `consent_basis`, `consent_obtained_at`.

Members who are not marketing eligible on the selected channel are **omitted from the
file**, not flagged inside it. A flagged row in a spreadsheet is one careless sort away
from being mailed.

### Report results (`export:reports`)

The allowlist is the report's own declared column list, so an exported report cannot carry
a field the screen did not show — including a financial column the caller's role caused to
be omitted.

### File format

UTF-8 with a byte-order mark (so Excel opens it as UTF-8 and Vietnamese survives), CRLF
line endings, `csv` module quoting. Any cell beginning with `=`, `+`, `-`, `@`, tab,
carriage return, or newline is prefixed with an apostrophe — prefixed, never stripped,
because stripping would silently alter an address whose first character is legitimately
whitespace (DEC-0081). Exports stream in bounded pages and are never written to disk.

---

## Phase 5A1 — Approved public update wording

### `shipment_events.public_update_template_key`

| | |
|---|---|
| Type | `VARCHAR(80)`, nullable |
| Added by | migration `e5623fcf8018` |
| Source | Staff choice in the event form, validated against the catalogue |
| Meaning | Which approved sentence this milestone publishes |

A key into `backend/app/content/public_update_templates.json`. Mutually exclusive with
`public_update_text`: an event carries a template key **or** a typed sentence, never both,
and `record_event` rejects a payload with both. `NULL` on every event recorded before the
migration, and on any event whose wording staff typed themselves.

Keys are immutable. Wording is changed by adding a new key (`in_transit.v2`), never by
editing an existing one, because the row stores the key and the sentence is resolved at
read time — editing in place would rewrite what a customer was already told.

A key that no longer exists in the catalogue renders as nothing rather than raising, so a
retired template cannot take the tracking page down.

### `timeline[].message_template_key` (public API)

The same key, published. It is the twenty-fifth field on the public response and the only
one added since Phase 3. It names approved wording and carries nothing about the shipment,
the customer, or who recorded the event.

`message` remains populated for every entry: free text where staff typed it, and the
template rendered in the catalogue's default language (English) where they chose one, so a
consumer that cannot resolve keys still reads a sentence. The tracking page prefers the
key and renders it in the reader's chosen language.

### Template catalogue

| Field | Meaning |
|---|---|
| `version` | Catalogue format version |
| `event_types.<type>.default_public` | Whether the publish box starts ticked (DEC-0083) |
| `event_types.<type>.templates` | Ordered keys offered for that event type; order is the UI's order |
| `templates.<key>.text.en` / `.vi` | The approved sentence. Both are required |

Validated at import time by `check_catalogue`: every template needs both languages, every
event type must be a real `ShipmentEventType`, every referenced key must exist, and no
template may be unreachable. A malformed catalogue stops the application from starting
rather than failing when a staff member clicks publish.

Templates carry no location, date, or interpolation — the timeline already shows place and
time as their own fields — and none may describe a carrier as having reported anything,
since no provider integration exists (DEC-0075).

---

# Customer Account (Phase 9)

Nine tables. None of them is canonical customer data, none of them is a staff table, and no
existing table gained a column pointing at any of them — the link lives in its own table, in
one direction only, so a `customers` row never depends on the account feature existing
(DEC-0091).

Retention classification appears on each table. Two categories are settled and two are not:
**credential material** (sessions, tokens) is purgeable immediately on expiry and **does not
wait for OD-01**; **security event logs** (registration attempts) are purgeable on a short
schedule; **account lifecycle records** and **consent and acknowledgement evidence** have no
deletion schedule, because OD-01 is open and OD-36 aligns them with it. No period is asserted
here and no compliance claim is made (OD-35).

## `customer_identities`

The account. One row per registered email address. **Not a user**: no role, no permission, no
`customer_id`, and no code path to `permissions_for()`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | Internal. Never serialized |
| `public_id` | String(20), unique | no | `CA-000001`. The reference a customer quotes and the only identity id that reaches an audit row |
| `email_entered` | String(320) | no | As typed |
| `email_normalized` | String(320), **unique**, indexed | no | From `app.core.normalization`, which lowercases — so the plain unique constraint *is* the case-insensitive uniqueness strategy. The sign-in lookup key |
| `password_hash` | String(255) | no | Argon2, same hasher and rehash-on-sign-in policy as staff (DEC-0003) |
| `status` | String(30), indexed | no | `pending_verification` \| `pending_approval` \| `active` \| `rejected` \| `suspended` \| `deactivated`. **Phase 9 never writes `active`** |
| `email_verified_at` | DateTime | yes | Proof of mailbox control. **Not approval**, and a separate column so "verified" cannot be inferred from a lifecycle value |
| `approved_at`, `approved_by_user_id` | DateTime, FK `users.id` | yes | `ON DELETE SET NULL`. Written by Phase 10 |
| `rejected_at`, `rejected_by_user_id` | DateTime, FK | yes | `ON DELETE SET NULL` |
| `suspended_at`, `suspended_by_user_id` | DateTime, FK | yes | `ON DELETE SET NULL` |
| `deactivated_at`, `deactivated_by_user_id` | DateTime, FK | yes | `ON DELETE SET NULL` |
| `status_reason_code` | String(40) | yes | A reason **code**, never prose about the person. Bounded so a sentence does not fit |
| `failed_sign_in_count` | Integer, default 0 | no | Abuse control |
| `locked_until` | DateTime | yes | Bounded in time and never permanent: a permanent lockout hands an attacker a way to disable any customer they can name |
| `last_sign_in_at` | DateTime | yes | |
| `preferred_language` | String(8), default `en` | no | Release 1 serves English only (OD-39) |
| `created_at`, `updated_at` | DateTime | no | `TimestampMixin` |

**Indexes:** `email_normalized` (sign-in), `status` (the Phase 10 queue), `created_at`.
**Retention:** account lifecycle record; OD-01 dependent.
**Audit:** every transition writes an `audit_events` row carrying `public_id`, a reason code
and a hashed address key — never the hash, never a token, never the address.

## `customer_identity_links`

The identity-to-customer link. **Created by the Phase 9 migration and written by nothing in
Phase 9** — linking is a staff act (OD-24). Mapped anyway, so `alembic check` stays green
without widening the autogeneration exclusion.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | FK `customer_identities.id` | no | `ON DELETE CASCADE` |
| `customer_id` | FK `customers.id`, indexed | no | `ON DELETE RESTRICT` — a linked customer is not deleted out from under an account |
| `link_role` | String(20), default `owner` | no | Release 1 writes only `owner`. `member` and `admin` are where company access lands later (OD-26) |
| `status` | String(20) | no | `active` \| `revoked` |
| `linked_at`, `linked_by_user_id` | DateTime, FK `users.id` | | `ON DELETE SET NULL` |
| `revoked_at`, `revoked_by_user_id`, `revoke_reason_code` | DateTime, FK, String(40) | yes | |

**Two partial unique indexes**, both `WHERE status = 'active'`: one active link per identity,
and one active identity per customer. Partial because a plain unique index would also forbid
a second *revoked* link, which would make unlink-and-relink impossible and turn an ordinary
correction into a data-repair job. Relaxing to company access later drops the second index
and permits another `link_role` — no ownership check changes and no foreign key moves.

## `customer_sessions`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | FK, indexed | no | `ON DELETE CASCADE` |
| `session_token_hash` | String(64), **unique**, indexed | no | SHA-256. **The token itself is never stored** |
| `csrf_token_hash` | String(64) | no | Bound to this row, so a token from another session — or from the staff realm — satisfies nothing |
| `created_at`, `last_seen_at`, `expires_at` | DateTime | no | `expires_at` indexed |
| `revoked_at` | DateTime | yes | Server-side revocation. Also written when idle expiry is detected, and committed there |
| `ip_address` | String(64) | yes | The directly observed peer only (DEC-0007) |
| `user_agent` | String(255) | yes | Truncated |

**No role, no permission snapshot, no cached `customer_id`.** Idle expiry 60 minutes,
absolute 24 hours.
**Retention:** credential material; expired and revoked rows purgeable immediately,
independent of OD-01.

## `customer_auth_tokens`

Email verification and password reset. One table, one shape, one set of rules.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | FK, indexed | no | `ON DELETE CASCADE` |
| `purpose` | String(30) | no | `email_verification` \| `password_reset` |
| `token_digest` | String(64), **unique**, indexed | no | **Keyed** HMAC-SHA256 over `purpose:token` (DEC-0097). The only lookup path |
| `issued_at` | DateTime | no | |
| `expires_at` | DateTime, indexed | no | Hours, not days. Verification 24h, reset 2h |
| `consumed_at` | DateTime | yes | Single use, claimed by conditional update |
| `invalidated_at`, `invalidated_reason_code` | DateTime, String(40) | yes | Superseded by a newer token of the purpose, or by a completed reset |
| `issued_to_email_normalized` | String(320) | no | So a later address change cannot redirect an outstanding token |
| `request_ip` | String(64) | yes | Abuse analysis |

**Index:** `(identity_id, purpose)` for the supersession sweep.
**The plaintext exists in the outbound message and nowhere else** — not in a column, not in a
log, not in an audit payload.

## `customer_terms_acknowledgements`

Append-only (OD-37). No update path and no delete path; a later acknowledgement is a later row.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | FK, indexed | no | `ON DELETE CASCADE` |
| `document_kind` | String(30) | no | `terms` \| `privacy` |
| `document_version` | String(40) | no | The version presented. **A marked placeholder until OD-37 is satisfied**, and production registration refuses while it is |
| `presented_language` | String(8) | no | What the person actually read, which is not necessarily what they prefer |
| `acknowledged_at` | DateTime | no | |
| `request_ip` | String(64) | yes | |

**Index:** `(identity_id, document_kind)`. No uniqueness: two acknowledgements of one version
are two facts, not a duplicate.
**Retention:** consent and acknowledgement evidence; kept, OD-01 dependent.

## `customer_notification_preferences`

Operational preferences, identity-scoped. **Marketing consent is not here**: it is a
`consent_events` row written through the existing consent service at approval, and a
preference row can neither create one nor weaken one, nor lift a suppression (OD-27, OD-38).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | FK, indexed | no | `ON DELETE CASCADE` |
| `channel` | String(20) | no | `email` in release 1 |
| `topic` | String(40) | no | `shipment_milestones` \| `delivery_outcome`. `account_security` exists but is **not settable** |
| `enabled` | Boolean, default false | no | **Unchecked by default**: a row exists only because somebody chose (OD-38) |
| `updated_at` | DateTime | no | |

**Unique:** `(identity_id, channel, topic)`, so a repeated submission updates rather than
accumulates. A preference that could suppress a verification or reset message would be a
preference that locks people out of their own account, which is why `account_security` is not
in the settable set.

## `customer_data_proposals`

What the customer says about themselves, before a person agrees.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `identity_id` | FK, indexed | no | `ON DELETE CASCADE` |
| `customer_id` | FK `customers.id` | yes | **Null for a registration proposal — there is no customer yet, and that is the point.** `ON DELETE SET NULL` |
| `kind` | String(30) | no | `registration` \| `profile_update` |
| `status` | String(20) | no | `pending` \| `approved` \| `rejected` \| `superseded` \| `withdrawn`. Phase 9 writes `pending` and `superseded` |
| `submitted_at` | DateTime | no | |
| `reviewed_at`, `reviewed_by_user_id` | DateTime, FK `users.id` | yes | `ON DELETE SET NULL`. Phase 10 |
| `decision_reason_code` | String(40) | yes | Code, not prose |
| `duplicate_review_outcome` | String(30) | yes | Staff-facing. **Never serialized to a customer** (T-02) |
| `applied_audit_event_id` | FK `audit_events.id` | yes | `ON DELETE SET NULL`. Ties a canonical change to its audit row |
| `supersedes_proposal_id` | FK self | yes | Versioning by immutability: field rows are never rewritten, so a newer submission points back at the one it replaced |

**Index:** `(identity_id, status)` — the customer's own history and the Phase 10 queue read
exactly that pair.

## `customer_data_proposal_fields`

One allowlisted, typed field per row. A JSON blob would accept whatever the client sent,
which is the same as having no allowlist.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `proposal_id` | FK, indexed | no | `ON DELETE CASCADE` |
| `field_key` | String(60) | no | From the 43-key allowlist in `app/core/account_fields.py`. Longest key today is 31 characters |
| `value_type` | String(20) | no | `string` \| `enum` \| `email` \| `phone` \| `country` \| `boolean` — the type the boundary enforced, recorded so Phase 10 reads a typed value |
| `proposed_value` | Text | yes | What the person typed |
| `proposed_value_normalized` | Text | yes | What `app.core.normalization` made of it — what later duplicate review compares |
| `current_value_at_submission` | Text | yes | Null for a registration proposal: there is no canonical record to have drifted from |
| `applied` | Boolean, default false | no | Per field, because an approver may accept some and decline others (OD-28) |

**Unique:** `(proposal_id, field_key)`.
**Retention:** account lifecycle record — and the rows that actually hold personal data, which
is why the proposal tables are named in the categories legal review is asked to rule on.

**The allowlist, by group.** Scalars: `customer_type`, `business_type`, `legal_name`,
`display_name`, `primary_contact_name`, `email`, `phone`, `phone_country_code`,
`preferred_language`, `marketing_consent`. Billing address: six `billing_address.*` keys.
Pickup/sender addresses: nine keys each for up to three addresses (`pickup_address.1.*` …
`pickup_address.3.*`). Plural because OD-27 says addresses; bounded because unbounded plural
is a queue-flooding vector.

**`legal_name`, `display_name` and the billing keys have no canonical column** (DEC-0096).

## `customer_registration_attempts`

The idempotency and concurrency claim for public registration. Not proposed by
`docs/customer_account/DATA_MODEL.md`; reconciled in `PROJECT_STATUS.md` section 17.4 and
recorded as DEC-0098.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | Integer PK | no | |
| `idempotency_key_digest` | String(64), **unique** | no | Digest of the caller's key — a caller-supplied key is caller-supplied text, and storing arbitrary caller text is how personal data reaches a column nobody checks |
| `email_key` | String(64), indexed | no | Keyed digest of the normalized address. **Never the address** |
| `request_fingerprint` | String(64) | no | Digest of the canonicalized submitted fields. One key reused with different data is a conflict, not a silent replay. **The password is deliberately outside it** |
| `outcome` | String(30) | no | Internal category: `created`, `existing_address`, `throttled`, `replayed`, `suppressed`. **Never serialized** |
| `identity_id` | FK `customer_identities.id` | yes | `ON DELETE SET NULL` — the attempt records a request and outlives what it created |
| `created_at` | DateTime, indexed | no | |
| `request_ip` | String(64) | yes | |

There is deliberately **no** uniqueness on `email_key`: suppressing repeat work per address is
a rate-limit concern, and a constraint there would make a second attempt answer differently
from the first — the enumeration oracle OD-23 forbids.
**Retention:** security event log; purgeable on a short schedule. Holds no address, no body
and no token.

## What a Customer Account response may contain

The same discipline as the public surface, and the same enforcement. Every response model in
`app/schemas/account.py` inherits from nothing, sets `from_attributes=False` and
`extra="forbid"`, and is populated field by field.

`GET /me` returns exactly eight fields: `account_reference`, `status`, `email_verified`,
`linked`, `shipment_history_available`, `preferred_language`, `status_reason_code`,
`has_pending_proposal`. `linked` and `shipment_history_available` are hard `False` in Phase 9;
they are present rather than omitted so the shape does not move when Phases 10 and 11 make
them capable of being true.

Sign-in returns four: `account_reference`, `status`, `email_verified`, `csrf_token`.

**Never present, at any depth**: an internal row id, a password or anything about one, a token
or a digest, a session identifier, a CSRF digest, a duplicate score or match count, a
customer-link candidate, an audit internal, a staff name or role, integration state, a
financial value, or anything that says whether an address is registered. Asserted recursively
with planted sentinels in `backend/tests/test_account_privacy.py`, which also plants a leak
deliberately to prove the scan still detects one.


# Phase 10 — Customer Account approval and linking

## The historical-shipment disclosure rule (OD-29)

Before an account is linked to a canonical customer, staff are shown how much shipment
history the link would make visible, and must acknowledge it. This is the definition of
"visible", stated exactly and identically to the rule Phase 11 will serve rows under:

```sql
shipments.customer_id = <candidate customer id>
  AND shipments.booking_state != 'draft'
  AND shipments.is_demo_record = 0
```

**Three clauses, and the first one is the whole of ownership.** Not an email match on the
shipment, not a phone match, not recipient information, not address similarity, not
possession of a tracking reference, and never a customer id supplied by a browser (OD-29,
OD-30). A registration naming the same address as a shipment's sender snapshot discloses
nothing; only the canonical shipper relationship does.

| Figure | Derivation |
|---|---|
| `shipment_count` | `count(*)` over the rule |
| `oldest_booked_at` | `min(booking_date)` over the same set |
| `newest_booked_at` | `max(booking_date)` over the same set |
| `includes_cancelled` | true when any qualifying row has `booking_state = 'cancelled'` |
| `includes_rebooked` | true when any qualifying row has `rebooked_to_shipment_id` or `rebooked_from_shipment_id` |
| `definition_version` | `od29-shipper-link-v1` — the identifier of this rule |

**Cancelled and rebooked shipments are counted and labelled.** OD-29 keeps them visible with
safe states, and a count that dropped them would understate the disclosure — the one
direction this number must never be wrong in. **Drafts and demo records are excluded**,
because `SHIPMENT_ALLOWLISTS.md` section 5 says neither is ever visible. A shipment with no
`booking_date` is counted and bounds neither date: it is disclosed, and it has no date to
state.

**OD-22 stays open.** Nothing here creates, infers or follows a return-shipment link. A
return record is counted when, and only when, its own `customer_id` is the candidate.

The calculation returns a count, two dates and two booleans. **It never loads a shipment
row**, which is why no preview can leak one.

## `customer_account_disclosure_acknowledgements`

A staff member saw the five figures above and said so. The row stores the figures, not a
boolean, because the approval that reads it is a **later request** against a world that may
have moved: storing "yes" would record that somebody clicked, and storing the figures
records what they agreed to.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | int PK | yes | internal |
| `identity_id` | int FK `customer_identities.id` | yes | `ON DELETE CASCADE` |
| `proposal_id` | int FK `customer_data_proposals.id` | yes | `ON DELETE CASCADE` |
| `action` | str(20) | yes | `create_new` \| `link_existing`. An acknowledgement of one does not authorize the other |
| `customer_id` | int FK `customers.id` | no | the intended link target; null for `create_new` |
| `acknowledged_by_user_id` | int FK `users.id` | no | `ON DELETE SET NULL` |
| `acknowledged_at` | datetime | yes | |
| `disclosed_shipment_count` | int | yes | as shown |
| `oldest_booked_at` / `newest_booked_at` | datetime | no | as shown |
| `includes_cancelled` / `includes_rebooked` | bool | yes | as shown |
| `disclosure_definition_version` | str(40) | yes | which rule produced them |
| `preview_fingerprint` | str(64) | yes | keyed digest of every material fact; the approval recomputes and compares it |

Index on `(identity_id, preview_fingerprint)` — the only lookup an approval performs. No
uniqueness: acknowledging twice is two facts, and a reviewer who reloads after a customer
edit legitimately acknowledges a second, different set of figures.

**Holds no shipment reference**, and none is available to hold.

## `customer_account_approval_attempts`

The idempotency and concurrency claim for a staff decision — the shape
`booking_confirmations` and `customer_registration_attempts` already use (DEC-0031,
DEC-0098). SQLite has no useful `SELECT … FOR UPDATE`, so a unique index is how this
codebase serializes a claim.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | int PK | yes | internal |
| `idempotency_key_digest` | str(64) **unique** | yes | digest of the caller-supplied key. The claim: the insert is the serialization point |
| `identity_id` | int FK | yes | `ON DELETE CASCADE` |
| `action` | str(20) | yes | `create_new` \| `link_existing` \| `reject` |
| `customer_id` | int FK `customers.id` | no | set on the outcome |
| `request_fingerprint` | str(64) | yes | digest of the action, target and reason code. One key reused for different data is a **conflict**, not a replay |
| `outcome` | str(30) | yes | `approved_created` \| `approved_linked` \| `rejected` \| `replayed` \| `conflict` |
| `reason_code` | str(40) | no | the override or rejection code |
| `actor_user_id` | int FK `users.id` | no | `ON DELETE SET NULL` |
| `created_at` | datetime | yes | |

**Holds no raw key, no payload, no address and no token.** Retention: security event log,
purgeable on a short schedule.

## What a Customer Account review response may contain

The staff review schemas in `app/schemas/customer_account_review.py` obey the same four
rules as the customer-facing ones and for the same reason: inherit from nothing, set
`from_attributes=False` and `extra="forbid"`, and be populated field by field.

| Response | Fields |
|---|---|
| Queue row | `account_reference`, `status`, `submitted_at`, `email_verified_at`, `proposal_id`, `field_count` — **no contact detail of any kind** |
| Registration detail | the queue fields plus `account_email_entered`, `account_email_normalized`, `preferred_language`, `proposal_status`, the proposal's field rows, and `has_active_link`. **No duplicate result** |
| Duplicate candidate | `customer_public_id`, `full_name`, `display_name`, `city`, `country_code`, `matched_on`, `confidence`, `is_archived`, `is_merged`, `has_active_identity_link`, `linkable` — **not the candidate's email, phone, address, notes, owner, tags or lifecycle** |
| Disclosure | the six figures above, and nothing else |
| Preview | the proposed and current mapped snapshots, the differences, the classification, the candidate references, the target, the disclosure and the fingerprint |
| Decision | `account_reference`, `status`, `customer_public_id`, `outcome`, `replayed` |

**Never present, at any depth**: a password hash, a verification, reset or session token or
any digest of one, a CSRF value, a raw captured message, internal limiter state, a customer
that is not a duplicate candidate for this proposal, any shipment reference, package, event,
recipient or financial value, or any integration credential or state. Asserted recursively
with planted sentinels against a populated record in
`backend/tests/test_account_review_privacy.py`.

## Audit actions added in Phase 10

Every one carries a staff `actor`, which the Phase 9 events deliberately do not.

| Action | Written when |
|---|---|
| `customer_account.queue_reviewed` | the pending queue is listed. Counts, never the applicants |
| `customer_account.registration_opened` | one application is opened. Field **keys**, never the values |
| `customer_account.duplicates_reviewed` | the duplicate calculation runs. Classification and candidate references; **no score** |
| `customer_account.preview_created` | a preview is computed. The five figures and the fingerprint |
| `customer_account.disclosure_acknowledged` | a reviewer acknowledges. The evidence OD-29 asks for |
| `customer_account.approve` | actor, identity, customer, the five figures, the applied field keys and the reason code (AC-CA-10.4) |
| `customer_account.link` | the link row. Includes `differing_field_keys` — keys only, applied to nothing |
| `customer_account.separate_customer_override` | a new customer created despite a candidate, with its bounded reason code |
| `customer_account.reject` | reason code, sessions revoked, tokens invalidated |
| `customer_account.preview_stale_refused` | an approval refused because a material fact moved |
| `customer_account.approval_conflict` | two decisions raced and this one lost |
| `customer_account.approval_replayed` | an idempotency key arrived again; **nothing else was written** |

The disclosure figures are the one place a count about shipments appears in an audit
payload. That is deliberate: OD-29 and AC-CA-10.4 require the approval record to carry what
the approver was shown. No customer-facing route returns any of them.

---

# Phase 11 — Authenticated shipment history

**No table, column or index is added by this phase.** The schema is unchanged and
`alembic check` is green at the same head. What follows is the contract of the two read
routes: which stored column each published value comes from, and which columns are
deliberately not published.

## The list allowlist — `GET /api/v1/account/shipments`

`AccountShipmentListItem`, eighteen fields (`booking_reference` since UAT round 11, DEC-0160). Standalone: `from_attributes=False`,
`extra="forbid"`, every value assigned explicitly by
`customer_account_shipment_service._list_item`.

| # | Response field | Source column | Transformation | Null? |
|---:|---|---|---|:--:|
| 1 | `shipment_reference` | `shipments.public_id` | none | no |
| 1a | `booking_reference` | `shipments.booking_reference` | trimmed; empty becomes null. On the detail too since UAT round 12 (DEC-0160, DEC-0163) | yes |
| 2 | `booked_at` | `shipments.booking_date` | naive UTC as stored | yes |
| 3 | `route_group` | `shipments.route_group` | none | no |
| 4 | `route_label` | `shipments.route_group` | `ROUTE_GROUP_LABELS`, falling back to the code | no |
| 5 | `origin_city` | `shipments.origin_city` | trimmed; empty becomes null | yes |
| 6 | `origin_country_code` | `shipments.origin_country_code` | upper-cased; empty becomes null | yes |
| 7 | `destination_city` | `shipments.destination_city` | trimmed; empty becomes null | yes |
| 8 | `destination_country_code` | `shipments.destination_country_code` | upper-cased; empty becomes null | yes |
| 9 | `status` | `shipments.operational_state` | none | no |
| 10 | `status_label` | `shipments.operational_state` | `value_label` | no |
| 11 | `package_count_active` | `shipment_packages.is_active` | grouped count per shipment | no |
| 12 | `package_count_cancelled` | `shipment_packages.is_active` | grouped count of the inactive | no |
| 13 | `delivered_at` | `shipments.delivered_at` | suppressed when the booking is cancelled | yes |
| 14 | `cancelled_at` | `shipments.cancelled_at` | present only when cancelled | yes |
| 15 | `last_public_update_at` | `shipment_events.occurred_at` | `MAX`, over published, non-voided events with approved wording | yes |
| 16 | `is_cancelled` | `shipments.booking_state` | equals `cancelled` | no |
| 17 | `is_rebooked` | `shipments.rebooked_to_shipment_id` | is not null | no |

`origin_*` and `destination_*` are the denormalized route summary `booking_service`
maintains alongside the sender and recipient snapshots, so the list's city and the detail's
city describe one place.

The envelope, `AccountShipmentListPage`, carries `items`, `total`, `limit`, `offset` and
`timezone`. It is **not** `app.schemas.common.Page`, which sets `from_attributes=True`.
`timezone` is the organization's display timezone and travels once per page rather than on
every row.

### Excluded from the list, and why

| Excluded | Why |
|---|---|
| `recipient_name`, `_company`, `_phone_*`, `_email`, `_address_*`, `_postal_code`, `_delivery_note` | A third party's personal data. The shipper knows who they sent to; a leaked session should not hand over an address book |
| `sender_name`, `_company`, `_address_*`, `_postal_code`, `_email`, `_phone_*` | The customer's own record, which belongs on a profile surface |
| `currency`, `selling_amount`, `shipping_cost`, `surcharges_amount`, `discount_amount`, `refund_amount`, `payment_state` | OD-32 |
| `declared_value`, `declared_value_currency`, `contents_description` | Not needed to choose a row; customs-sensitive free text |
| `internal_notes`, `owner_user_id` | Internal (OD-27) |
| `shipments.id`, `customer_id` | Internal row ids |
| `idempotency_key`, `source_system`, `source_record_id` | Booking and import mechanics (`booking_reference` was here until DEC-0160; it is field 1a) |
| `is_demo_record`, `booking_state` | Internal; the safe derivations are fields 16 and 17 |
| `rebooked_to_shipment_id`'s **reference** | A second disclosure decision, not made (`SHIPMENT_ALLOWLISTS.md` §5) |

## The detail allowlist — `GET /api/v1/account/shipments/{reference}`

`AccountShipmentDetail`, twenty-five top-level fields — the field names and semantics the
Phase 8 specification approved, **re-declared** rather than inherited (OD-31), plus the
customer's own `booking_reference` since UAT round 12 (DEC-0163), which Public Tracking
does not carry. Four nested
shapes are re-declared with it: `AccountPlace`, `AccountPackage`, `AccountTimelineEntry`,
`AccountCarrierLink`. `AccountTrackingState` and `AccountDataMode` are re-declared enums.

| # | Field | Source / derivation |
|---:|---|---|
| 1 | `shipment_reference` | `shipments.public_id` |
| 1a | `booking_reference` | `shipments.booking_reference`, trimmed; empty becomes null. The same value as the list row (DEC-0163) |
| 2 | `matched_reference_type` | constant `"shipment"` — no package addressing on this route |
| 3 | `selected_package_reference` | constant `null`, for the same reason |
| 4 | `route_group` | `shipments.route_group` |
| 5 | `route_label` | `ROUTE_GROUP_LABELS` |
| 6 | `origin` | `shipments.sender_city`, `sender_country_code` |
| 7 | `destination` | `shipments.recipient_city`, `recipient_country_code` |
| 8 | `status` | `shipments.operational_state` |
| 9 | `status_label` | `value_label` |
| 10 | `package_count_active` | derived package progress |
| 11 | `package_count_cancelled` | derived package progress |
| 12 | `package_count_delivered` | derived package progress |
| 13 | `progress_summary` | derived package progress |
| 14 | `packages` | `shipment_packages`: reference, state, label, selected, cancelled, delivered-at |
| 15 | `estimated_delivery_at` | `shipments.estimated_delivery_at`, dropped once delivered, returned or cancelled |
| 16 | `delivered_at` | `shipments.delivered_at`, null when cancelled |
| 17 | `cancelled_at` | `shipments.cancelled_at`, only when cancelled |
| 18 | `timeline` | published, non-voided `shipment_events` with approved wording |
| 19 | `tracking_state` | derived; cancellation first, then milestones, then a link, then honesty |
| 20 | `last_public_update_at` | the newest timeline entry's `occurred_at` |
| 21 | `carrier_link` | an allowlisted, HTTPS, non-private public carrier URL — **never** the tracking number |
| 22 | `data_mode` | constant `live`; demo rows never qualify |
| 23 | `help_url` | configured public help URL |
| 24 | `timezone` | organization display timezone |

A timeline entry carries the approved public wording only. `shipment_events.internal_detail`
is not read on this path and there is no field on `AccountTimelineEntry` that could carry
it; neither is the recording staff member, the internal event id, the leg, or any carrier
payload.

## What a Customer Account shipment response may never contain

Beyond the exclusion tables above: staff notes; internal event detail; audit data; staff
identities; internal customer ids, including `customers.public_id`; recipient or sender
information beyond the coarse city and country; cost, revenue, profit, invoices or payment
data; integration credentials; worker or job state; token or session data; internal
duplicate information; raw carrier payloads; unapproved tracking references; provider
freshness fields; provider synchronization status.

`backend/tests/test_account_shipment_privacy.py` asserts this two ways: a recursive scan
for forbidden **keys** at any depth, and a scan for planted private **values** — a sentinel
written into a real column in every excluded category that has one, searched for in the
whole serialized body. Categories with no column today (integration credential, worker
state, provider freshness) are asserted by the absence of the concept.

## Audit action added in Phase 11

| Action | Written when |
|---|---|
| `customer_account.shipment_access_denied` | a read was refused. Carries the identity `public_id`, the surface (`list` or `detail`), a bounded reason code (`not_authorized` or `shipment_not_found`), and — on a detail refusal — a **keyed digest** of the submitted reference |

A **successful** read writes no audit row. The approved granularity watches not-found rates
per identity, not read rates, and a row per successful read would build a second copy of a
customer's history in audit summaries. Successes are recorded as one structured log line
carrying a digest of the account reference, the surface, an outcome category, the page size
and the number of rows returned — and nothing else.

The refusal payload records the *category*, not the internal reason. An archived linked
customer and a revoked link are both `not_authorized`, because which one applies is a fact
about the CRM's state and both are `FIELD_MATRIX.md` §3.4 never-fields. The distinction
travels in the operator-facing log as a bounded code from
`customer_account_link_policy.REFUSAL_REASONS`.

---

# Phase 13A — vendor tariffs and exchange rates

Twelve tables added by migration `f53efaa7773e`. All of them hold **vendor cost data and
are internal**: readable through the staff router behind `tariff:read`, never through the
public or Customer Account routers. No table here has a column for a person's name or
telephone; the vendor's staff directory sheet is never read.

## `vendors`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | int PK | yes | |
| `key` | str(40) unique | yes | `kango`. A key, never shown to customers |
| `name` | str(120) | yes | |
| `is_active` | bool | yes | |
| `notes` | text | no | |

## `tariff_versions`

One imported workbook. Immutable once written; a new file is a new version.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | int PK | yes | |
| `public_id` | str(20) unique | yes | `TRF-000001`, from the `counters` table |
| `vendor_id` | int FK `vendors.id` | yes | |
| `label` | str(120) | yes | |
| `source_file_name` | str(255) | no | operator metadata, not content |
| `source_sha256` | str(64) | yes | unique per vendor: the same bytes cannot be imported twice |
| `effective_from` / `effective_to` | date | yes / no | `effective_to` is set when superseded |
| `status` | str(20) | yes | `draft` \| `active` \| `superseded` |
| `imported_at`, `imported_by_user_id` | datetime, FK `users.id` | yes, no | |
| `activated_at`, `activated_by_user_id` | datetime, FK `users.id` | no | |
| `dim_divisor_default` | int | yes | 6000 |
| `fixed_fx_vnd_per_cad` | numeric(12,2) | no | the vendor's own fixed CAD rate for its CAD fees (19,500); not a bank rate |
| `cost_currency` | str(3) | yes | `VND` |
| `import_report_json` | text | yes | counts, anomalies, rules in prose; read by staff, never by pricing |

## `tariff_products`

One sellable vendor product per origin (`AIR-CAD`, `AIR-CAD EXPRESS`, `KSN-SEA-CAD-PURO`,
`KSN-SEA-CAD-PURO-BH`, `KSN-SEA-CAD-TRUCKING`, each for HCM and HAN).

| Field | Type | Required | Notes |
|---|---|---|---|
| `version_id` | int FK `tariff_versions.id` | yes | unique with `origin`, `code` |
| `code`, `origin`, `mode`, `last_mile` | str | yes | origin `HCM`/`HAN`; mode `air`/`sea`; last mile `purolator_ground`/`purolator_express`/`trucking` |
| `dim_divisor` | int | yes | 6000; 5000 for trucking |
| `per_kg_from_kg` | numeric(7,2) | no | air: 21 |
| `piece_min_weight_kg`, `piece_min_fee_vnd`, `piece_min_applies_above_kg` | numeric | no | air: pieces under 12 kg on lots over 21 kg pay 300,000 (Ground) / 700,000 (Express); sea Purolator: 15 kg / 300,000; trucking: 12 kg / 500,000 |
| `min_chargeable_kg` | numeric(7,2) | no | trucking: 100 |
| `customs_surcharges_waived` | bool | yes | true for the insured sea product |
| `transit_text`, `source_sheet` | str | no, yes | |

## `tariff_rate_brackets`

| Field | Type | Required | Notes |
|---|---|---|---|
| `product_id` | int FK `tariff_products.id` | yes | indexed with `kind`, `zone` |
| `kind` | str(10) | yes | `per_bill` (0.5–20.5 kg bands, VND per shipment) \| `per_kg` (tiers, VND per kg) |
| `zone` | int | yes | 1–3; 0 for trucking (not zoned) |
| `label` | str(20) | yes | the vendor's row label verbatim |
| `weight_from_kg`, `weight_to_kg` | numeric(7,2) | no | band bounds as written; open top tier has NULL `weight_to_kg` |
| `price_vnd` | numeric(14,2) | yes | as written, unrounded |
| `source_sheet`, `source_cell` | str | yes | provenance |

## `tariff_zone_fsas`, `tariff_beyond_postal_codes`, `tariff_beyond_rates`

| Table | Key | Notes |
|---|---|---|
| `tariff_zone_fsas` | unique (`version_id`, `fsa`) | `province`, `ground_zone`, `express_zone` (1–3) |
| `tariff_beyond_postal_codes` | unique (`version_id`, `postal_code`) | six characters, no space; `city`, `province`, `beyond_code` |
| `tariff_beyond_rates` | unique (`version_id`, `beyond_code`) | `status` `priced` \| `no_rate`; `base_cad`, `per_lb_cad` NULL when `no_rate` (code 180). Fee = base + ceil(lb) × per-lb, CAD per piece |

## `tariff_accessorials`

Fees the vendor writes in prose, read through the reviewed table in
`app/pricing/kango_semantics.py`, each with the cell it was taken from.

| Field | Type | Notes |
|---|---|---|
| `key` | str(60) | unique per version |
| `description` | str(300) | |
| `amount`, `currency` | numeric(14,2), str(3) | `CAD` or `VND` |
| `basis` | str(30) | `per_shipment` \| `per_piece` \| `per_piece_per_week` \| `per_bill` |
| `applies_to_modes` | str(20) | comma-separated `air`, `sea` |
| `source_sheet`, `source_cell` | str | |

## `tariff_surcharge_rules` and `tariff_surcharge_rule_tiers`

The vendor's text and the structured reading, side by side.

| Field | Type | Required | Notes |
|---|---|---|---|
| `version_id`, `section`, `stt` | FK, str(20), int | yes | unique together; section `hcm_air` \| `han_air` \| `sea_ca_au_uk_eu` \| `sea_usa` |
| `section_label`, `name`, `raw_price_text`, `raw_note` | str / text | yes, yes, yes, no | verbatim |
| `basis` | str(20) | yes | `per_kg` \| `per_piece` \| `per_unit` \| `per_pair` \| `per_box` \| `per_bottle` \| `per_shipment` \| `compound` \| `free` \| `unpriced` |
| `scope` | str(20) | yes | `full_carton` (the default for per-kg rules, per the sheet's footer) \| `full_master` \| `item_weight` \| `per_unit` \| `per_shipment` |
| `pricing_status` | str(30) | yes | `priced` \| `tiered` \| `free` \| `unpriced_vendor_review` \| `not_applicable_canada` \| `conflict`. Only the first two may be priced by the engine |
| `unit_price_vnd` | numeric(14,2) | no | NULL unless `priced` |
| `per_unit_price_vnd`, `per_unit_label` | numeric, str(20) | no | the per-unit half of a `compound` rule (perfume: 50,000 per bottle) |
| `min_charge_kg`, `max_kg_per_shipment` | numeric(7,2) | no | "Min thu 1Kg"; "max 1 kg per bill" |
| `applies_to_canada` | bool | yes | false for the USA sea section and the EU/UK-only rows |
| `semantics_source` | str(10) | yes | `parsed` \| `curated` |
| `semantics_note` | str(500) | no | our one-line reading; staff-only |
| `source_sheet`, `source_row` | str, int | yes | |

`tariff_surcharge_rule_tiers`: `rule_id` FK, `weight_from_kg`, `weight_to_kg` (NULL = open),
`price_vnd`. Bounds are stored as the vendor wrote them, overlaps included (V-11).

## `fx_rate_snapshots` and `fx_sync_attempts`

| Table | Fields | Notes |
|---|---|---|
| `fx_rate_snapshots` | `bank`, `currency`, `cash_buy_vnd`, `transfer_buy_vnd` (nullable), `sell_vnd`, `bank_published_raw`, `bank_published_at`, `retrieved_at`, `content_sha256`, `source_url` | append-only; one row per verified reading; cost converts at `cash_buy_vnd`, customer surcharges at `sell_vnd` |
| `fx_sync_attempts` | `bank`, `currency`, `attempted_at`, `outcome` (`ok` \| `failed`), `error_summary` (bounded category, never a body), `snapshot_id` FK (nullable), `worker_name` | one row per attempt, failed or not |

## Customer identifiers after OD-42

`customers.public_id` is `STCA-000001` from 2026-10-19 (migration `a7c3e1d9b2f4`, DEC-0174).
Identifiers issued as `CUS-` before that were renamed in place and each former value is a
`customer_id_aliases` row with `reason = prefix_change_2026_10_19`, resolvable through the same
lookup as a merge alias. The counter and its six digits did not change.

## Audit actions added in Phase 13A

`tariff_version.imported`, `tariff_version.activated`.

## What a public or Customer Account response may never contain

Any field from the tables above. `backend/tests/test_tariff_import.py` walks the public and
account schema modules for the vocabulary (`tariff`, `vendor`, `price_vnd`, `cash_buy`,
`sell_vnd`, `beyond`, `surcharge_rule`, `accessorial`, `fx_`, `kango`) and asserts no tariff
or exchange-rate route is mounted outside `/api/v1/tariffs` and `/api/v1/fx`.


---

# Phase 13B — consolidations, memberships, commodity items, service mapping, payer

Six new tables by migration `b8d4f2a6c1e7`. No existing table changed. All staff data; the
vendor reference and master weights never reach the public or Customer Account routers
(`backend/tests/test_consolidations.py` plants a vendor reference and scans the public page).

## `consolidations`

The handoff's master: one vendor booking carrying several customers' shipments.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | int PK | yes | |
| `public_id` | str(20) unique | yes | `MST-000001`, from `counters`; the Solaris reference, never the vendor's |
| `vendor_id` | int FK `vendors.id` | yes | `RESTRICT` |
| `solaris_service` | str(20) | yes | `air_standard` \| `air_express` \| `ups` \| `sea` (only the first two are mapped, OD-43) |
| `origin` | str(3) | yes | `HCM` \| `HAN` |
| `tariff_version_id`, `tariff_product_id` | FK | no | set at booking from the active tariff's mapping; `SET NULL` |
| `vendor_reference` | str(60) | no | the vendor's booking number or AWB; indexed; staff-only |
| `state` | str(20) | yes | `open` \| `booked` \| `completed` \| `cancelled` |
| `actual_weight_kg` | numeric(8,3) | no | |
| `length_cm`, `width_cm`, `height_cm` | numeric(7,1) | no | |
| `carton_count` | int | yes | default 1 |
| `dim_divisor` | int | no | copied from the product at booking |
| `volumetric_weight_kg`, `chargeable_weight_kg` | numeric(8,3) | no | stored at booking; never recomputed |
| `handed_over_at` | datetime | no | hand-over at the Vietnam depot: the revenue period (owner decision 12); defaults to the booking time |
| `cutoff_at`, `booked_at`, `completed_at`, `cancelled_at` | datetime | no | |
| `booked_by_user_id`, `created_by_user_id` | FK `users.id` | no | `SET NULL` |
| `cancellation_reason` | str(255) | no | |
| `internal_notes` | text | no | |

## `consolidation_memberships`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | int PK | yes | |
| `consolidation_id` | FK `consolidations.id` | yes | `CASCADE` |
| `shipment_id` | FK `shipments.id` | yes | `CASCADE` |
| `added_at`, `added_by_user_id` | datetime, FK | yes, no | |
| `removed_at`, `removed_by_user_id`, `removal_reason` | datetime, FK, str(255) | no | a removed membership keeps its row |

Partial unique index `uq_consolidation_memberships_active_shipment` on `shipment_id` where
`removed_at IS NULL`: one active consolidation per shipment, history kept.

## `consolidation_event_links`

| Field | Type | Notes |
|---|---|---|
| `event_id` | PK, FK `shipment_events.id` | `CASCADE`; the inherited event |
| `consolidation_id` | FK `consolidations.id` | `CASCADE` |
| `shipment_id` | FK `shipments.id` | `CASCADE`; indexed with `consolidation_id` |

A row means the event was recorded on the master and fanned out to this shipment
(`event_id` is the primary key). A repeat is refused: the same type and stated time, or the
same type when no time is stated.

## `shipment_payers`

| Field | Type | Notes |
|---|---|---|
| `shipment_id` | PK, FK `shipments.id` | `CASCADE` |
| `payer_customer_id` | FK `customers.id` | `CASCADE`; indexed |
| `set_at`, `set_by_user_id` | datetime, FK `users.id` | |

`shipment_id` is the primary key. No row means the booking customer pays. Naming the booking
customer as payer stores nothing, and a customer merge re-points or drops the row.

## `shipment_items`

| Field | Type | Required | Notes |
|---|---|---|---|
| `shipment_id` | FK `shipments.id` | yes | `CASCADE` |
| `sequence` | int | yes | unique per shipment; never reused |
| `description` | str(300) | yes | |
| `quantity` | numeric(10,2) | yes | default 1 |
| `unit` | str(20) | yes | `piece` \| `pair` \| `box` \| `bottle` \| `set` \| `kg` \| `carton` \| `other` |
| `weight_kg` | numeric(8,3) | no | |
| `declared_value`, `declared_value_currency` | numeric(12,2), str(3) | no | |
| `package_id` | FK `shipment_packages.id` | no | `SET NULL` |
| `is_active` | bool | yes | removal deactivates |
| `notes` | str(400) | no | |

## `service_vendor_products`

| Field | Type | Notes |
|---|---|---|
| `tariff_version_id` | FK `tariff_versions.id` | `CASCADE`; unique with `solaris_service`, `origin` |
| `solaris_service` | str(20) | |
| `origin` | str(3) | |
| `tariff_product_id` | FK `tariff_products.id` | `CASCADE` |
| `created_at` | datetime | |

Written by the tariff importer for every version: Air Standard → `AIR-CAD`, Air Express →
`AIR-CAD EXPRESS`, per origin. Sea and UPS have no rows.

## Staff shipment detail additions

`GET /api/v1/shipments/{id}` gains `payer` (a customer summary or null), `consolidation`
(id, Solaris reference, state, service, origin, and the vendor reference for `tariff:read`
holders only, or null) and `items`. The consolidation routes themselves need `tariff:read`.
The public tracking and Customer Account shipment schemas are unchanged.

## Audit actions added in Phase 13B

`consolidation.create`, `consolidation.update`, `consolidation.member_add`,
`consolidation.member_remove`, `consolidation.book`, `consolidation.complete`,
`consolidation.cancel`, `consolidation.event_record`, `shipment.item_add`,
`shipment.item_update`, `shipment.item_remove`.


---

# Phase 13C — pricing settings, surcharge policies, fee lines, quotes

Six new tables by migration `c9e5a3b7d2f8`; nothing existing altered. Internal: vendor cost and
margin sit beside the customer price; staff routes only.

## `pricing_settings`

One row, created on first use. `air_standard_default_rate_cad` numeric(8,2) default 18.00;
`air_express_default_rate_cad` numeric(8,2) nullable; `trigger_share_numerator` /
`trigger_share_denominator` int (2/3); `defaults_owner_confirmed` bool (false, OD-48);
`vendor_delivery_postal_code` str(6) (`L5A3K6`, OD-46); `updated_at`, `updated_by_user_id`
(FK `users`, SET NULL).

## `surcharge_rule_policies`

Unique (`section`, `stt`). `markup_kind` str(20) `pass_through` | `fixed_cad` | `percent`;
`markup_value` numeric(10,2); `scope_override` str(20) nullable (a `SurchargeScope`, for example
`item_weight`); `note` str(400); `updated_at`, `updated_by_user_id`.

## `shipment_fee_lines`

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `shipment_id` | FK `shipments.id` | CASCADE |
| `item_id` | FK `shipment_items.id` | CASCADE |
| `section`, `stt` | str(20), int | the vendor's rule; survives tariff versions |
| `quantity` | numeric(10,2) | units, pairs, boxes, bottles or cartons, by the rule's basis |
| `weight_kg` | numeric(8,3) | carton weight for a tiered rule; kilograms for an item-weight rule |
| `manual_unit_price_vnd` | numeric(14,2) | the vendor's quoted unit price for a manual-quote rule or a battery carton above 8 kg (OD-56, OD-59); null = the file's minimum, flagged |
| `created_at`, `created_by_user_id` | | |
| `removed_at`, `removed_by_user_id` | | removal keeps the row |

Partial unique index `uq_shipment_fee_lines_active_item_rule` on (`item_id`, `section`, `stt`)
where `removed_at IS NULL`.

## `consolidation_cartons`

`consolidation_id` FK `consolidations` CASCADE, unique with `sequence`; `weight_kg`
numeric(8,3); `length_cm`, `width_cm`, `height_cm` numeric(8,2) nullable; `created_at`,
`created_by_user_id`. Replaced as a set; drives the under-12 kg piece fee on masters of 21 kg and
over (OD-62, DEC-0194).

## `quote_versions`

| Field | Type | Notes |
|---|---|---|
| `shipment_id` | FK `shipments.id` | **RESTRICT**; unique with `version` |
| `version` | int | 1, 2, … |
| `status` | str(12) | `draft` \| `finalized` \| `superseded`; one draft per shipment (partial unique index) |
| `consolidation_id`, `tariff_version_id`, `fx_snapshot_id` | FK | SET NULL; what it was priced against |
| `solaris_service` | str(20) | |
| `default_rate_cad`, `selling_rate_cad` | numeric(8,2) | |
| `override_reason` | str(400) | required for any rate other than the default |
| `rate_confirmed_at`, `rate_confirmed_by_user_id` | | |
| `inputs_sha256`, `confirmed_inputs_sha256` | str(64) | a changed input revokes the confirmation |
| `negative_margin_reason` | str(400) | required when a surcharge bills below cost |
| `billable_weight_kg` | numeric(8,3) | |
| `base_revenue_cad`, `surcharge_revenue_cad`, `total_revenue_cad`, `allocated_cost_cad`, `gross_profit_cad` | numeric(12,2) | |
| `blocking_json`, `provisional_json`, `snapshot_json` | text | the snapshot is frozen at finalisation |
| `created_by_user_id`, `finalized_at`, `finalized_by_user_id`, `superseded_at` | | |

## `quote_lines`

`version_id` FK CASCADE, unique with `sequence`; `kind` `base_freight` | `surcharge`;
`description` (Solaris service name or the commodity, never a vendor name); `section`, `stt`;
`quantity`, `unit`; `revenue_cad`; internal `cost_vnd`, `cost_cad`; `is_trigger` (false = an
internal cost share only, never printed on a customer document); `markup_kind`, `markup_value`.

## Audit actions added in Phase 13C

`pricing.settings_update`, `pricing.policy_update`, `shipment.fee_line_add`,
`shipment.fee_line_remove`, `consolidation.cartons_replace`, `quote.draft_open`,
`quote.confirmation_revoked`, `quote.rate_confirm`,
`quote.finalize`.

## Enum value added

`SurchargePricingStatus.manual_quote` (OD-56).

## Privacy

The public and Customer Account forbidden-key lists gain `quote`, `quotes`, `selling_rate_cad`,
`total_revenue_cad`, `gross_profit_cad` and `allocated_cost_cad`; `tests/test_quotes.py` scans
the public tracking page after a quote is finalised.

# Phase 13E — finance

Eight new tables by migration `d1f6b4c8e2a9`; nothing existing altered. Internal except the two
customer documents, which are served through allowlist schemas.

## `finance_settings`

One row, created only when an administrator saves (reads return defaults, DEC-0204).
`invoice_due_days` int (0 = due on issue, OD-65); `tax_status` str(30) (`review_pending` while
D-11 / OD-64 is open); `updated_at`, `updated_by_user_id`.

## `customer_invoices` / `customer_invoice_lines`

| Field | Type | Notes |
|---|---|---|
| `public_id` | str(20) unique | `INV-000001`, allocated at issue, never reused |
| `shipment_id` | FK `shipments` | RESTRICT; one live (non-void) invoice per shipment (partial unique index) |
| `customer_id` | FK `customers` | RESTRICT; the payer, else the booking customer |
| `quote_version_id` | FK `quote_versions` | RESTRICT; the finalised version it was issued from |
| `consolidation_id` | FK `consolidations` | SET NULL |
| `status` | str(16) | `issued` \| `partially_paid` \| `paid` \| `void` |
| `subtotal_cad`, `total_cad`, `paid_cad` | numeric(12,2) | `paid_cad` = payments − refunds |
| `tax_cad` | numeric(12,2) null | empty while D-11 is open |
| `tax_status` | str(30) | copied from the settings at issue |
| `period_month` | str(7) | revenue month `YYYY-MM` (hand-in month, or the first open month) |
| `is_adjustment` | bool | booked after its own month locked |
| `document_json` | text | customer name and reference, shipment reference, service, frozen at issue |
| `issued_at`, `due_at`, `voided_at`, `void_reason` | | |

Lines: `sequence`, `description`, `quantity`, `unit`, `amount_cad` (CASCADE with the invoice).

## `customer_payments`

`kind` `payment` \| `refund`; `receipt_public_id` (`RCT-000001`, payments only, unique);
`refund_of_payment_id` (RESTRICT); `amount_cad`; `currency` (CAD only, OD-66); `method`
(`cash`, `bank_transfer`, `e_transfer`, `card`, `other`); `reference`; `note` (a refund's
reason); `received_at` (when money moved); `recorded_at`, `recorded_by_user_id`. RESTRICT to
the invoice.

## `vendor_invoices` / `vendor_invoice_lines` / `cost_allocations`

Vendor bill: `public_id` (`VB-000001`); `consolidation_id` RESTRICT, one live bill per master;
`vendor_bill_number`; `billed_at`; `currency` VND \| CAD; `status` `entered` \| `approved` \|
`paid` \| `void`; `total_amount`; `fx_snapshot_id`, `fx_cash_buy_vnd` (frozen at entry, OD-67);
`total_cad`; `expected_vnd`, `expected_cad`, `expected_json` (the estimate at entry);
`variance_cad`, `variance_reason`; `period_month`, `is_adjustment`; entry, approval, payment and
void stamps. Lines: `kind` `base` \| `piece_fee` \| `surcharge` \| `other`, `fee_key` (the
estimate fee a surcharge line follows), `description`, `amount`. Allocations: one row per line
and shipment, `amount_cad`, written at approval, deleted by a void; shipment RESTRICT.

## `period_closes`

`month`, `version` (unique together); `closed_at`, `closed_by_user_id`, `snapshot_json` (the
profitability report at close); `reopened_at`, `reopened_by_user_id`, `reopen_reason`.

## Permission added

`financial:adjust` (refunds, voids, reopening a closed month): in no role set, so Admin only
(OD-69).

## Audit actions added

`invoice.issue`, `invoice.payment`, `invoice.refund`, `invoice.void`, `vendor_invoice.enter`,
`vendor_invoice.approve`, `vendor_invoice.paid`, `vendor_invoice.void`, `period.close`,
`period.reopen`, `finance.settings_update`, `export.ar_aging`, `export.profitability`.

# Owner answers (2026-10-20) and Phase 13F

## `payment_conversions` (migration `e4a7c2d9f1b3`)

One row per VND customer payment (OD-66): `payment_id` (unique, CASCADE), `amount_vnd`,
`vnd_per_cad` (Vietcombank selling rate on the invoice date: a CAD invoice paid in VND is a CAD-to-VND conversion, OD-73), `fx_snapshot_id` (SET NULL),
`rate_day`. The payment's `amount_cad` is the converted figure.

`vendor_invoices.fx_cash_buy_vnd` holds the Vietcombank **buy** rate (first column) on the bill
date (OD-73, superseding OD-67's middle rate); the API calls it `fx_rate_vnd`. `customer_invoices.tax_status` is
`gst_hst_0`, `gst_hst_5` or `gst_hst_13` for an invoice issued after OD-64 (`review_pending`
before), and `tax_cad` the tax at that rate.

## `notification_preferences` (migration `f2b8d5a1c7e4`)

`customer_id` (CASCADE), `milestone` (`received` | `in_transit` | `out_for_delivery` |
`delivered`), unique together; `enabled`; `updated_via` (`account` | `staff`); `updated_at`.
No row = on (OD-72).

## `notification_outbox`

| Field | Type | Notes |
|---|---|---|
| `dedup_key` | str(80) unique | `{shipment_id}:{milestone}:{template_version}` |
| `shipment_id` | FK `shipments` | CASCADE |
| `customer_id` | FK `customers` | SET NULL |
| `event_id` | FK `shipment_events` | SET NULL; the event that reached the milestone |
| `milestone`, `channel` (`email`), `language` (`vi` \| `en`) | | |
| `template_key`, `template_version` | | `notify.<milestone>.<language>`, `v1` |
| `status` | str(10) | `queued` \| `sending` (claimed) \| `sent` (capture) \| `recorded` (null transport) \| `skipped` \| `failed` |
| `skip_reason` | str(20) | `opted_out` \| `suppressed` \| `no_email` \| `voided` \| `closed` (Phase 15: the shipment was returned or cancelled before the row went out) |
| `transport`, `attempts`, `last_error` (bounded), `created_at`, `processed_at` | | |

No address and no message body are stored.

## Audit actions added

`notification.preferences_update`, `notification.retry`.

## `markup_defaults` (migration `a3c9e7f1b5d2`)

One row (none until an administrator first saves it; the service answers with the default
meanwhile): `markup_kind` (`pass_through` | `fixed_cad` | `percent`, default `percent`),
`markup_value` (numeric 10,2, default `2`), `updated_at`, `updated_by_user_id` (SET NULL). The
markup on every surcharge whose rule has no `surcharge_rule_policies` row (OD-74). Customer
surcharges convert VND to CAD at the **buy** rate (OD-73). Exposed on
`GET/PATCH /api/v1/pricing/settings` as `default_markup_kind` / `default_markup_value` (Admin).
Audit action `pricing.markup_default_update`.

# Phase 13G — customer quote acceptance

## `quote_offers` (migration `b7d2e9a4c1f6`)

A finalised quote version sent to the customer, and their answer (OD-77, DEC-0213).

| Field | Type | Notes |
|---|---|---|
| `quote_version_id` | FK `quote_versions`, unique | RESTRICT; one offer per version, ever |
| `shipment_id` | FK `shipments` | RESTRICT; partial unique index `uq_quote_offers_open_shipment`: one `sent` offer per shipment |
| `customer_id` | FK `customers` | SET NULL; the shipment's customer when sent |
| `status` | str(12) | `sent` \| `accepted` \| `declined` \| `withdrawn` |
| `customer_view_json` | text | The frozen customer-safe content: `shipment_reference`, `version`, `service` (label), `billable_weight_kg`, `rate_per_kg_cad`, `base_charge_cad`, `surcharges` [`name`, `amount_cad`], `total_cad`, `currency` (`CAD`), `tax_included` (false). Nothing cost-derived |
| `sent_at`, `sent_by_user_id` | | `sent_by_user_id` SET NULL |
| `responded_at`, `responded_identity_id` | | FK `customer_identities` SET NULL; the account that answered |
| `decline_reason` | str(400) | The customer's, optional |
| `withdrawn_reason`, `withdrawn_at` | str(400) | Staff's reason, or `superseded by vN`; never shown to the customer |
| `withdrawn_code` | str(20) | `staff` \| `superseded` \| `customer_merged` \| `customer_changed`; the account words it as `withdrawn` or `replaced` |
| `superseded_by_version`, `superseded_at` | int, datetime | Set when a newer version is finalised after the customer accepted (staff warning) |
| `email_status` | str(20) | Outcome of the quote-sent email: `sent` (capture) \| `recorded` (null transport) \| `no_email` \| `failed` \| `resending` (Phase 15: claimed by a staff resend, replaced by the outcome; taken over after 10 minutes) \| `skipped` (answered or withdrawn before the send: nothing sent); null until decided (a suppression does not stop it, DEC-0143). No address, no body |
| `created_at`, `updated_at` | | |

Staff: `GET /api/v1/shipments/{id}/quote-offers`, `POST /api/v1/shipments/{id}/quotes/send`,
`POST /api/v1/quote-offers/{id}/withdraw {reason}`. Customer Account:
`GET /api/v1/account/quotes`, `GET /api/v1/account/quotes/{id}`,
`POST /api/v1/account/quotes/{id}/accept`, `POST /api/v1/account/quotes/{id}/decline {reason?}`
(the frozen view, status, `responded_at`, `decline_reason`, `can_answer`; never the withdrawal
reason or the email outcome). Email templates `quote.sent.vi`, `quote.sent.en` (reference and
account link only).

## Audit actions added

`quote.sent`, `quote.withdrawn` (staff, `superseded by vN`, `customer merged`, `customer changed`),
`quote.accepted_superseded` (a newer version finalised after an acceptance),
`quote.accepted`, `quote.declined` (actor `customer_account:<account reference>`; detail carries
the account reference and, for a decline, the reason).

# Phase 13H — vendor rate-email intake

## `tariff_intake_settings` (migration `c5e8a1f3d7b9`)

One row (id 1), created when an administrator first saves; until then readers answer with the
owner's defaults and never write (OD-76, DEC-0214).

| Field | Type | Notes |
|---|---|---|
| `mailbox_address` | str(320) | Informational only; no mailbox is connected. Default the owner's Soleil address (OD-76) |
| `approver_emails` | JSON list | Normalised staff emails allowed to approve, reject, release, reprocess and activate (with `tariff:manage`). Default the owner's address; at least one, at most 20. Only a current approver changes it (recovery: any Admin when no current approver is an active Admin) |
| `allowed_sender_domains` | JSON list | Sender domains imported straight to a draft. Default empty: every email is held for an approver |
| `updated_at`, `updated_by_user_id` | | `updated_by_user_id` SET NULL |

## `tariff_email_intakes` (migration `c5e8a1f3d7b9`)

One row per vendor rate email received (upload or intake folder). Provenance only: **no email
body and no workbook content** is stored.

| Field | Type | Notes |
|---|---|---|
| `message_id` | str(255) | The email's Message-ID; `sha256:<digest>` of the file when it has none (or of the id when it is longer than 255). Unique together with `sender` (`uq_tariff_email_intakes_message_id_sender`) |
| `source_sha256` | str(64), indexed | SHA-256 of the whole `.eml`; the folder worker does not ingest or audit the same bytes twice |
| `stored_file` | str(255) | Folder emails: where the worker moved the file (`processed/…`, `failed/…`), relative to the intake folder; used to reprocess a failed one |
| `sender` | str(320) | Lower-case `From` address; null for an unreadable file |
| `subject` | str(300) | Plain text, one line, bounded; the draft's label (first 120 characters) |
| `received_at` | datetime | The email's `Date`, UTC; its date in America/Toronto is the draft's `effective_from` |
| `source` | str(10) | `upload` \| `folder` |
| `attachment_name`, `attachment_sha256` | str(255), str(64) | The one `.xlsx` attachment; the digest is of the workbook **after** any `DS SDT…` sheet was stripped |
| `warning` | str(300) | A note that did not stop the import, e.g. an email Date more than 60 days from the intake (the intake date was used) |
| `status` | str(20) | `received` \| `imported` \| `duplicate` \| `rejected` \| `failed` \| `no_attachment` \| `held_sender`; indexed |
| `tariff_version_id` | FK `tariff_versions` | SET NULL; the draft it produced (for `duplicate`, the version already holding that workbook) |
| `error` | str(500) | A plain reason; never a stack trace |
| `reviewed_at`, `reviewed_by_user_id`, `review_note` | | The approver's approval, rejection reason or release; `reviewed_by_user_id` SET NULL |
| `created_at` | datetime | |

## `tariff_version_reviews` (migration `c5e8a1f3d7b9`)

The approver's decision on a tariff version, whatever its source (email or manual import).
`tariff_versions` is not altered and has no rejected state; a `rejected` row here makes the
version impossible to approve or activate (409), by any path.

| Field | Type | Notes |
|---|---|---|
| `tariff_version_id` | FK `tariff_versions`, unique | CASCADE; one decision per version |
| `decision` | str(10) | `approved` \| `rejected` |
| `reviewed_by_user_id`, `reviewed_at` | | `reviewed_by_user_id` SET NULL |
| `note` | str(400) | The rejection reason |

Staff routes (`/api/v1`): `POST /tariffs/intake/upload` (multipart `.eml`), `GET /tariffs/intake`
(`viewer_is_approver` included), `POST /tariffs/intake/{id}/release`,
`POST /tariffs/intake/{id}/reprocess` (a failed folder email, approver only),
`GET/PATCH /tariffs/intake/settings`, `GET /tariffs/versions/{id}/diff`,
`POST /tariffs/versions/{id}/approve`, `POST /tariffs/versions/{id}/reject {reason}`; the existing
`POST /tariffs/versions/{id}/activate` is now approver-only. Intake routes need `tariff:manage`
(Admin); saving settings also `settings:manage`; the diff needs `tariff:read`.

## Audit actions added

`tariff_intake.received`, `tariff_intake.<status>` (imported, duplicate, rejected, failed,
no_attachment, held_sender), `tariff_intake.duplicate_message`, `tariff_intake.released`,
`tariff_intake.settings_updated` and `tariff_intake.approvers_recovered` (detail: old and new
approver and domain lists in full), `tariff_intake.reprocessed`, `tariff_version.approved`,
`tariff_version.rejected` (detail: the reason). Audit details carry the sender's domain, never the subject or body.

# Phase 15 — workflow hardening (no table added or altered; DEC-0216)

No new table and no new column. Values and response fields added:

* `notification_outbox.skip_reason` `closed`: the shipment's state was returned or cancelled
  before the row went out; the row's dedup key is freed. A milestone below the furthest milestone already reached (current state when on
  the ladder, and every other published, unvoided milestone event) is never queued; a returned
  or cancelled shipment queues nothing.
* `quote_offers.email_status` `resending`: a staff resend claimed the email; the send's outcome
  replaces it.
* Customer Account `AccountTimelineEntry.event_type` (`GET /api/v1/account/shipments/{reference}`):
  the published event's type from the public event vocabulary, so the account shows the standard
  wording for the step in the customer's language with the staff's published text beneath it.
  `AccountTimelineEntry.scope`: `package` when the entry covers some, not all, of several
  active parcels (worded "One of your parcels ..."), else `shipment`. The public tracking
  contract is unchanged.

Staff routes (`/api/v1`): `POST /quote-offers/{id}/resend-email` (the send / withdraw permission:
an unanswered offer whose email `failed`, or had `no_email` and the customer now has an address);
`GET /finance/accepted-not-invoiced?limit=` (`financial:read`; true `total`; read-only list of each shipment's latest
accepted offer with no live invoice: offer, shipment and reference, customer name, version,
accepted date, accepted total in CAD, master, `superseded_by_version`);
`GET /tariffs/intake/pending-count` (`tariff:read`; `viewer_is_approver`, `drafts_awaiting`,
`held_senders`, `total`; zeros for anyone who is not a designated approver).

## Audit actions added

`quote.email_resent` (entity `quote_offer`; detail: `shipment_id`, `previous_email_status`).

# Fix pack RC-UAT-18 — master lock, quote expiry, draft invoices (DEC-0219 to DEC-0221)

## `master_edit_unlocks` (migration `d4f7a2c9e1b8`)

An Admin's temporary unlock of a booked master's items and fee lines (DEC-0219).

| Field | Type | Notes |
|---|---|---|
| `consolidation_id` | FK `consolidations` | CASCADE; indexed; partial unique index `uq_master_edit_unlocks_open_consolidation` (one open unlock: `relocked_at IS NULL`) |
| `unlocked_by_user_id` | FK `users` | SET NULL |
| `reason` | str(400) | Required |
| `unlocked_at` | datetime | |
| `relocked_at`, `relocked_by_user_id` | datetime, FK `users` | Null while open; `relocked_by_user_id` SET NULL (null when automatic without an actor) |
| `relock_reason` | str(400) | Staff text, `Locked again by staff.`, or `quote vN finalised for SX-…` (automatic) |

## `invoice_drafts` (migration `d4f7a2c9e1b8`)

The invoice prepared as a draft when a customer accepts a quote (DEC-0221). Revenue only.

| Field | Type | Notes |
|---|---|---|
| `shipment_id` | FK `shipments` | RESTRICT; indexed; partial unique index `uq_invoice_drafts_live_shipment` (one `draft` per shipment) |
| `customer_id` | FK `customers` | RESTRICT; indexed; the payer |
| `quote_version_id` | FK `quote_versions` | RESTRICT; the accepted version |
| `offer_id` | FK `quote_offers` | SET NULL |
| `status` | str(12) | `draft` \| `issued` \| `discarded` |
| `bill_to_name` | str(200) | |
| `bill_to_address` | text | Up to 1,000 characters, line breaks kept |
| `customer_reference` | str(120) | The customer's reference / PO; printed as `purchase_order_reference` |
| `notes` | text | Up to 2,000 characters, printed on the invoice |
| `tax_rate_percent` | int | 0, 5 or 13 (OD-64) |
| `lines_json` | text | `[{"description", "amount_cad"}]`, at most 50 lines, amounts ≥ 0 with two decimals, total > 0 |
| `quote_total_cad` | numeric(12,2) | The accepted quote's total before tax, frozen at creation |
| `total_change_reason` | str(400) | Required when the lines' total differs from `quote_total_cad`; cleared when it no longer does |
| `revision` | int | Starts at 1; +1 on every save, the send and a discard |
| `created_at`, `created_by_user_id`, `created_by_identity_id` | | FKs SET NULL; the identity is the accepting Customer Account |
| `updated_at`, `updated_by_user_id` | | SET NULL |
| `issued_invoice_id`, `issued_at` | FK `customer_invoices`, datetime | SET NULL; set by Send |
| `discarded_at`, `discard_reason` | datetime, str(400) | Replaced by a newer acceptance, or the quote expired |
| `email_status` | str(20) | Invoice email after Send: `sent` (capture) \| `recorded` (null transport) \| `no_email` \| `failed` \| `skipped`. No address, no body |

## `quote_expiries` (migration `d4f7a2c9e1b8`)

A finalised quote version that expired on a new tariff version (DEC-0220).

| Field | Type | Notes |
|---|---|---|
| `quote_version_id` | FK `quote_versions`, unique | CASCADE; one expiry per version |
| `shipment_id` | FK `shipments` | CASCADE; indexed |
| `tariff_version_id` | FK `tariff_versions` | SET NULL; the version whose activation expired it |
| `offer_id`, `previous_offer_status` | FK `quote_offers`, str(12) | SET NULL; the offer turned `expired`, and whether it was `sent` or `accepted` |
| `invoice_draft_id` | FK `invoice_drafts` | SET NULL; the draft withdrawn |
| `reason` | str(400) | `tariff TRF-… became active before the goods were received` |
| `expired_at` | datetime | |

`quote_offers.status` gains the value `expired` (no schema change). New permission
`master:unlock` (Admin). New email templates `invoice.sent.vi`, `invoice.sent.en`
(parameters `invoice_number`, `total`, `due_date`).

## Audit actions added

`master.unlocked`, `master.relocked` (detail `automatic`); item and fee audits carry
`master_unlock_id` while unlocked; `quote.expired`; `invoice.draft_created` (actor
`customer_account:CA-…`), `invoice.draft_edited` (detail `changes {field: {from, to}}`,
`revision`), `invoice.draft_sent`, `invoice.draft_discarded`; `invoice.issue` detail gains
`from_draft`.

## Fix pack RC-UAT-18: tariff readings and vendor names (DEC-0222)

- `tariff_versions.import_report_json`: new key `confirmed_price_steps` -- list of
  `{sheet, cell, product_code, zone, label, reference, message}`; informational, never an anomaly.
  `anomaly_counts.price_falls_with_weight` is absent for the 12 October 2026 workbook
  (was 3); `counts.anomalies` is 39 (was 42).
- `tariff_surcharge_rules.semantics_note` for HCM air row 41 now cites DEC-0222 and route VN-CA.
- `quote_offers.customer_view_json.surcharges[].name`: a vendor-naming label is stored neutral
  for offers sent from now on; older offers are made neutral when read by the account routes.
- `customer_invoice_lines.description`: unchanged in storage; the invoice document shows the
  neutral label when it names a vendor.

# Fix pack RC-UAT-19 (DEC-0223 to DEC-0225)

## `invoice_draft_tax` (migration `e6b1c4a8d2f3`)

A draft invoice's GST/HST mode and the staff confirmation (DEC-0223). One row per draft.

| Field | Type | Notes |
|---|---|---|
| `draft_id` | FK `invoice_drafts`, unique | CASCADE |
| `mode` | str(10) | `included` (backed out of the all-in lines) \| `added` (on top) |
| `rate_percent` | int | Mirror of `invoice_drafts.tax_rate_percent` (the source of truth), written with every save |
| `confirmed_revision` | int, null | The draft revision whose GST/HST staff confirmed; equal to `invoice_drafts.revision` = confirmed |
| `confirmed_at`, `confirmed_by_user_id` | datetime, FK `users` | SET NULL |
| `created_at`, `updated_at` | datetime | |

No row = a draft from before 2026-10-22: read as `added` at its rate, unconfirmed.

## Existing columns, new values or meanings (nothing altered)

* `tariff_surcharge_rules.basis`: new value `manual_amount` (HCM air row 27 on re-import).
* `shipment_fee_lines.manual_unit_price_vnd`: for a `manual_amount` line, the line's whole
  amount (VND), not a unit price; `quantity` is 1 and `weight_kg` null for such a line.
* `customer_invoices.document_json`: adds `tax_mode`, `tax_rate_percent` for an invoice sent
  from a draft. With `tax_mode = included`, `subtotal_cad + tax_cad = total_cad = Σ lines`.
* API: `DraftUpdateIn` also adds `confirmed_total_cad`, `confirmed_tax_mode`,
  `confirmed_tax_rate_percent`; public and account details add `carrier_links`.
* API: `InvoiceDraftOut` adds `tax_mode`, `tax_confirmed`, `tax_confirmed_at`,
  `tax_confirmed_by`, `lines_total_cad`; `DraftUpdateIn` adds `tax_mode`, `tax_confirmed`;
  `InvoiceDocumentOut` adds `tax_mode`, `tax_included_note`; public and account
  `carrier_link` add `tracking_name_key`.
* New route: `PATCH /shipments/{id}/fee-lines/{line_id}` (staff).

# Fix pack RC-UAT-20 (DEC-0227 to DEC-0229) -- (migration `f7c2d9e3a1b5`)

**`tax_rates`** (DEC-0227) -- GST/HST rate per Canadian province or territory.
| Column | Type | Notes |
|---|---|---|
| `province_code` | String(2), PK | ON, NS, NB, NL, PE, AB, BC, MB, QC, SK, NT, NU, YT |
| `rate_percent` | Integer, not null | whole percent, 0–30 (drafts store an integer rate) |
| `tax_label` | String(10), not null | `GST` or `HST` |
| `updated_at` | DateTime, not null | seed: 2026-10-23 |
| `updated_by_user_id` | FK users, SET NULL | null for seeded rows |
Seeded: ON 13 HST; NS 14 HST; NB, NL, PE 15 HST; AB, BC, MB, QC, SK, NT, NU, YT 5 GST. Code
defaults (`tax_rate_service.DEFAULT_RATES`) apply to a province without a row.

**`invoice_draft_tax_route`** (DEC-0227) -- what a draft's GST/HST was auto-filled from; one
row per draft created from RC-UAT-20 on (older drafts have none).
| Column | Type | Notes |
|---|---|---|
| `id` | Integer, PK | |
| `draft_id` | FK invoice_drafts, CASCADE, unique | |
| `route_band` | String(16) | `international` / `domestic` |
| `origin_country_code`, `destination_country_code` | String(2), null | as read |
| `destination_province` | String(2), null | null = unknown |
| `suggested_rate_percent` | Integer, null | null when staff must choose |
| `suggested_mode` | String(10) | `included` |
| `rate_required` | Boolean | true when no rate could be suggested |
| `rate_chosen_at`, `rate_chosen_by_user_id` | DateTime / FK users SET NULL, null | set by the save that chose the rate |
| `created_at` | DateTime | |
While `rate_required` and `rate_chosen_at` is null, `invoice_drafts.tax_rate_percent` holds the
placeholder 0 (the column is not nullable); it is never shown, confirmed or sent.

**`fee_line_manual_prices`** (DEC-0228) -- customer price of a `manual_amount` fee line.
| Column | Type | Notes |
|---|---|---|
| `id` | Integer, PK | |
| `fee_line_id` | FK shipment_fee_lines, CASCADE, unique | one per line |
| `customer_price_cad` | Numeric(12, 2), not null | > 0, ≤ 9,999,999,999.99 |
| `updated_at` | DateTime | |
| `updated_by_user_id` | FK users, SET NULL | |

`customer_payments.received_at` (unchanged type): naive midnight of the plain received date,
never shifted by a zone (DEC-0229 §1).

# Build RC-UAT-21 (DEC-0230 to DEC-0233)

## Shipment import and legacy history (DEC-0230)

| Table | Column | Notes |
|---|---|---|
| `shipment_import_links` | `batch_id` → `import_batches.id` | The committed batch (kind `shipments`). |
| | `row_number` | Spreadsheet row (header = 1). |
| | `shipment_id` → `shipments.id` | Unique: one batch per imported shipment. |
| | `source_system`, `external_reference` | Unique pair; `csv_shipment_import` + the file's reference. Duplicate refusal. |
| | `created_at` | Commit time. |
| `legacy_baselines` | `batch_id` → `import_batches.id` | Unique; the batch (kind `legacy_history`). |
| | `source_system` | `legacy_csv`. |
| | `cutoff_date` | Optional; every row booked on or before it. |
| | `status` | `active` \| `voided`. |
| | `created_count` | Records this baseline created. |
| | `voided_at`, `voided_by_user_id`, `void_reason` | Soft void. |
| `legacy_shipments` | `baseline_id`, `row_number` | Provenance. |
| | `customer_id` → `customers.id` | Existing customer (RESTRICT). |
| | `source_system`, `legacy_reference` | The old system's reference. |
| | `active_key` | Unique; `source_system\|legacy_reference` while live, NULL once voided. Idempotent re-run. |
| | `route_group`, `direction`, `transport_mode` | Validated like a booking; mode always `air`. |
| | `booked_on`, `final_status`, `completed_on` | `delivered` \| `returned` \| `cancelled` \| `lost`; closing date for the first three. |
| | `recipient_*`, `package_count`, `total_weight_kg`, `contents_description` | Optional summary. |
| | `notes` | Staff-only. |
| | `is_voided`, `voided_at` | Set when the baseline is voided. |
| `legacy_shipment_events` | `legacy_shipment_id`, `sequence` | Unique pair; journey order. |
| | `event_type` | `ShipmentEventType` value, or `cancelled` / `lost`. |
| | `occurred_on` | Date of the milestone. |

`import_batches.kind` now takes `customers`, `shipments`, `legacy_history`
(`GET /imports/batches?kind=` filters). No existing column changed.

## Account security (DEC-0231, DEC-0232)

**`customer_email_change_requests`** (new, DEC-0231) — one row per self-service email-change
request. `id`; `identity_id` → `customer_identities` (CASCADE); `token_id` →
`customer_auth_tokens` (SET NULL; null when the single email rule refused the request and no
message was sent); `new_email_entered`, `new_email_normalized` (the address asked for; the
identity keeps its old address until confirmation); `status` `pending | completed | superseded |
cancelled | refused`; `refused_reason_code` (internal, never serialized:
`address_in_use_identity`, `address_in_use_customer`, `status_<x>`); `requested_at`,
`expires_at` (= the token's, the OD-36 verification period), `closed_at`, `request_ip`. Index
`(identity_id, status)`. Retention: account-lifecycle record (OD-01 dependent); holds an email
address the customer typed.

**`customer_account_reinstatements`** (new, DEC-0231) — one row per Admin reinstatement of a
deactivated account. `id`; `identity_id` → `customer_identities` (CASCADE, indexed);
`deactivated_at`, `deactivated_by_user_id` → `users` (SET NULL), `deactivation_reason_code` (the
deactivation reversed, copied before the identity's columns are cleared); `restored_status`
(`active | pending_approval | pending_verification | suspended`); `reason_code`
(`deactivated_in_error | customer_request | review_complete`); `note` (≤ 500, staff only, never
in an audit payload); `reinstated_at`; `reinstated_by_user_id` → `users` (SET NULL).

**`customer_auth_tokens.purpose`** — new value `email_change` (no schema change; String(30)).
Purpose-bound digest as the other two; `issued_to_email_normalized` is the **new** address.

**Audit actions** (new): `customer_account.password_changed`,
`customer_account.password_change_refused`, `customer_account.email_change_requested`,
`customer_account.email_change_cancelled`, `customer_account.email_changed`,
`customer_account.email_change_refused`, `customer_account.reactivate`,
`customer_account.deactivated_list_read`, `auth.password_change`,
`auth.password_change_refused`.

**Email templates** (new, en + vi): `account.password_changed_here`,
`account.email_change_confirm`, `account.email_change_requested` (to the current address),
`account.email_changed_notice`, `account.reinstated`.

**`customer_identity_links.revoke_reason_code`** — new values (no schema change):
`merged_since_deactivation`, `archived_since_deactivation` (a reinstatement ended the link).

## Quote soft delete and retention (DEC-0233)

* **`quote_version_deletions`** — Admin soft delete of a quote version (DEC-0233). `id` PK;
  `quote_version_id` FK `quote_versions` SET NULL, nullable (NULL once purged), indexed;
  `shipment_id` FK `shipments` CASCADE, indexed; `version` int (kept after a purge); `reason`
  varchar(400) required; `deleted_at`, `deleted_by_user_id` (FK users SET NULL);
  `restored_at`, `restored_by_user_id`, `restore_reason` (null until restored); `purged_at`
  (set when the retention worker removed the version). Partial unique index
  `uq_quote_version_deletions_open_version` on `quote_version_id` WHERE `restored_at IS NULL`.
  Retention: kept (it is the audit of a deletion).
* **`data_retention_settings`** — one row (`id = 1`), seeded off. `enabled` bool;
  `enabled_at`, `enabled_by_user_id`; `quote_delete_min_age_days` int (0); `batch_size` int
  (200); `updated_at`, `updated_by_user_id`. A database without the row reads as all-off
  (reading never writes).
* **`data_retention_policies`** — PK `record_class` varchar(40); `enabled` bool (false);
  `period_days` int nullable (NULL = undecided); `action` varchar(10) `delete|anonymise`;
  `last_run_at`, `last_run_affected`; `updated_at`, `updated_by_user_id`. Seeded with the eight
  classes, all disabled, no period. A missing row reads as the default.
* **`data_retention_runs`** — run log. `id`; `dry_run` bool; `trigger` `worker|admin`;
  `actor_user_id` (FK users SET NULL; the Admin of a screen dry run); `status`
  `completed|failed`; `counts_json` (per class: eligible/affected/action/ran — counts only, never
  record content); `error` varchar(300); `started_at` (indexed), `finished_at`. Retention: kept.
* Permissions: `quote:delete`, `retention:manage` (Admin only).
* Audit actions: `quote.soft_delete`, `quote.restore`, `data_retention.enable`,
  `data_retention.disable`, `data_retention.settings_update`, `data_retention.policy_update`,
  `data_retention.dry_run`, `data_retention.run`.

## Import CSV formats (DEC-0230)

UTF-8 (with or without BOM), comma-separated, header row required, column names matched
case/accent/punctuation-insensitively; unknown columns are reported and ignored. Dates are
**`YYYY-MM-DD` only** (ISO); a slash date such as `01/02/2024` is refused as
`invalid_date`, never guessed (it means different days in Vietnam and the United States). Templates: `artifacts/sample-imports/
shipment-import-template.csv`, `artifacts/sample-imports/legacy-history-template.csv`
(also downloadable from each page). Test fixtures: `backend/tests/fixtures/rc21_*.csv`.

#### 4.1 Shipment import — one row per shipment

| Column (aliases) | Req. | Meaning |
|---|---|---|
| `external_reference` (`external_ref`, `reference`) | **yes** | Unique reference from the source; ≤ 120 chars; never starts with `= + - @`. Duplicate → refused. |
| `customer_ref` (`customer_id`, `customer`) | **yes** | Solaris customer ID (`STCA-000123`, former IDs accepted) or the `source_record_id` a customer import gave the customer. Must exist. |
| `recipient_name`, `recipient_city`, `recipient_country_code` | **yes** | Recipient; country must match the route direction (CA for VCA). |
| `contents_description` (`contents`) | **yes** | ≤ 400 chars. |
| `package_weights_kg` (`weights_kg`) | **yes** | One weight per package in kg, `;`-separated, e.g. `12.5;8`. 1–99 packages, each > 0 and ≤ 500 kg. |
| `route_group` (`route`) | no | `VCA` (default), `CAV`, `CAD`, `XUS`; also `VN-CA`, `CA-VN`, … |
| `direction` | no | Needed only for `XUS` when the countries do not decide it. |
| `transport_mode` (`mode`) | no | Blank or `air`. Anything else is refused. |
| `service_type` | no | `standard_parcel` (default), `express_parcel`, `epacket`, `other`. |
| `booking_state` | no | `draft` (default) or `confirmed` (normal confirmation; issues the Solaris ID). |
| `booking_date` | no | Not in the future. |
| `booking_reference` | no | Customer's own reference (≤ 60). |
| `sender_name`, `sender_phone`, `sender_address_line1`, `sender_city`, `sender_province_state`, `sender_postal_code`, `sender_country_code` | no | Sender name defaults to the customer's name; country to the route's origin. |
| `recipient_company`, `recipient_phone`, `recipient_email`, `recipient_address_line1`, `recipient_address_line2`, `recipient_province_state`, `recipient_postal_code`, `recipient_delivery_note` | no | Recipient details. |
| `package_dimensions_cm` (`dimensions_cm`) | no | `LxWxH` per package, `;`-separated, same count as the weights, e.g. `40x30x30;30x30x20`. |
| `items` | no | `description\|quantity\|unit\|declared value`, `;`-separated, e.g. `Áo dài\|2\|piece\|80;Cà phê\|3\|box\|30`. Units: piece, pair, box, bottle, set, kg, carton, other. |
| `declared_value`, `declared_value_currency` (`currency`) | no | ≥ 0; three-letter code (item values use it, default CAD). |
| `internal_notes` (`notes`) | no | Staff-only. |

Example:

```
external_reference,customer_ref,recipient_name,recipient_city,recipient_country_code,contents_description,package_weights_kg,booking_state
SAMPLE-SHP-0001,STCA-000001,Trần Thị Mẫu,Toronto,CA,Quà tặng gia đình,12.5;8,draft
```

#### 4.2 Legacy history — one row per past shipment

| Column (aliases) | Req. | Meaning |
|---|---|---|
| `legacy_reference` (`legacy_ref`, `old_reference`, `reference`) | **yes** | Old system's reference; same identifier rules as above. |
| `customer_ref` | **yes** | As above; must exist. |
| `booked_on` (`booking_date`) | **yes** | Not in the future; ≤ the baseline cutoff date when one is given. |
| `final_status` (`status`) | **yes** | `delivered`, `returned`, `cancelled`, `lost`. |
| `route_group`, `direction`, `transport_mode` | no | As above; air only; default VCA. |
| `recipient_name`, `recipient_city`, `recipient_province_state`, `recipient_country_code` | no | Summary. |
| `package_count` (1–99), `total_weight_kg` (> 0), `contents_description`, `notes` | no | Summary; notes staff-only. |
| `received_on`, `departed_on`, `customs_on`, `arrived_on`, `out_for_delivery_on` | no | Milestone dates, in this journey order, never earlier than the previous one or than `booked_on`, never in the future. |
| `delivered_on` / `returned_on` / `cancelled_on` | per status | The closing date the final status requires; a closing date that contradicts the status is an error. |

Each record gets a `booked` milestone plus one per filled date (`lost` adds a closing `lost`
milestone at the last known date). Example:

```
legacy_reference,customer_ref,booked_on,final_status,departed_on,delivered_on
SAMPLE-OLD-0001,STCA-000001,2024-03-01,delivered,2024-03-06,2024-03-12
```

# Build RC-UAT-22 (DEC-0234)

## Orphaned-account re-links and closures (DEC-0234)

### `customer_account_relinks`

One row per staff action on an orphaned Customer Account (approved once, now `pending_approval`
with no active link and no pending proposal). Append-only; written by
`customer_account_relink_service`.

| Column | Type | Meaning |
|---|---|---|
| `id` | integer PK | |
| `identity_id` | FK `customer_identities.id`, not null | The account acted on |
| `action` | varchar(20), not null | `relink` or `close` |
| `previous_customer_id` | FK `customers.id`, null | The customer of the account's last link, if any |
| `previous_link_end_reason` | varchar(40), null | Why that link ended (`merged_since_deactivation`, `archived_since_deactivation`, …) |
| `target_customer_id` | FK `customers.id`, null | The customer linked (re-link only) |
| `reason_code` | varchar(40), not null | Re-link: `merge_survivor`, `correct_customer`, `other`; close: `no_customer`, `duplicate`, `other` |
| `note` | varchar(500), null | Staff-only note; never in the audit detail |
| `disclosed_shipment_count`, `oldest_booked_at`, `newest_booked_at`, `includes_cancelled`, `includes_rebooked`, `disclosure_definition_version` | null | The OD-29 history figures the Admin acknowledged (re-link only) |
| `preview_fingerprint` | varchar(64), null | Digest of the preview that was acknowledged (re-link only) |
| `acted_at` | datetime, not null | UTC |
| `acted_by_user_id` | FK `users.id`, null | The Admin |

A closure also sets the identity's `status_reason_code` to `orphan_closed` through the ordinary
deactivation.

# Build RC-UAT-23 (DEC-0235)

## Invoices on the Solaris Invoicing layout (no schema change)

No table or column is added or altered (DEC-0181); `alembic upgrade head` + `alembic check` on a
scratch DB: "No new upgrade operations detected."

**`customer_invoices.document_json`** — keys added on every invoice issued from RC-UAT-23
(both the draft Send path and the manual Issue invoice path):

| Key | Type | Meaning |
|---|---|---|
| `tax_layout` | string | `"invoicing_v1"`: the Solaris Invoicing layout (DEC-0235). Absent on an invoice issued before: that invoice reads and prints exactly as it did. |
| `tax_mode` | string | `included` / `added`. Was written only by the draft path; now the manual path writes `"added"` too (readers already defaulted to `added`). |
| `tax_lines` | list | One object per line, in line order: `sequence` (= `customer_invoice_lines.sequence`), `quantity` (string, as written; `"1"` when the line has none), `unit_price_cad` (string, 4 dp: the Rate column, net / qty), `net_cad`, `tax_cad`, `gross_cad` (net + tax), `tax_code` ("Zero-rated", "GST", "HST ON", "HST 14%", "HST 15%", …). |
| `tax_rows` | list | Summary rows, one per distinct tax code: `label` ("GST @ 0%", "GST @ 5%", "HST ON @ 13%", "HST @ 14%", "HST @ 15%"), `tax_cad`. |

**`customer_invoice_lines.amount_cad`** — on a `tax_layout: invoicing_v1` invoice, the line's
**net** (before tax); on an older one, the amount as entered (gross in included mode).
`quantity` / `unit` unchanged (None on draft-path lines; the quote line's on the manual path).

**`customer_invoices.subtotal_cad / tax_cad / total_cad`** — v1: Σ net, Σ line tax, Σ gross.
Revenue (profitability, the period-close snapshot) is still `subtotal_cad`; AR, payments,
receipts and the invoice email read `total_cad` as before.

**API (response fields added, all optional / nullable):**

* `InvoiceDraftOut`: `tax_layout`, `tax_lines[] {description, quantity, unit_price_cad, net_cad, tax_cad, gross_cad, tax_code}`, `tax_rows[] {label, tax_cad}` (None while no rate is chosen).
* `InvoiceDetailOut` (staff): `tax_layout`, `tax_rows`; `InvoiceLineOut`: `unit_price_cad`, `tax_cad`, `gross_cad`, `tax_code` (None on older invoices).
* `InvoiceDocumentOut`: `company_email`, `tax_layout`, `tax_rows`, `payment_terms`, `payment_etransfer`, `payment_wire`; lines `unit_price_cad`, `tax_cad`, `gross_cad`, `tax_code`. Key names avoid "rate" (the customer-document key screen in `test_finance_golden.py` forbids it), hence `unit_price_cad` for the Rate column.
* `ReceiptDocumentOut`, `QuoteDocumentOut`: `company_email`.

**Constants:** `finance_service.COMPANY` (name "Solaris Express Inc.", trade name "Solaris
Express" kept, address "2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6", BN
unchanged, new `company_email`), `finance_service.PAYMENT` (`payment_etransfer`,
`payment_wire`), `finance_service.INVOICE_FOOTER`, `finance_service.payment_terms(days)`;
`invoice_tax_math.LAYOUT = "invoicing_v1"`.

# Build RC-UAT-25 (DEC-0240 to DEC-0247)

Ben's live UAT fixes of 2026-10-25 (OD-113). Migration `a5c7e9b1d3f6` (revises `e7a9c1d3f5b6`)
adds two tables; nothing existing is altered (DEC-0181).

## Admin change of a sign-in email (DEC-0243)

### `customer_account_email_changes`

An Admin changed a Customer Account's sign-in email (RC-UAT-25 item 2). One row per change;
never updated.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer PK | no | |
| `identity_id` | FK `customer_identities.id` ON DELETE CASCADE, indexed | no | the account |
| `customer_id` | FK `customers.id` ON DELETE SET NULL | yes | the linked customer whose email followed; null when the account had no link (pending approval) |
| `previous_email_entered` | varchar(320) | no | the address before, as entered (personal data; staff only; never serialized to the customer) |
| `new_email_entered` | varchar(320) | no | the address after, as entered |
| `reason_code` | varchar(40) | no | `customer_request` · `mailbox_lost` · `entered_in_error` |
| `note` | varchar(500) | yes | Admin's optional note; never in the audit payload |
| `sessions_revoked` | integer | no | sessions ended by the change |
| `changed_at` | datetime (UTC) | no | |
| `changed_by_user_id` | FK `users.id` ON DELETE SET NULL | yes | the Admin |

**`customer_email_change_requests`** (RC-UAT-21) — no new rows from customers. New values (no
schema change): a pending request closed when the customer opens "Sign-in and security" ends
`cancelled`, and a link used after RC-UAT-25 ends `refused`, both with reason
`self_service_withdrawn`.

**API.** Staff: `POST /api/v1/customer-account/identities/{reference}/sign-in-email`
(`customer_account:review` + `customer_account:deactivate`, Admin only), body
`{new_email (≤ 320), reason_code (≤ 40), note? (≤ 500)}`; 422 for the account's own address, a
malformed address or an unlisted reason; 409 for an address held by another account or customer
record, or an account that is pending verification, rejected or deactivated.
`IdentityStatusOut` gains `can_change_sign_in_email` (the account's status allows it; the
caller's permission is checked separately). Customer: `POST /api/v1/account/email/change` answers
403 to every request; `/account/email/change/confirm` refuses every link; `GET
/account/security` keeps `pending_email_change`, always null.

**Audit action** (new): `customer_account.sign_in_email_changed_by_staff` (identity and customer
references, reason code, sessions-ended count, keyed `address_key` of both addresses; never an
address, never the note). **Email template** (new, en + vi): `account.sign_in_email_set_by_staff`
(to the new address, with the sign-in link); the old address gets the existing
`account.email_changed_notice`.

## Timeline event corrections (DEC-0245)

### `shipment_event_revisions`

Staff edited a timeline event (RC-UAT-25 item 6). One row per edit; never updated. The event
rows themselves are corrected in place.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer PK | no | |
| `shipment_id` | FK `shipments.id` ON DELETE CASCADE, indexed | no | |
| `event_ids_before` | text (JSON list) | no | the recording's live rows before the edit |
| `event_ids_after` | text (JSON list) | no | the live rows after (kept + added; removed packages' rows are voided) |
| `before_json` / `after_json` | text (JSON object) | no | `event_type`, `occurred_at`, `location_label`, `location_country_code`, `leg_id`, `package_ids`, `internal_detail`, `public_update_template_key`, `public_update_text`, `is_final_recipient_delivery` |
| `reason` | varchar(255) | no | required |
| `was_published` | boolean | no | the event was published when edited |
| `public_wording_changed` | boolean | no | the customer-visible sentence changed |
| `edited_at` | datetime (UTC) | no | |
| `edited_by_user_id` | FK `users.id` ON DELETE SET NULL | yes | |

**API.** `POST /api/v1/shipments/{id}/events/edit` (`tracking:write`), body `EventEditIn`:
`event_ids` (1–200, the rows of one recording), `event_type`, `occurred_at?` (omitted =
unchanged), `package_ids` (empty = every active package), `leg_id?`, `location_label?` (≤ 160),
`location_country_code?`, `internal_detail?`, `public_update_template_key?` (≤ 80),
`public_update_text?` (≤ 400), `reason` (≤ 255, required). `GET
/api/v1/shipments/{id}/event-revisions` (shipment readers): `EventRevisionOut` — `id`,
`shipment_id`, `event_ids_before`, `event_ids_after`, `before`, `after`, `reason`,
`was_published`, `public_wording_changed`, `edited_at`, `edited_by`. A package removed by an edit
has its row voided (reason "Removed from this event by an edit: …"). **Audit action** (new):
`shipment.event_edit` (revision id, rows, changed fields, before/after without free text, the
reason, the actor). No notification row is ever written by an edit.

## "Received at warehouse" and the standard-update catalogue (DEC-0244)

No data change: the stored code stays `received_at_solaris` (event type and operational state);
its label is now "Received at warehouse" / "Đã nhận hàng tại kho" (`VALUE_LABELS`, staff API
`event_type_label`, every catalogue).

**Standard updates** (`backend/app/content/public_update_templates.json`): new key
`received_at_solaris.v2` — "We have received your shipment at our warehouse." / "Chúng tôi đã
nhận lô hàng của bạn tại kho." — the only one offered for the event type. `received_at_solaris.v1`
("…at our facility.") is **retired**: the catalogue gains a top-level `retired` list; a retired
key still renders on events that carry it (`shipment_events.public_update_template_key`) and is
never offered again. `check_catalogue` refuses a retired key that is unknown or still offered.

## Booking currency list and recipient addresses (DEC-0241, DEC-0242)

No schema change. **`shipments.declared_value_currency`** — accepted values on draft create and
edit are now `CAD` and `VND` only (`booking_service.DECLARED_VALUE_CURRENCIES`; lower case stored
upper case; blank = none); a code stored before the list is kept and accepted when re-sent
unchanged. **`GET /api/v1/shipments/meta`** gains `declared_value_currencies` (`["CAD", "VND"]`).
Refusal: 422, field `declared_value_currency`. **Shipment CSV import**: column
`declared_value_currency` checked against the same list per row (problem code
`invalid_currency`). Recipient addresses: no API change — the booking screen reads the existing
`GET /customers/{id}/addresses` and sends the existing `address_id`.

## Shipment financials (DEC-0246, DEC-0247)

No schema change. **`shipments.currency`** (the Financials tab's recorded amounts) — `PATCH
/api/v1/shipments/{id}/financials` now accepts only three ASCII letters (upper-cased; blank stored
as null) and refuses anything else with 422, field `currency`
(`shipment_finance_summary_service.recorded_currency`). A value stored before the fix is not
rewritten (the screen shows it as entered, with a warning).

**`GET /api/v1/shipments/{id}/financial-summary`** (new, read-only, `financial:read`):
`ShipmentFinancialSummaryOut` — `shipment_id`; `master {id, public_id, state, locked}` or null;
`quote` (the newest version still listed) and `finalised_quote` (the newest finalised one), each
`{id, version, status, finalized_at, total_revenue_cad, allocated_cost_cad, gross_profit_cad,
expired}` with the cost and profit null for a role without `tariff:read`; `invoice {id,
public_id, status, total_cad, paid_cad, balance_cad, issued_at}` or null; `draft_invoice {id,
status, revision}` or null; `next_step` (`add_to_master` · `price` · `finalise_quote` · `requote`
· `issue_invoice` · `review_draft` · `open_invoice`); `invoice_blocked_reason` and
`invoice_blocked_code` (what Issue invoice would answer now, word for word, from
`finance_service.invoiceable_version`); `cost_visible`, `can_issue_invoice`, `can_price`.
