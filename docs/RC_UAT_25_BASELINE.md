# RC-UAT-25 — the release candidate frozen for UAT of Ben's live UAT fixes of 2026-10-25

**Identifier:** RC-UAT-25 · **Frozen:** 2026-10-25 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `bccbddf` (`bccbddfd9551bbe7b360b05a93175f28b72430c4`), the application commit of
the RC-UAT-25 fix pack · **Supersedes:** RC-UAT-24, measured at `f4a04a3`
**Machine-readable:** `docs/RC_UAT_25_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-24 listed are unchanged.

## 1. Why RC-UAT-24 was superseded

The RC-UAT-25 fix pack (`PROJECT_STATUS.md` §65, DEC-0240 to DEC-0247, OD-113, record
`docs/b2c_merge/29_BUILD_RC25_RECORD.md`, status page `docs/b2c_merge/BUILD_STATUS.md`) fixed the
eight findings of Ben's live UAT of 2026-10-25. It changed what a tester sees, added four staff
routes and a migration with two new tables.

| Category | Changed |
|---|---|
| Screens | A red `*` beside each required label instead of "(required)", staff portal and Customer Account, English and Vietnamese; "Optional" under the control in the Customer Account (DEC-0240). The booking's declared value currency is a list (—, CAD, VND) (DEC-0241). The recipient card offers the customer's saved addresses (DEC-0242). "Sign-in and security" shows the sign-in email read only; an Admin changes it with **Change sign-in email** on the staff account screen (DEC-0243). "Received at warehouse" / "Đã nhận hàng tại kho" replaces "Received at Solaris" (DEC-0244). **Edit** on each live, staff-entered timeline event, published or not (DEC-0245). The blank Financials tab fixed at its cause; every shipment tab in an error boundary (DEC-0246). A **Quote and invoice** card on the Financials tab and a **Quote & invoice** header button (DEC-0247) |
| Routes | **277** (273 at RC-UAT-24): staff **246** (customer-account review set **22**), Customer Account 26 (mutations 18), public 2, other 3. Added, all staff: `POST /customer-account/identities/{account_reference}/sign-in-email`, `POST /shipments/{shipment_id}/events/edit`, `GET /shipments/{shipment_id}/event-revisions`, `GET /shipments/{shipment_id}/financial-summary`. None removed: the customer's three email-change routes stay mounted and refuse (`POST /account/email/change` answers 403 before reading the body; an outstanding link is refused and its request closed) |
| Public contract | `PublicTrackingResult` 25, `AccountShipmentDetail` 26, list item 18, `AccountQuoteDetail` 18 — unchanged |
| Staff response schemas | Pydantic models under `app`: 330 at `f4a04a3`, **337** at `bccbddf`. Removed: `EmailChangeRequest` (the withdrawn self-service body). Added: `IdentitySignInEmailChangeRequest` 3, `ShipmentFinancialSummaryOut` 12 with `SummaryMasterOut` 4, `SummaryQuoteOut` 8, `SummaryDraftOut` 3, `SummaryInvoiceOut` 7, `EventEditIn` 11, `EventRevisionOut` 11. Changed: `IdentityStatusOut` 13 → 14 (`can_change_sign_in_email`). Every other model has the same field set. `GET /shipments/meta` (a plain dict) gains `declared_value_currencies`. `QuoteDocumentOut` 21, `InvoiceDocumentOut` 34, `InvoiceDraftOut` 46 unchanged |
| Permissions | 55, unchanged (the same set); the new routes reuse `customer_account:review` + `customer_account:deactivate`, `tracking:write`, `shipment:read` and `financial:read` |
| Schema | **Migration** `a5c7e9b1d3f6` (new Alembic head; revises `e7a9c1d3f5b6`): two new tables, `customer_account_email_changes` and `shipment_event_revisions`; nothing existing altered |
| UAT seed | Nothing new |
| Packaging | Unchanged: `uat_package` derives `RC-UAT-<N>` and the application commit from the newest `docs/RC_UAT_<N>_BASELINE.json` |
| Dependencies | None. Both lock digests carried from RC-UAT-24 (no change between `f4a04a3` and `bccbddf`) |
| UAT packs | `AIR_UAT_PACK.md` 96 → **104** (`UAT-BLD-26` to `-33`; `UAT-BLD-09` rewritten for the Admin change, `UAT-BLD-10` withdrawn with its heading kept). `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-24's files are unchanged. Against this tree they drift on **the Alembic head only**
(`e7a9c1d3f5b6` recorded, `a5c7e9b1d3f6` measured): the fix pack added no dependency and no public
tracking field, and none of the ten checks hashes application code or counts routes, so the route
and screen changes above do not show in the drift report.

## 2. Evidence

From the fix pack's gates on the application tree (`29_BUILD_RC25_RECORD.md` §2):

| Gate | Result |
|---|---|
| ruff | clean (399 files formatted) |
| Backend, full | **5,055 passed**, 1 skipped, 0 failed, in eleven foreground chunks covering all 164 test files; new `test_rc25_*.py` files (five); AS-44 to AS-57 superseded |
| eslint, vitest, vite build | clean; **892 passed**; built |
| Playwright | **328 passed** — one full run on port 5173 on the integrated tree (14.1 min); no second run needed |
| Alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database — head `a5c7e9b1d3f6`, no new upgrade operations detected |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_24_BASELINE.json` | 1 of 10 drifted: the Alembic head (see §1) |
| `verify_uat_blank.py` | pass (49 / 60 / 104) |
| `verify_decision_log.py` | pass (247 records; the next free decision number is 0248) |
| `verify_owner_decisions.py` | pass (113 recorded, 91 answered, 22 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process over git archives (no database opened); the same walker over `f4a04a3` reproduces RC-UAT-24's 273 / 242 / 26 / 18 / 21 / 2 / 3 and 55, with the route table and the model field sets identical to those recorded at the RC-UAT-24 freeze |
| Alembic head | Read from the migration scripts of git archives of `f4a04a3` (`e7a9c1d3f5b6`) and `bccbddf` (`a5c7e9b1d3f6`), no database |

## 3. Counts

| | RC-UAT-24 | RC-UAT-25 |
|---|---:|---:|
| Backend tests | 4,940 | **5,055** passed (+1 skipped) |
| Frontend unit tests | 844 | **892** |
| Playwright tests | 326 (once) | **328** (once) |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 273 | **277** |
| Staff API / customer-account review set | 242 / 21 | **246 / 22** |
| Permissions | 55 | 55 |
| Public tracking contract fields | 25 | 25 |
| Customer Account detail / list item / quote fields | 26 / 18 / 18 | 26 / 18 / 18 |
| Staff quote document fields (not in the checked set) | 21 | 21 |
| Pydantic models under `app` (not in the checked set) | 330 | **337** |
| Alembic head | `e7a9c1d3f5b6` | **`a5c7e9b1d3f6`** |
| UAT cases: staff / Customer Account / air | 49 / 60 / 96 | 49 / 60 / **104** |
| Owner decisions recorded (open) | 112 (22) | **113 (22)** |
| Decision log records | 239 | **247** |
| Supported Python (UAT) | 3.11 to 3.14 | 3.11 to 3.14 |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* `test_phase14_golden.py::test_document_deep_scan_is_customer_safe` failed once in the RC-UAT-22
  build's backend run and passed on the immediate rerun; the leak list was not captured, so the
  cause is not known (`26_BUILD_RC22_RECORD.md` §3). It did not fail in the RC-UAT-23 run (4,936
  passed), the RC-UAT-24 run (4,940 passed) or the RC-UAT-25 run (5,055 passed, 0 failed); it
  stays a known intermittent until explained. If it recurs, the assertion message names the field.
* B-13 is built but partly open: whether reinstatement should instead be refused outright after
  a merge (`19_OWNER_QUESTIONS.md` §0000); the re-link and close choices are stand-ins B-15 to B-20.
* **RC25-C1 — the exact currency Ben typed on shipment 71 is unknown.** His database was not
  opened, by rule. Every value that is not three letters reproduced the blank page and is now
  refused; a bad code already stored is not rewritten (RC25-C2) and now shows as entered with a
  warning, for staff to correct in the form. If shipment 71 shows a normal code, the error
  boundary prints the browser's error on the page: send it.
* The quote GST/HST wording is confirmed (OD-109, 2026-10-24); domestic shipments cannot be
  quoted on screen (P-10); the builds' stand-ins A-1 to A-14, B-1 to B-20 and D-1 to D-12 in
  `19_OWNER_QUESTIONS.md` §0000 (B-3, B-7 and B-11 email parts, B-12 and B-14 no longer apply,
  DEC-0243), the remaining invoice stand-ins of I-1 to I-13 in §00000, R-1 to R-14 in §000, and
  RC-UAT-25's RC25-A1 to A8, RC25-B1 to B13 and RC25-C1 to C7 in §000000.
* Retention deletion is built but **off**; periods undecided (OD-01, OD-36). Testers only dry-run it.
* Not started; Ben: skip for now (OD-112, OD-113): returns (OD-22), staff MFA (OD-17), production
  email (OD-34), provider sync (OD-21).
* Python 3.15 waits for the pinned packages (P-8); browser Back from an unsaved invoice draft is
  not intercepted (F-9).
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* `docs/PRODUCT_SPEC.md` still says "Received at Solaris" among the Phase 2–3 state names (a
  historical specification, left as written).
* Unchanged from RC-UAT-24: see `RC_UAT_24_BASELINE.md` §4.

## 5. What the lead runs after committing

Done: application and tests committed as `bccbddf`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `f4a04a3` (RC-UAT-24), or do not merge `fix/owner-answers-rc17` past `9888196`. The
fix pack added no dependency and one migration, `a5c7e9b1d3f6`, whose downgrade drops the two new
tables (`customer_account_email_changes`, `shipment_event_revisions`) and their history. A UAT
database is disposable: rebuild it from the RC-UAT-24 checkout with `uat_env.py --reset` rather
than downgrade one in place.
