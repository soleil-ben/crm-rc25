# 09 — Phase 13B completion record: consolidation, items, payer, service mapping

**Date:** 2026-10-19 · **Branch:** `phase-13-b2c-merge` · **Base:** ca04230 (Phase 13A +
OD-42 to OD-45) · **Migration:** `b8d4f2a6c1e7` (head), from `a7c3e1d9b2f4` ·
**Decisions:** DEC-0178 to DEC-0182 · **Scope:** air only (OD-43)

Backend only. No public or Customer Account route or schema changed; no frontend file
changed. Nothing is deployed. No request was made to the vendor or the bank.

## 1. What was built

| Area | Files | What it does |
|---|---|---|
| Consolidation entity | `app/models/consolidation.py`, `app/services/consolidation_service.py` | The handoff's master: `MST-000001`, vendor, Solaris service, origin, vendor reference, master weight and dimensions, carton count, cutoff and hand-over dates; `open → booked → completed` or `cancelled`. Memberships with a partial unique index (one active consolidation per shipment, history kept). Only confirmed, live, Vietnam → Canada shipments may join |
| Booking | same | Resolves the vendor product through the active tariff's `service_vendor_products` row for the service and origin, copies the divisor, computes and stores volumetric and chargeable weight; refuses with the reason when no tariff is active or the service is unmapped (Sea, UPS) |
| Master milestones | same | One event per active member through `event_service.record_event`; each marked by a `consolidation_event_links` row; the same type and time is never fanned out twice to a member; refused members are reported, not fatal; package targets refused on the master |
| Chargeable weight | `app/pricing/chargeable_weight.py` | Greater of actual and L×W×H/divisor; above 20.5 kg rounded up to the whole kilogram (the sheet's rule); below, to the next 0.5 kg band as a recorded convention (V-01) |
| Service mapping | `app/pricing/service_mapping.py`, `tariff_import_service._write_service_mapping` | Air Standard → `AIR-CAD`, Air Express → `AIR-CAD EXPRESS`, written per origin for every imported tariff version |
| Commodity items | `app/services/shipment_item_service.py` | Numbered lines with quantity, unit, weight, declared value, optional package; removal deactivates; read-only once the booking is cancelled |
| Payer | `booking_service._resolve_payer`, `set_payer`, `shipment_payers` | A distinct paying customer, settable at creation and after confirmation; naming the booking customer stores nothing |
| Routes | `app/api/v1/routes/consolidations.py`, `app/schemas/consolidation.py` | 15 staff routes: consolidations list / create / detail / update / members add / remove / book / complete / cancel / events; shipment items list / add / update / remove. Consolidation reads need `shipment:read` + `tariff:read` (vendor data); writes add `shipment:write`; master milestones `tracking:write` + `tariff:read`; items keep the shipment permissions |
| Shipment detail | `app/api/shipment_presenters.py`, `schemas/shipment.py` | Gains `payer`, `consolidation` (summary) and `items`; `payer_customer_id` accepted on create and update |
| Migration | `alembic/versions/b8d4f2a6c1e7_…` | Six new tables, nothing altered; up, check, down, up verified on a scratch database and in tests |

## 2. The design change the tests forced

The first draft added `payer_customer_id` to `shipments` and `consolidation_id` to
`shipment_events`. The Phase 4A populated-database test then lost the shipment's packages:
SQLite cannot add a foreign-key column in place, Alembic rebuilt `shipments`, and with
`PRAGMA foreign_keys` on, dropping the original cascaded into every child table. The pragma
cannot be turned off inside Alembic's transaction. Both facts are now link tables
(`shipment_payers`, `consolidation_event_links`); the migration touches nothing existing
and the Phase 4A column guard is unchanged (DEC-0181).

## 3. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean |
| `verify_decision_log.py`, `verify_owner_decisions.py` | pass |
| New tests | `test_consolidations.py` (membership rules, booking and its preconditions, mapping for Standard / Express / Sea / UPS, cancellation, master milestone to three members with duplicate refusal and inherited marks, refusals for future time / package target / cancelled member, the whole flow over HTTP, roles, and a planted vendor reference scanned out of the public tracking page); `test_shipment_items.py` (numbering, deactivation, validation, read-only when cancelled, HTTP, payer at creation and after confirmation); `test_chargeable_weight.py` (the 21 kg / 60×40×40 example, rounding table, trucking divisor); `test_migrations_phase13b.py` (empty, partial index behaviour, populated database up and down with existing schema and row counts unchanged, deletion behaviour on every key) |
| Adjusted tests | `test_migrations_phase13a.py` targets its own revision for the downgrade test, as head moved |
| Full backend suite | **3,308 passed, 2 failed** (two halves, 334 s + 649 s); the two failures are the environmental pair every worktree run shows |
| Independent review | one subagent review of the uncommitted change set: 8 verified and 6 suspected findings, all applied before the final gates — payer rows follow a customer merge; cancelling a shipment releases it from its consolidation in any state and booking refuses a member that is no longer confirmed; a milestone with no stated time repeats on type alone; consolidation reads need `tariff:read` and the shipment page hides the vendor reference from other roles; a booked consolidation accepts a corrected vendor reference; the migration backfills mapping rows for tariffs imported before it; a membership race surfaces as 409; volumetric weight and item figures are quantized to their stored precision; item currency is normalised; the privacy key lists name the new vocabulary; the migration docstring and DEC-0178 / DEC-0180 say what the code does |
| Frontend | unchanged; re-run anyway: eslint clean, 538 unit tests, build, 295 Playwright |
| Alembic | 11 up, check clean, 1 down, 1 up on a scratch database |

## 4. Directive acceptance tests touched

v2.1 test 2 (shared master: a verified milestone reaches the right children, each customer
sees only their own) and test 8 (the same milestone twice is one event) are asserted in
`test_consolidations.py`; the notification half of test 8 waits for Phase 13F. Test 1's
"no vendor reference on the public page" is asserted with a planted value.

## 5. Not done, and why

* No pricing. Chargeable weight is stored; nothing turns it into money (13C).
* No frontend. The Unified Workspace (13D) is the first screen for all of this.
* Sea and UPS consolidations can be created and filled but refuse to book, by decision.
* The 0.5 kg convention below 20.5 kg awaits the vendor (V-01).

## 6. Next

13C: the pricing engine. Vendor cost estimate per consolidation (bracket or tier lookup,
piece minimums, beyond fee, surcharges with the reviewed semantics), allocation to children
(CW share; the two-thirds rule; triggers only for revenue), FX at cash-buy and sell,
per-rule markup with negative-margin refusal (OD-44), the $18/kg default with Operations
confirmation and reasoned override (OD-45), quote versions with immutable snapshots, and the
golden cases from the handoff.
