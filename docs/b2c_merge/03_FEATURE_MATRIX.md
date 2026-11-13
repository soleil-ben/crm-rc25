# 03 — Feature matrix: directive requirements vs this CRM, and the fate of each handoff component

Status words: **EXISTS** (built, tested, in RC-UAT-16), **PARTIAL**, **MISSING**.
Evidence is a path in this repository. Counts are from `docs/RC_UAT_16_BASELINE.md`
(3,043 backend, 538 frontend, 295 Playwright tests).

## 1. Directive requirements vs the Package

| # | Requirement (v2.0 / v2.1 / handoff) | Status | Evidence | Gap |
|---|---|---|---|---|
| A | Customer with stable ID; payer / sender / receiver distinct | PARTIAL | `models/customer.py` (`STCA-000001`, immutable, aliases on merge), address book roles sender / recipient / billing, sender and recipient snapshots on shipments | No **payer** party; ID prefix `STCA-` not `STCA-` (see `05_OPEN_DECISIONS.md` D-01) |
| B | Master (vendor booking) containing N customer shipments; packages; commodity items | PARTIAL | `shipments → shipment_packages → shipment_legs → leg_tracking_references`; `consolidation_reference` free text on a leg | No **consolidation entity** with child FK; no **commodity line items** (only `contents_description`) |
| C | Vendor COST: vendor, quote, base freight, surcharges, allocation, invoice, actual vs expected, reconciliation | MISSING | Only `shipments.shipping_cost`, `surcharges_amount` (manual), `financial_cost:read` gating, derived gross profit | The whole vendor cost model |
| D | Customer QUOTE / REVENUE: selling rate, chargeable weight, surcharges, discounts, tax, total, versions, acceptance, invoices, payments, receipts | MISSING | Manual `selling_amount`, `discount_amount`, `refund_amount`, single `payment_state` | Quote, invoice, payment, receipt entities; chargeable weight |
| E | Server-side separation: cost / profit never in customer-facing payloads | EXISTS | `schemas/public_tracking.py`, `schemas/account_shipments.py` allowlists; `tests/test_public_privacy.py`, `tests/test_account_shipment_privacy.py` scan JSON for forbidden keys **and planted values** | Extend the forbidden-key lists as cost fields are added |
| F | Public tracking on Solaris site by secure reference, not vendor number; rate limit; enumeration resistance | EXISTS | `api/public/tracking.py`; `SX-VCA-…` CSPRNG IDs (`identifier_service.py`); generic 404; 30/60 s limit; `no-store`, `noindex` | — |
| G | Customer login, My Shipments, search, detail, profile; staff approval / linking | EXISTS | `api/account/*` (15 routes), `frontend/src/account/` (14 pages), `customer_account_review.py` | Notification history screen; Vietnamese UI (OD-39 chose English first) |
| H | Normalized tracking events, manual staff events with actor / time / source / audit, dedup, out-of-order, master→child inheritance; vendor connector abstraction | EXISTS / PARTIAL | `shipment_events` (15 types → 17 states, occurred vs recorded, void with audit, fan-out to packages, no regression); adapter registry, webhook inbox with DB dedupe, job queue — **registry empty by DEC-0075** | Cross-shipment master→child inheritance needs B |
| I | Milestone notifications: email + in-app, templates EN/VI, preferences, dedup, send log, test mode | PARTIAL | 6 account-lifecycle emails, `NullEmailTransport` / `CaptureEmailTransport`, preference table with topics, public wording catalogue EN/VI | No shipment-milestone notification, send log, in-app channel, VI email bodies |
| J | Kango tariff engine, 85 surcharges, searchable fee → Add Fee, 2/3–1/3 allocation, $18/kg default with confirm, Vietcombank BUY/SELL | MISSING | zero hits for `kango`, `vietcombank` | The handoff's core; see `06_MERGE_PLAN.md` |
| K | Finance dashboard: revenue, cost, profit, margin, AR / AP, monthly, variance | PARTIAL | `dashboard_service`, 9 reports incl. gated `financial_summary`, per-customer financials, CSV exports | Margin %, AR / AP, variance, P&L need C and D |
| L | Marketing / segmentation | PARTIAL (by owner choice) | `saved_segments` builder with live counts, consent / suppression, audience CSV | Campaigns deferred by the owner; **no placeholder page needed, the real builder exists** |
| M | Staff auth, RBAC, audit, backups, secrets, deployment | EXISTS (not deployed) | argon2, sessions, CSRF, 4 roles × ~45 permissions, `audit_events`, backup / restore scripts, startup safety gates | MFA undecided (OD-17); hosting undecided (OD-10) |
| N | English / Vietnamese | PARTIAL | Staff UI and public tracking EN/VI with parity test; templates EN/VI | Account UI and emails English only |
| O | Owner approval gates, nothing live without approval | EXISTS | `docs/OWNER_DECISIONS.md` OD-20 "Deployment prohibited"; production startup refuses dev secrets | Keep |

## 2. Fate of each handoff component

| Handoff component | Decision | Why |
|---|---|---|
| Unified Calculator **workflow** (master → customers → items → fees → cost / quote → confirm → save → documents) | **BUILD in React on the Package**, as a staff feature `features/workspace/` backed by new API routes | The flow is owner-approved; the v1.5 implementation is a browser prototype with the defects in `04_ISSUE_REGISTER.md` |
| Searchable fee list → Add Fee UX | **BUILD**, same interaction | Owner decision 4 |
| `compute()` financial engine | **REWRITE server-side** as pure, tested functions; carry the rules, not the code | Rules are correct (allocation 2/3–1/3, CW share, BUY/SELL); the parser and FX handling are wrong |
| `parseRule` / `ruleMeta` regex rule parsing | **DISCARD** | Mis-prices 5 rules at 1 VND, ignores tiers, bottles, full-box scope; replace with structured rule rows from the importer |
| `kango_reference.json` / `kango_data.js` | **DISCARD as a source; keep as a regression fixture** | Faithful to the workbook but carries none of the rules; import from the workbook with provenance |
| `cost_calculator.html` (FSA zone, 0.5 kg bands, tiers, beyond, under-12 kg fee) | **Carry the algorithms as golden tests**; discard the page | Its `calc()` encodes the vendor's bracket logic correctly and is the only place the under-12 kg piece fee exists |
| `server.py` VCB watcher | **Reimplement as a Package background job** with BUY **and** SELL, history table, stale / outage states | Existing one reads BUY only and runs only while a desktop process is open |
| `index.html` shell pages (Customers, Quotes, Shipments, Batches, Finance, Reports, Settings, Allocation Studio, Smart Quotation, backup / restore) | **DISCARD** | Every one of these exists in the Package with persistence, roles, audit and tests; the shell's Shipments form cannot save |
| `localStorage` store and `restore()` | **DISCARD**; write a one-off import only if the owner has real data in a browser (none reported) | Not transactional; injection vector |
| Master prompt v1.6 owner decisions 1–15 | **ADOPT** into `docs/OWNER_DECISIONS.md` as new owner-decision records when the owner answers them | They are the business rules |
| Master prompt open decisions and the 20 workbook questions | **ADOPT** as `05_OPEN_DECISIONS.md` | Only the owner or vendor can answer them |
| v0.7 zip | **Reference only** | Approved interaction, already captured above |
| Historical v1.0 prompt, questionnaire, tracking prototype xlsx | **Reference only** | Superseded where they conflict |

## 3. Directive items the Package already contradicts, deliberately

| Directive text | Package reality | Proposed handling |
|---|---|---|
| Customer ID `STCA-XXXX` | Was `CUS-000001`; now `STCA-000001` (OD-42, DEC-0174): issued identifiers renamed by migration, former ones kept as aliases, six digits kept | Decided 2026-10-19 |
| "Marketing — navigation placeholder only" (v2.1 §10) | A working segment builder with consent-aware audience export exists | Keep what exists; do not add a placeholder page that pretends less than what is built |
| "Milestones: Shipment Received … Delivered / Collected" (v2.1 §6) | 15 event types / 17 states already approved in `CRM.md` §10, with EN/VI public wording | Map the directive's nine milestones onto the existing vocabulary; do not add a second one |
| Six-agent team with fixed roles (v2.0 §14) | Work here runs as one lead with per-task subagents and worktrees | Same discipline (independent audit, QA, no self-approval); roles are assigned per task, not per persona |
| SQLite is a prototype; "persistent transactional DB" (handoff §0.8) | SQLite WAL with hardening, online backup, documented PostgreSQL threshold (`docs/HOSTING.md`) | Unchanged; revisit at the documented threshold |
