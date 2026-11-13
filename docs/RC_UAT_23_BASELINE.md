# RC-UAT-23 — the release candidate frozen for UAT of the invoice build of 2026-10-24

**Identifier:** RC-UAT-23 · **Frozen:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `3151095` (`3151095458910c77d3aa2c5942ca86a9c07eb6e8`), the application commit of
the RC-UAT-23 build · **Supersedes:** RC-UAT-22, measured at `61f5c22`
**Machine-readable:** `docs/RC_UAT_23_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-22 listed are unchanged.

## 1. Why RC-UAT-22 was superseded

The RC-UAT-23 build (`PROJECT_STATUS.md` §63, DEC-0235, OD-111, OD-109 answered, record
`docs/b2c_merge/27_BUILD_RC23_RECORD.md`, status page `docs/b2c_merge/BUILD_STATUS.md`) made
invoices follow the Solaris Invoicing desk. It changed what a tester sees.

| Category | Changed |
|---|---|
| Screens | Invoices follow the Solaris Invoicing desk (Ben, 2026-10-24): domestic courier lines back GST/HST out **per line** at the destination province's rate (net = round_half_up(gross ÷ (1 + r), 2), tax on the net, the net nudged by the cent; Rate = net ÷ qty to 4 dp); international Air Freight is **zero-rated**; issued invoices print each line at its net with a Tax column (Zero-rated · GST · HST ON · HST 14% · HST 15%) and summary rows (GST @ 0% · GST @ 5% · HST ON @ 13% · HST @ 14% · HST @ 15%), the total still the all-in total. The draft editor shows **As the invoice will show it**; the invoice detail and print pages show Qty, Rate, Amount, Tax and the summary. Invoice PDFs are English only, without accents (I-1), with the **Solaris Express Inc.** company block, Terms: Due on receipt, CAD, the E-transfer and BMO wire lines and the desk's footer; receipts and the printable quote carry the new name, address and email. Quotes keep their inclusive wording (OD-109, confirmed); the manual **Issue invoice** keeps tax added on top (I-2); invoices issued before are untouched (I-4); refunds and voids unchanged. Stand-ins I-1 to I-13 (`19_OWNER_QUESTIONS.md` §00000) |
| Routes | **273**, unchanged: staff 242 (customer-account review set 21), Customer Account 26 (mutations 18), public 2, other 3. The route tables at `61f5c22` and `3151095` are identical; existing finance and invoice-draft routes return more |
| Public contract | `PublicTrackingResult` 25, `AccountShipmentDetail` 26, list item 18, `AccountQuoteDetail` 18 — unchanged |
| Staff response schemas | Optional fields added, none removed (DEC-0235): the quote document `QuoteDocumentOut` 20 → **21** (`company_email`; its exact allowlist is AS-43); `InvoiceDocumentOut` 28 → **34** (`company_email`, `tax_layout`, `tax_rows`, `payment_terms`, `payment_etransfer`, `payment_wire`); `ReceiptDocumentOut` 17 → **18** (`company_email`); `InvoiceDetailOut` 25 → **27** (`tax_layout`, `tax_rows`); `InvoiceLineOut` 5 → **9** and `InvoiceDocumentLineOut` 4 → **8** (`unit_price_cad`, `tax_cad`, `gross_cad`, `tax_code`); `InvoiceDraftOut` 43 → **46** (`tax_layout`, `tax_lines`, `tax_rows`) |
| Permissions | 55, unchanged (the same set) |
| Schema | **No migration**: Alembic head stays `d4f6b8c0e2a5`. New invoices store each line's net in `customer_invoice_lines.amount_cad` and `tax_layout: "invoicing_v1"` in `document_json` |
| UAT seed | Nothing new; `uat_smoke.py` checks domestic drafts with the per-line rule (still 22 checks) |
| Packaging | Unchanged: `uat_package` derives `RC-UAT-<N>` and the application commit from the newest `docs/RC_UAT_<N>_BASELINE.json` |
| Dependencies | None. Both lock digests carried from RC-UAT-22 (no change between `61f5c22` and `3151095`) |
| UAT packs | `AIR_UAT_PACK.md` 90 → **95** (`UAT-BLD-20` to `-24`); Ben's script step 42. `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-22's files are unchanged. Against this tree they drift on **none** of the 10 checks: the
build added no migration, no dependency and no public tracking field, and none of the ten checks
hashes application code. That is a property of what is checked (as at RC-UAT-4 → RC-UAT-5), not a
statement that nothing a tester sees moved; the screens and schemas above did.

## 2. Evidence

From the build's gates on the application tree (`27_BUILD_RC23_RECORD.md` §2):

| Gate | Result |
|---|---|
| ruff | clean (389 files formatted) |
| Backend, full | **4,936 passed**, 1 skipped, 0 failed, in nine foreground chunks; 52 new in `test_rc23_invoice_tax_math.py` and `test_rc23_invoice_layout.py`; about 20 earlier assertions changed for DEC-0235, the quote allowlist change is AS-43 |
| eslint, vitest, vite build | clean; **842 passed** (7 new in `rc23InvoiceLayout.test.jsx`); built |
| Playwright | **326 passed** — one full run on port 5173 (14.2 min), no failure, no retry |
| Alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database — head `d4f6b8c0e2a5` (unchanged), no new upgrade operations detected |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_22_BASELINE.json` | 0 of 10 drifted (all 10 match; see §1) |
| `verify_uat_blank.py` | pass (49 / 60 / 95) |
| `verify_decision_log.py` | pass (235 records; the next free decision number is 0236) |
| `verify_owner_decisions.py` | pass (111 recorded, 89 answered, 22 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process over git archives (no database opened); the same walker over `61f5c22` reproduces RC-UAT-22's 273 / 242 / 26 / 18 / 21 / 2 / 3 and 55, and the two route tables and permission sets are identical |

## 3. Counts

| | RC-UAT-22 | RC-UAT-23 |
|---|---:|---:|
| Backend tests | 4,881 | **4,936** passed (+1 skipped) |
| Frontend unit tests | 835 | **842** |
| Playwright tests | 326 (twice) | 326 (once) |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 273 | 273 |
| Permissions | 55 | 55 |
| Public tracking contract fields | 25 | 25 |
| Customer Account detail / list item / quote fields | 26 / 18 / 18 | 26 / 18 / 18 |
| Staff quote document fields (not in the checked set) | 20 | **21** |
| UAT cases: staff / Customer Account / air | 49 / 60 / 90 | 49 / 60 / **95** |
| Owner decisions recorded (open) | 110 (23) | **111 (22)** |
| Decision log records | 234 | **235** |
| Supported Python (UAT) | 3.11 to 3.14 | 3.11 to 3.14 |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* `test_phase14_golden.py::test_document_deep_scan_is_customer_safe` failed once in the RC-UAT-22
  build's backend run and passed on the immediate rerun; the leak list was not captured, so the
  cause is not known (`26_BUILD_RC22_RECORD.md` §3). It did not fail in the RC-UAT-23 run (4,936
  passed, 0 failed), which changed the documents it scans; it stays a known intermittent until
  explained. If it recurs, the assertion message names the field.
* B-13 is built but partly open: whether reinstatement should instead be refused outright after
  a merge (`19_OWNER_QUESTIONS.md` §0000); the re-link and close choices are stand-ins B-15 to B-20.
* **I-1:** invoice PDFs print every string without Vietnamese accents ("Phạm Thị Thu Trang" →
  "Pham Thi Thu Trang"); whether a customer name without accents is acceptable on a legal
  invoice is open (`27_BUILD_RC23_RECORD.md` §3).
* **I-10:** the staff Settings legal-entity name and the label sender still read "Soleil Global
  Transportation Inc."; only the invoice, receipt and quote company block changed
  (`27_BUILD_RC23_RECORD.md` §3).
* The quote GST/HST wording is confirmed (OD-109, 2026-10-24); domestic shipments cannot be
  quoted on screen (P-10); the builds' stand-ins A-1 to A-14, B-1 to B-20 and D-1 to D-12 in
  `19_OWNER_QUESTIONS.md` §0000, I-1 to I-13 in §00000, R-1 to R-14 in §000.
* Retention deletion is built but **off**; periods undecided (OD-01, OD-36). Testers only dry-run it.
* Not started, waiting for Ben: returns (OD-22), staff MFA (OD-17), production email (OD-34),
  provider sync (OD-21).
* Python 3.15 waits for the pinned packages (P-8); browser Back from an unsaved invoice draft is
  not intercepted (F-9).
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-22: see `RC_UAT_22_BASELINE.md` §4, less the quote-wording stand-in
  (OD-109, now confirmed).

## 5. What the lead runs after committing

Done: application and tests committed as `3151095`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `61f5c22` (RC-UAT-22), or do not merge `fix/owner-answers-rc17` past `ecb19b7`. The
build added no migration and no dependency, but invoices issued on it store per-line nets and
`tax_layout: "invoicing_v1"`, which RC-UAT-22 does not read: rebuild the UAT database from the
RC-UAT-22 checkout with `uat_env.py --reset` rather than keep one holding invoices issued on the
new layout.
