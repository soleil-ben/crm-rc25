# 21 — Phase 17 completion record: UAT readiness

**Date:** 2026-10-21 · **Branch:** `phase-13-b2c-merge` · **Base:** 1089257 (Phase 16) ·
**Migration:** none (head stays `c5e8a1f3d7b9`) · **Decision:** DEC-0218 · **Baseline:**
RC-UAT-17 · **Scope:** air only, test data only

This phase changes scripts, documents and tests, plus the application fixes the UAT dry run
and the independent review asked for (§1, last rows). No table, migration, route or
dependency changed. Nothing is deployed, pushed or merged.

## 1. What changed

| Area | Where | What |
|---|---|---|
| UAT air dataset | `scripts/uat_seed_phase13.py` (new), called by `scripts/uat_env.py --reset` | Through the services and the HTTP routes (never rows): the sanitized Kango tariff, active; demo Vietcombank readings (closed month and now, `demo://fixture`); pricing settings saved by the demo Admin (CAD 18.00, 2 % default markup); tariff approvers = the demo Admin only, allowed sender `vendor-rates.example.com`; customers A1–A4 on `example.com`; five air masters `UAT-AWB-OPEN` / `-BOOKED` / `-TRANSIT` / `-DELIVERED` / `-CLOSED`; a quote awaiting the customer; two accepted in the Customer Account; invoices at GST/HST 0, 5, 13 %; a part payment; a VND payment and a refund; two vendor bills, one with a reconciled variance; a closed month; two linked Customer Accounts (A1 Vietnamese, A2 English; A2 opted out of "in transit") registered, verified and linked by Operations through the real routes; milestone and quote emails in `data/uat/account_mail`; two `.eml` rate emails generated at seed time from the sanitized fixture and read by the intake worker (a draft with three changed prices awaiting the approver; one held from an unknown sender), copies in `data/uat/tariff_intake/samples/`. Idempotent, deterministic apart from dates, and guarded |
| UAT environment | `scripts/uat_env.py` | Runs the air seed with the capture transport and `TARIFF_INTAKE_DIR` inside `data/uat/`; 20 new `--check` categories; `--refresh-fx` (demo reading, no network); `--reset` / `--destroy` also clear the intake folder (confined to the UAT directory); prints the two Customer Account sign-ins |
| Tests | `backend/tests/test_uat_seed_phase13.py` (new, 12) | A full build into a temporary UAT directory: every category present, masters at their stages, quotes / invoices / payments / bills / closed month as named, accounts and the opt-out, the two rate emails, only reserved addresses and the demo Admin as approver, a second run adds nothing, `--refresh-fx`; refusals of a non-UAT database, folders outside the database's directory, production, and an intake folder outside the UAT directory |
| UAT cases | `docs/UAT/AIR_UAT_PACK.md` (new, 36 cases) | `UAT-WSQ` 7 (workspace pricing and quotes), `UAT-QAC` 4 (quote acceptance in the account), `UAT-FIN` 8 (invoices and GST/HST, CAD and VND payments, refunds and voids, vendor bills and reconciliation, receivables/payables/profitability, M+7 and reopen, permissions), `UAT-PRC` 4 (pricing settings and markup), `UAT-TAR` 5 (tariff browser, intake, release, approval, approvers), `UAT-MLS` 4 (milestone emails and choices), `UAT-VIA` 4 (Vietnamese-first account). Each names its role, the seeded data, steps, expected result, privacy note and evidence; a blocked-by table from `19_OWNER_QUESTIONS.md` |
| Verifier | `scripts/verify_uat_blank.py` | Checks the third pack (36 by DEC-0218) the way it checks the other two |
| Stale text | `CUSTOMER_ACCOUNT_UAT_PACK.md`, `ENVIRONMENT.md`, `README.md`, `REVIEW_customer_account_copy.md`, `REVIEW_vietnamese_ui.md` | "English only" replaced by Vietnamese first (OD-71); `CA-XP-03` rewritten (same identifier, same count of 60); the `CA-PRF` banner says the screens exist; the seeded accounts are named as the air pack's only |
| Run documents | `docs/UAT/HOW_TO_RUN.md` (new), `docs/UAT/UAT_SCRIPT_FOR_BEN.md` (new), `ENVIRONMENT.md` | Build, reset, start (PowerShell), sign-ins, the capture folder, the `--once` workers (notification, tariff intake; the FX worker is not run in UAT because it calls the bank), how the owner adds himself as an approver; a 60–90 minute guided walk-through for the owner |
| Counts | `UAT_SUMMARY.md`, `ROLE_MERGE_COVERAGE_MAP.md` §8, `UAT_CASES.md` blocked table | The air pack's 36 rows; the role mapping; a pointer to the air pack's blocked table |
| Baseline | `docs/RC_UAT_17_BASELINE.{json,md}`, `scripts/verify_rc_baseline.py` | RC-UAT-17 in force, measured at the application commit `1089257`; RC-UAT-16 added to the superseded list |
| Registers | `docs/DECISIONS.md` (DEC-0218), `PROJECT_STATUS.md` §57, `00_README.md`, `16_REMAINING_WORK_PLAN.md` | Phase 17 recorded and marked done |
| Fix: master milestones | `consolidation_service._already_inherited` | A published milestone repeats only a published one: unpublished then published records the published event and queues one email (UAT-MLS-04). Tests: `test_phase17_fixes.py` |
| Fix: account session touch | `app/api/account/deps.py` (`keep_session_alive`), `app/api/account/quotes.py` | The last-seen touch is committed on its own after the unchanged expiry, idle, revocation and CSRF checks, best effort for every account route; a lock skips it, any other error propagates. The quotes route's own workaround is removed. Tests simulate a lock on the touch |
| Fix: invoice after a closed offer | `finance_service.issue_invoice` / `closed_offer_state`, `InvoiceLink.jsx`, `en.js`, `vi.js` | Still allowed (stand-in); the workspace warns before **Issue invoice**, naming the offer state, and the issue audit records `offer_state`. Tests: backend and `invoiceOfferWarning.test.jsx` |
| Fix: no real address in UAT | `tariff_intake_service.update_settings` (service-only `mailbox_address`; first-save audit records "owner default"), the seed | The UAT intake mailbox is `tariffs@demo.example.com`; the seed test scans every text column for the company domain; street addresses are plainly fictitious |
| Docs from the dry run | `AIR_UAT_PACK.md`, `UAT_SCRIPT_FOR_BEN.md`, `ENVIRONMENT.md`, `HOW_TO_RUN.md`, `uat_env.py` | DELIVERED dated in the current month; `--check` counts only the air shipments' emails; partial build → `--reset`; `--path` only directly in `data/uat/`; `--refresh-fx` for FIN-05; receipt `RCT-000003`; Payables wording; TAR-04 order; Admin opens Audit access; account changes audited as "system" with the account reference; staff wording on the departure; the Quotes list shows the Solaris ID; WSQ-05 says what booking freezes; `CORS_ORIGINS` and `TRACKING_BASE_URL` for other ports; `npm run dev` rather than `npx` |

## 2. The dataset, as built

`uat_env.py --reset` on 2026-10-21, then `--check` (every required category present):

| Item | Built |
|---|---|
| Masters | `MST-000001` UAT-AWB-CLOSED completed · `MST-000002` UAT-AWB-OPEN open · `MST-000003` UAT-AWB-BOOKED booked · `MST-000004` UAT-AWB-TRANSIT booked · `MST-000005` UAT-AWB-DELIVERED completed |
| Quote offers | 1 sent (A1, `UAT-AIR-A1-2`), 2 accepted (A1 `UAT-AIR-A1-1`, A2 `UAT-AIR-A2-1`); 1 accepted, not invoiced (A2) |
| Invoices | `INV-000001` 0 % CAD 90.00 paid (closed month) · `INV-000002` 13 % CAD 122.04 issued · `INV-000003` 0 % CAD 90.00 part-paid (CAD 50.00) · `INV-000004` 5 % CAD 132.30, paid in VND, CAD 10.00 refunded |
| Vendor bills | `UAT-BILL-CLOSED` CAD 84.70, no variance, paid · `UAT-BILL-DELIVERED` VND 3,510,699.20 (CAD 196.28), variance +CAD 19.57 with a reason, paid |
| Month | 2026-09 closed |
| Accounts | A1 `CA-000001` (vi), A2 `CA-000002` (en), both linked; A2 "in transit" off |
| Milestone emails | 18 sent (11 for the air masters — the figure `--check` reports — and 7 queued earlier by the base seed's published milestones), 1 skipped (A2, opted out) |
| Tariffs | 1 active, 1 draft from the allowed sender (three prices changed), 1 held (unknown sender) |
| Exchange rates | 2 demo readings (2026-09 and now) |

Identifiers are those of a fresh reset; dates follow the day of the reset.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,213 passed, 1 skipped; 1 failed, the known environmental `test_e2e_safety` (the other environmental test passed this run). A first run caught the account statement-count test: the session touch now writes at most once a minute (fixed, rerun) |
| ruff check / format | clean (331 files) |
| eslint, vitest | clean; 734 passed |
| vite build | built |
| Playwright (run alone) | 316 passed (one run had a flaky account verification step under load; the spec passed alone 4/4 and the full rerun passed 316) |
| Alembic | head `c5e8a1f3d7b9` (no migration), check clean, round trip |
| Verifiers | decision log, owner decisions, UAT blank (49/60/36), RC baseline 10/10 |
| UAT dry run | 34 of 36 air cases executed by an independent tester; two product defects found and fixed (P1, P2), doc mismatches corrected |

Application commit: `911965b`.

## 4. Open questions

Unchanged from `19_OWNER_QUESTIONS.md`; none blocks UAT, and `AIR_UAT_PACK.md` tests the
stand-in for each:

1. D-07 — the Express zone 2 price drop at 16 kg (stand-in: used as printed).
2. D-09 — HCM meat / egg / dairy / honey, 20,000 or 10,000 VND/kg (stand-in: 20,000).
3. V-20 — other per-kg surcharges on the item's own kg or the whole carton (stand-in: carton).
4. A default Air Express selling rate (stand-in: none; typed with a reason).
5. Vendor surcharge names on customer documents (stand-in: printed as the vendor names them).
6. A native review of the Vietnamese wording (stand-in: machine-checked only).
7. The account's standard update sentences (stand-in: the standard sentence, staff text beneath).
8. Invoice automatically on acceptance (stand-in: no; staff are prompted).
9. Quote expiry (stand-in: none).
10. Sending while a newer draft is open (stand-in: refused).
11. The vendor rate mailbox, Microsoft 365 or Gmail (stand-in: upload or intake folder).
12. Reminder emails for approvers or customers (stand-in: none; a badge).
13. The register's open decisions OD-01 to OD-22 and the production-only OD-34 / OD-37, as
    listed in sheet 19 §4.

## 5. What the lead must still do

* Done by the lead: application committed as `911965b`, the SHA filled in, gates run on that
  tree (§3), documents and scripts committed on top.
* Optional: run the backend suite in the main checkout to clear the environmental failure.
* Decide whether items and fee lines should freeze on a booked master (today they do not;
  `UAT-WSQ-05` documents it).
