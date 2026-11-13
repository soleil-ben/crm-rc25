# 12 — Phase 13E completion record: finance

**Date:** 2026-10-20 · **Branch:** `phase-13-b2c-merge` · **Base:** 34906d0 (Phase 13D) ·
**Migration:** `d1f6b4c8e2a9` (head), from `c9e5a3b7d2f8` · **Decisions:** DEC-0201 to
DEC-0207 · **Owner decisions:** OD-64 to OD-69 · **Scope:** air only (OD-49)

Nothing is deployed, pushed or merged; no document is sent to a customer; no request goes to the
bank or the vendor; test data only. Customer credit is not enabled (owner instruction, OD-68).

## 1. What was built

| Area | Where | What it does |
|---|---|---|
| Invoices | `models/finance.py`, `services/finance_service.py`, `routes/finance.py` | Issued from a finalised quote (`INV-`), revenue lines only, payer or customer billed, one live per shipment, void with a reason; no tax while D-11 is open |
| Payments and receipts | same | CAD only, never above the balance, receipt `RCT-` per payment; refunds against a payment (Admin); the shipment's payment state follows |
| Customer documents | `schemas/finance.py`, `features/finance/PrintPages.jsx` | Invoice and receipt from allowlists; printed as "Draft for review" with tax "under review" |
| Vendor bills | same, `features/workspace/VendorBillPanel.jsx` | Per booked master, VND or CAD, beside the expected cost; reasoned variance; approval splits the bill onto shipments in exact cents, as the estimate splits it; mark paid; void (Admin) |
| Reports | `features/finance/FinancePage.jsx` | Invoices, receivables by age (CSV), payables, monthly profitability by hand-in month with matched and unmatched cost (CSV), month close |
| Periods | same | M+7 lock, late figures as next-month adjustments, close with frozen figures, Admin reopen with a reason |
| Workspace | `InvoiceLink.jsx`, `CustomerCard.jsx`, `WorkspaceListPage.jsx` | "Issue invoice" on a finalised quote; remove a customer from an open master; masters paged (13D gaps) |
| Robustness | `core/db.py`, `pricing_service.py` | Settings reads no longer write; heavy writes re-run whole on a SQLite lock (found by the live run) |

## 2. Trying it

As in `11_PHASE_13D_RECORD.md` §2 (rebuild the demo with `--reset`). Then on master
`MST-000001`: price, confirm and finalise a customer's quote → **Issue invoice** → open it →
record a payment → print the receipt; **Book with vendor** → **Enter bill (start from the
estimate)** → save → approve; then **Finance** for receivables, payables, profitability and month
close. Operations (`ops@demo.example.com`) does all of it except refunds, voids and reopening a
month, which need Admin (`admin@demo.example.com`, same password).

## 3. Evidence

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check` (backend and scripts) | pass |
| Backend | full run **3,819 passed, 3 failed** (1,216 s). Two are the known environmental pair (`test_e2e_safety.py`, `test_incident_cleanup.py`: this worktree lacks the git-ignored development databases). The third was a real catch: the schema vocabulary guard found vendor-bill fields in `schemas/finance.py`; fixed by moving them to `schemas/vendor_bills.py` (DEC-0207), then the affected suites re-run green (tariff, finance, quotes, permissions, privacy, migrations: 1,024 passed). New: `test_finance.py` (19, incl. review regressions), `test_finance_golden.py` (31, independent tester), `test_migrations_phase13e.py` (3) |
| `eslint .` | pass |
| Frontend unit | **577 passed**, 41 files; new `tests/finance.test.jsx` (10, independent tester) |
| `vite build` | pass |
| Playwright, `npm run e2e` | **307 passed**, 11.5 minutes, after one fix (finance tables made keyboard-scrollable at 375 px, DEC-0207); new `staffFinance.spec.js` (master → quote → invoice → payment → receipt → book → vendor bill → approve → profitability) and `/finance` accessibility audits |
| Alembic, disposable database | pass: up, check, 1 down, 1 up; head `d1f6b4c8e2a9` |
| Verifiers | `verify_decision_log.py` and `verify_owner_decisions.py` pass |
| Live walk-through on the demo database | quote → invoice INV-000001 → payment RCT-000001 → printed invoice and receipt → book → vendor bill VB-000001 → approve → profitability; it found and fixed a SQLite lock on fresh databases and a whole-bill-against-one-customer margin (DEC-0202, DEC-0204) |
| Independent review | 10 findings (4 significant); all applied with regression tests (DEC-0206) |

## 4. Open for the owner

OD-64 (tax, invoice wording, company details, numbering — blocks sending real invoices),
OD-65 (payment terms), OD-66 (VND customer payments), OD-67 (which day's rate converts a VND
vendor bill), OD-69 (who may refund, void and reopen). Each has a safe interim behaviour in
force. Still open from earlier: OD-48 ($18/kg and 2/3), markups (OD-44 policy values), the
pharmaceutical weight basis (V-20).

## 5. Owner answers of 2026-10-20

OD-64, OD-65, OD-66, OD-67, OD-69 and OD-48 were answered and are in force (DEC-0208,
`PROJECT_STATUS.md` §50): GST/HST per invoice, company details on documents, due on issue, VND
payments at the selling rate and VND bills at the middle rate of the invoice or bill date, and
Operations may refund, void and reopen. Section 4 above is kept as the record of what was open.
