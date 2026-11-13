# 07 — Does Product Owner Directive v2.1 make sense for this code base?

Short answer: **its principles, yes, fully; its priority order, only partly.** The
directive was written against the v1.5 prototype, where nothing customer-facing existed.
Against RC-UAT-16, most of its P1 "Customer Tracking" is already built and under UAT, so
following its order literally would spend the next phases re-building what exists while the
one thing both the handoff and the directive need — the vendor cost and pricing engine —
waits.

## Section by section

| v2.1 section | Verdict | Against this code base |
|---|---|---|
| §1 Vendor cost strictly internal; two linked records; backend enforcement, not CSS | **Already the design.** Keep | Allowlisted customer schemas and planted-value privacy scans exist; every new cost field must be added to those scans (plan 13C) |
| §2 Vendor surcharge vs customer surcharge as two perspectives; pass-through / fixed / % / waive; markup pending | **Sound; adopt the model** | Maps to `vendor_cost_lines` vs `quote_lines`. Markup is D-04. One addition the directive does not state: at SELL with 0 markup the pass-through is **below cost**, so the engine must surface fee-line margin |
| §3 Vendor portal / email as internal inputs only; rate-change review workflow; manual import acceptable first | **Agree** | Importer with versions and approval is 13A; email detection is "later" |
| §4 Tracking hosted on Solaris's site; no vendor names, links, references, costs | **Already built** | Public page keyed on `SX-…` IDs, carrier numbers are forbidden keys, generic 404s, no third-party requests. Verify, do not rebuild |
| §5 Internal vs vendor identifiers; public reference not the vendor number | **Already built** for shipments; master IDs come with 13B | `leg_tracking_references` already separates carrier references from the Solaris ID |
| §6 Portal MVP: login, My Shipments, search, timeline, notification history, profile | **Built except notification history** | 14 account pages exist; notification history is 13F |
| §7 Manual first, automation when verified | **Already the design** (DEC-0075) | Manual events with actor / time / source / audit exist; the adapter registry is deliberately empty |
| §8 Milestone notifications, email + in-app, dedup, test mode | **Missing — real work** | 13F; the capture transport and preference table already exist |
| §9 Finance second priority | **Agree it is the real build**, but see order below | 13C + 13E |
| §10 Marketing placeholder only | **Over-corrects** | A consent-aware segment builder already exists; adding a "Planned" placeholder would present *less* than what is built. Keep the existing module, add no campaigns |
| §11 Priorities P0 → P5 | **Re-sequence** (below) | |
| §12 Six named agents | **Method, not structure** | Independent audit / QA / no self-approval are kept; agents are spawned per task |
| §13 Approval policy | **Matches** `docs/OWNER_DECISIONS.md` OD-20 and the startup gates | Add "confirmed pricing-policy changes" to the approval list |
| §14 Eight acceptance tests | **Adopt all eight** | 1 and 7 pass today; 2, 3, 5, 6, 8 land with 13B–13F; 4 waits on V-19 |
| §15 Final instruction | **Agree** | — |

## Where v2.1's order would misfire

v2.1 P1 lists nine items. Seven exist today (event model, manual updates, customer-safe
projection, public page, authenticated My Shipments, data isolation, tests). Two do not:
master-to-customer inheritance (needs the consolidation entity, 13B) and the notification
queue in test mode (13F). Neither is large. Putting "P1 Tracking" first therefore means
either declaring it done after a short gap-fill, or stalling.

v2.1 P2 (tracking automation) is blocked on a fact nobody has: whether Kango offers any
authorised API or export (V-19). Nothing can be built there yet.

v2.1 P3 (Finance) presupposes vendor cost estimates, customer quotes and allocations — the
handoff's Unified Calculator — which v2.1 only mentions as "preserve existing functionality"
because it assumed v1.5 had working ones. It did not (see `04_ISSUE_REGISTER.md`).

## Recommended sequence (what `06_MERGE_PLAN.md` encodes)

1. **13A tariff + FX, 13B consolidation + items** — the foundations both tracking inheritance
   and pricing need; backend only; UAT round 13 continues untouched.
2. **13C pricing engine, 13D Unified Workspace** — the handoff's core, with golden tests.
3. **13F notifications in test mode** (closes v2.1 P1 Tests 3 and 8) — can run in parallel
   with 13D because it touches different modules.
4. **13E Finance** (v2.1 P3).
5. Automation and rate-email ingestion when the external facts arrive.

This keeps every v2.1 principle, satisfies its acceptance tests in the order the code allows,
and avoids rebuilding tracking that is already in UAT.

## Decisions the owner should confirm before coding starts

- The sequence above (or insist on v2.1's literal order).
- D-01 customer ID prefix, D-02 service taxonomy, D-04 surcharge markup handling, D-06
  confirmation roles — these shape the first schema and are cheap to decide now, expensive
  to change after data exists.
