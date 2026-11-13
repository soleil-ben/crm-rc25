# 06 — Merge plan: adding the handoff's components to this CRM

Principle: extend what exists, build what is missing, import no v1.5 code. Each phase is a
branch cut from the previous one, gated by the same checks as every earlier phase (ruff,
pytest, eslint, vitest, vite build, Alembic up/down/up, Playwright, privacy scans, RC
baseline freeze). Nothing is deployed; no real notification is sent.

## 1. Sequence

| Phase | Scope | Why this order |
|---|---|---|
| **13A — Tariff and FX foundation** (backend only) — **done 2026-10-19, `08_PHASE_13A_RECORD.md`** | Vendor entity; **tariff version** importer from the Kango workbook with provenance (file hash, sheet, row, effective date); rate brackets, FSA zones, beyond codes and rates, accessorials, piece-minimum rules, and the 85 surcharge rules as **structured rows** (basis, scope, unit price, tiers, applicability by origin / service / route, pricing status); Vietcombank CAD **BUY / TRANSFER / SELL** job with history, stale / outage states and plausibility bounds; golden tests reproducing the workbook calculator and every issue in `04_ISSUE_REGISTER.md` | Everything else prices against it; it is pure data and pure functions, so it is the safest first slice and the easiest to verify against the source file |
| **13B — Consolidation and line items** (schema) — **done 2026-10-19, `09_PHASE_13B_RECORD.md`** | **Air only (OD-43).** `service_vendor_products` (Solaris service → vendor product, per tariff version and origin); `consolidations` (vendor booking: vendor, product, reference / AWB, master actual weight, dims, divisor, master CW, cutoff / flight, state) with `consolidation_memberships` to child shipments; **payer** party on shipments; `shipment_items` (commodity lines: name, qty, unit, weight, declared value); master-level tracking events that **inherit** to active member shipments through the existing `event_service` fan-out; migrations with down-paths | The handoff's master / child model is the one structural thing the Package lacks; tracking inheritance (v2.1 Test 2) depends on it |
| **13C — Pricing engine** (backend) — **done 2026-10-19, `10_PHASE_13C_RECORD.md`** | Pure functions: `chargeable_weight`, `vendor_base_cost` (bracket / tier lookup, rounding, piece minimums, beyond), `evaluate_surcharge_rule`, `allocate_master_cost` (CW share; 2/3–1/3; multi-trigger by CW), `allocate_customer_surcharge` (triggers only), `fx_convert` (BUY for cost, SELL for revenue), `apply_markup` (per-rule markup: pass-through, fixed CAD or percent, default pass-through; a negative-margin line refuses to finalise without a reason, OD-44), `price_customer` ($18/kg default, Operations confirms and overrides with a reason, OD-45), `profit`. Sea products stay unmapped and unpriced until the owner enables them. **Quote** entity with versions and immutable snapshot (tariff version, FX snapshot, divisor, rule ids); **vendor cost estimate** entity per consolidation with per-child allocations. Routes under `/api/v1/consolidations/…` and `/api/v1/quotes/…`, permission-gated; **privacy scans extended** with every new cost / profit field name and planted values | Finance and the workspace both consume it; golden cases SC-01…SC-10 (handoff §11) and directive Test C / Test 5 live here |
| **13D — Unified Workspace UI** (React, staff portal) — **done 2026-10-20, `11_PHASE_13D_RECORD.md`** | `features/workspace/`: master header → customer cards → items → **searchable fee list → applicable kg / units → Add Fee** → cost / quote / profit panels → Confirm Selling Rate → Finish customer / add next → save → customer document (revenue only). Reuses existing customer search, package model, address book. Vietnamese and English strings with the parity test | The owner-approved interaction, on top of a real backend |
| **13E — Finance** — **done 2026-10-20, `12_PHASE_13E_RECORD.md`** | Customer invoices (numbering, tax status per D-11), payments (manual recording, partial, outstanding, refund), vendor invoices and **reconciliation** (expected vs actual per consolidation, variance, reasoned corrections, re-allocation), AR / AP, margin %, monthly profitability, M+7 lock; reports and CSV | v2.1 P3 and handoff phase 4 |
| **13F — Milestone notifications (test mode) and account Vietnamese** — **done 2026-10-20, `13_PHASE_13F_RECORD.md`** | `notification_outbox` with dedup key (shipment, event, template version), templates EN/VI, send log, retry, in-app notification history for the Customer Account, **Null / Capture transports only**; account UI Vietnamese if D-13 lifts OD-39 | v2.1 P1 remainder and Test 3 / Test 8 |
| **13G — Customer quote acceptance** (OD-77, D-08) — **done 2026-10-20, `14_PHASE_13G_RECORD.md`** | Staff **send** a finalised quote (version frozen); the linked customer sees it in the Customer Account (Solaris service name, charges, total; never vendor cost, rate or markup) and **accepts** or declines it; accepted = frozen, audited; a re-priced quote supersedes an unanswered sent one; quote-sent email through the test-capture seam; staff see the answer in the workspace | Owner answered D-08 on 2026-10-20 |
| **13H — Vendor rate-email intake** (OD-76, D-12) — **done 2026-10-20, `15_PHASE_13H_RECORD.md`** | A rate email (an `.eml` with the workbook attached) becomes a **pending tariff version** with provenance (message id, sender, received time, attachment hash); the existing importer parses it; a diff against the active version; **only the designated approver** (Ben, a setting) activates it; nothing is activated automatically. **Stand-in:** no live mailbox connection -- emails are dropped into an intake folder or uploaded by staff, because connecting a real mailbox needs credentials and a provider decision | Owner answered D-12 on 2026-10-20 |
| **Not planned** | QuickBooks export (OD-78: none); tracking automation (OD-63: no vendor API yet) | Owner decisions |

## 2. Data model additions (summary)

```
vendors ─< tariff_versions ─< rate_brackets, zone_fsas, beyond_codes, beyond_rates,
                              accessorials, piece_minimum_rules, surcharge_rules ─< surcharge_rule_tiers
fx_rates (bank, currency, buy, transfer, sell, bank_published_at, retrieved_at, status)
consolidations ─< consolidation_memberships >─ shipments ─< shipment_items
consolidations ─< vendor_cost_estimates ─< vendor_cost_lines (base, surcharge, accessorial) ─< cost_allocations >─ shipments
shipments ─< quotes ─< quote_versions ─< quote_lines ; quote_versions.snapshot_json
shipments ─< invoices ─< invoice_lines ; invoices ─< payments
consolidations ─< vendor_invoices ─< vendor_invoice_lines ; reconciliation_variances
notification_outbox, notification_deliveries
```

Everything customer-facing keeps reading from the existing allowlisted schemas; the new
tables are reachable only through staff routes gated by `financial:read`,
`financial_cost:read` and new `pricing:write`, `pricing:confirm` permissions.

## 3. Acceptance tests carried into the plan

| Source | Test | Phase |
|---|---|---|
| Handoff §11 | SC-01…SC-10 golden financial cases (21 kg / 3-6-12 kg master, single and multiple triggers, direct fee, $18 confirm, FX BUY / SELL) | 13C |
| v2.0 §18 | A lifecycle, B 10 items / 4 surcharges, C three customers per master, D vendor quote → invoice variance, G / H privacy, I payments, L FX, M dashboard reconciliation | 13C–13E |
| v2.1 §14 | 1 vendor confidentiality (exists), 2 shared master inheritance (13B), 3 manual tracking + queued notification (13F), 4 mocked vendor connector (later), 5 document security (13C/D), 6 reconciliation (13E), 7 URL privacy (exists), 8 duplicate milestone → one event, one notification (13F) | as noted |
| Issue register | one golden test per H-xx row | 13A / 13C |

## 4. What does not change

Public tracking, Customer Account, staff auth and roles, audit, backups, the integration
seam, the UAT packs and the RC freeze process all continue as they are. UAT round 13 on
RC-UAT-16 can run in parallel with 13A, which touches no existing route.

## 5. Working method

One lead session; independent subagents for audit and review of each phase; each phase in
its own worktree and branch; no change merged without its tests and an independent read;
decisions appended to `docs/DECISIONS.md` (DEC-0167 onward) and owner questions to
`docs/OWNER_DECISIONS.md` as new records when the owner answers them.
