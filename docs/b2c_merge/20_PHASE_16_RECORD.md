# 20 — Phase 16 completion record: registers and staff documentation

**Date:** 2026-10-21 · **Branch:** `phase-13-b2c-merge` · **Base:** 6f684f2 (Phase 15) ·
**Migration:** none (head stays `c5e8a1f3d7b9`) · **Decision:** DEC-0217 · **Scope:** air only

This phase changes documentation, plus comments, docstrings and the reopen wording in code (§2). No rule, table, migration or screen layout changed. Nothing is
deployed, pushed or merged.

## 1. What changed

| Area | Where | What |
|---|---|---|
| Owner-decision register | `docs/OWNER_DECISIONS.json` (`verify_owner_decisions.py --write`: the generated counts in `docs/OWNER_DECISIONS.md` are unchanged, because they do not count implementation status) | Each `not_implemented` record was checked against the backend and frontend. **14 move to `default_in_force`**: OD-23, 24, 25, 27, 28, 29, 31, 32, 34, 36, 37, 38, 43, 44. **2 stay `not_implemented` with refreshed text**: OD-35 (deactivation is built, but not data export or deletion on request) and OD-53 (no beyond fee is computed). The current behaviour of **8 more** was corrected: OD-02 and OD-03 (Operations holds `tariff:read` and sees vendor cost in the Workspace, Payables and Profitability, only `financial_cost:read` stays Admin's; Marketing may export marketing segments), OD-45 (rate confirmation), OD-48 (Settings → Pricing), OD-71 (nothing is stored in the browser; the record had said the choice is remembered there), OD-72, OD-76 and OD-77 (Phases 14 and 15; finalising a newer version withdraws an unanswered offer, re-pricing alone shows the customer "updating"). That makes 24 records updated, each with its evidence files added to `cited_in`. `not_implemented` drops from 24 to 10: OD-10 to 13, OD-17 to 19, OD-22, OD-35 and OD-53, none of them built |
| OD-32 and OD-77 | OD-32's `current_implemented_behavior`, DEC-0217 | OD-77 is the newer answer and narrows OD-32. The only financial figures in the Customer Account are those of a quote staff sent: rate per kg, base charge, the customer's surcharges and the total before tax, in CAD. There is no invoice, payment, balance, cost, margin, exchange rate or markup |
| Owner questions | `19_OWNER_QUESTIONS.md` (new) | One sheet with every open question, the stand-in in force, and what changes if the owner answers otherwise |
| Staff guide | `docs/STAFF_GUIDE.md`, new part "Air masters, quotes and money" | Covers the workspace (masters, items, fees, pricing, confirm rate, finalise, send quote, master milestones, complete and cancel), quotes and acceptance, finance (GST/HST 0/5/13, VND payments at the sell rate, refunds, voids and reopening by Admin and Operations, vendor bills at the buy rate, M+7, accepted-not-invoiced), pricing settings and markups, tariffs and rate emails, milestone emails, and the Customer Account (Vietnamese first). Screen names were checked against `frontend/src/i18n/en.js` and the account catalogues |
| Plan and index | `16_REMAINING_WORK_PLAN.md`, `00_README.md` | Phase 16 is marked done, and rows are added for records 19 and 20 |

## 2. Corrected in Phase 16 (reopen wording, OD-69)

Texts that predated OD-69 now say Admin or Operations may reopen a month: the Month close note
(`finance.periodsNote` in `i18n/en.js` and `vi.js`), the refusal messages in
`finance_service.py`, its module docstring (now also GST/HST 0/5/13 per OD-64, VND payments
at the sell rate and VND bills at the buy rate per OD-73) and a comment in `FinancePage.jsx`.
The rules were already right (`financial:adjust` is held by Operations); only the wording
changed.

Independent review fixes to this phase's documents: D-09 is charged at 20,000 VND/kg on the
whole carton, priced and not flagged; D-07's printed bracket is used and nothing flags it;
with no Air Express default, every Air Express rate needs a typed reason; Complete master is
checked by the server for booked status only.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,188 passed, 1 skipped; 2 failed, the known environmental pair |
| ruff, eslint, vitest, build | clean; vitest 731 passed; built |
| Playwright (run alone) | 316 passed |
| Alembic | head `c5e8a1f3d7b9` (no migration), check clean, round trip |
| Verifiers | every check passed |

Independent reviewer: six accuracy findings (D-07/D-09 stand-ins, Operations' cost visibility,
reopen wording, OD-77 wording, Air Express reason) all corrected.
