# RC-UAT-24 — the release candidate frozen for UAT of Ben's evening answers of 2026-10-24

**Identifier:** RC-UAT-24 · **Frozen:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `f4a04a3` (`f4a04a337350691a9241c5fb0554123b5e96a722`), the application commit of
the RC-UAT-24 build · **Supersedes:** RC-UAT-23, measured at `3151095`
**Machine-readable:** `docs/RC_UAT_24_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-23 listed are unchanged.

## 1. Why RC-UAT-23 was superseded

The RC-UAT-24 build (`PROJECT_STATUS.md` §64, DEC-0236 to DEC-0239, OD-112, record
`docs/b2c_merge/28_BUILD_RC24_RECORD.md`, status page `docs/b2c_merge/BUILD_STATUS.md`) applied
Ben's evening answers to the RC-UAT-23 invoice stand-ins. It changed what a tester sees and added
a data-only migration.

| Category | Changed |
|---|---|
| Screens | **Solaris Express Inc.** is the legal entity on Settings (Brand and tracking → Legal entity), the staff portal's login footer (English and Vietnamese) and the demo label sender (I-10, DEC-0236). The draft invoice editor's included-tax sentence reads "Tax included in the price: subtotal before tax …, HST ON @ 13% …, total …" with the invoice's summary labels (I-11, DEC-0239); quote wording unchanged. I-1 (English-only invoice PDF, names without accents) and I-12 (the cent nudge) confirmed as built (DEC-0237, DEC-0238). Parent-company references and historical records unchanged on purpose. The held items stay unbuilt (OD-112) |
| Routes | **273**, unchanged: staff 242 (customer-account review set 21), Customer Account 26 (mutations 18), public 2, other 3. The route tables at `3151095` and `f4a04a3` are identical |
| Public contract | `PublicTrackingResult` 25, `AccountShipmentDetail` 26, list item 18, `AccountQuoteDetail` 18 — unchanged |
| Staff response schemas | None changed: every Pydantic model under `app` (330 at each commit) has the same field set at `3151095` and `f4a04a3`; `QuoteDocumentOut` 21, `InvoiceDocumentOut` 34, `InvoiceDraftOut` 46 |
| Permissions | 55, unchanged (the same set) |
| Schema | **Data-only migration** `e7a9c1d3f5b6` (new Alembic head; revises `d4f6b8c0e2a5`; no table or column added or altered): an `organization_settings.legal_entity_name` still holding exactly "Soleil Global Transportation Inc." becomes "Solaris Express Inc."; any other value is left alone; the downgrade reverses it. The model default changed with it |
| UAT seed | The demo label sender reads Solaris Express Inc.; nothing else new |
| Packaging | Unchanged: `uat_package` derives `RC-UAT-<N>` and the application commit from the newest `docs/RC_UAT_<N>_BASELINE.json` |
| Dependencies | None. Both lock digests carried from RC-UAT-23 (no change between `3151095` and `f4a04a3`) |
| UAT packs | `AIR_UAT_PACK.md` 95 → **96** (`UAT-BLD-25`; the editor sentence updated in `UAT-OWN-20` and `UAT-OWN-28`). `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-23's files are unchanged. Against this tree they drift on **the Alembic head only**
(`d4f6b8c0e2a5` recorded, `e7a9c1d3f5b6` measured): the build added no dependency and no public
tracking field, and none of the ten checks hashes application code, so the screen changes above
do not show in the drift report.

## 2. Evidence

From the build's gates on the application tree (`28_BUILD_RC24_RECORD.md` §2):

| Gate | Result |
|---|---|
| ruff | clean (391 files formatted) |
| Backend, full | **4,940 passed**, 1 skipped, 0 failed, in nine foreground chunks covering all 159 test files; 4 new in `test_rc24_legal_entity.py` |
| eslint, vitest, vite build | clean; **844 passed** (2 new in `rc24LegalEntity.test.jsx`); built |
| Playwright | **326 passed** — one full run on port 5173 (13.5 min); no second run needed |
| Alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database — head `e7a9c1d3f5b6`, no new upgrade operations detected (data only) |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_23_BASELINE.json` | 1 of 10 drifted: the Alembic head (see §1) |
| `verify_uat_blank.py` | pass (49 / 60 / 96) |
| `verify_decision_log.py` | pass (239 records; the next free decision number is 0240) |
| `verify_owner_decisions.py` | pass (112 recorded, 90 answered, 22 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process over git archives (no database opened); the same walker over `3151095` reproduces RC-UAT-23's 273 / 242 / 26 / 18 / 21 / 2 / 3 and 55, and the two route tables, permission sets and Pydantic field sets are identical |
| Alembic head | Read from the migration scripts of git archives of `3151095` (`d4f6b8c0e2a5`) and `f4a04a3` (`e7a9c1d3f5b6`), no database |

## 3. Counts

| | RC-UAT-23 | RC-UAT-24 |
|---|---:|---:|
| Backend tests | 4,936 | **4,940** passed (+1 skipped) |
| Frontend unit tests | 842 | **844** |
| Playwright tests | 326 (once) | 326 (once) |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 273 | 273 |
| Permissions | 55 | 55 |
| Public tracking contract fields | 25 | 25 |
| Customer Account detail / list item / quote fields | 26 / 18 / 18 | 26 / 18 / 18 |
| Staff quote document fields (not in the checked set) | 21 | 21 |
| Alembic head | `d4f6b8c0e2a5` | **`e7a9c1d3f5b6`** |
| UAT cases: staff / Customer Account / air | 49 / 60 / 95 | 49 / 60 / **96** |
| Owner decisions recorded (open) | 111 (22) | **112 (22)** |
| Decision log records | 235 | **239** |
| Supported Python (UAT) | 3.11 to 3.14 | 3.11 to 3.14 |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* `test_phase14_golden.py::test_document_deep_scan_is_customer_safe` failed once in the RC-UAT-22
  build's backend run and passed on the immediate rerun; the leak list was not captured, so the
  cause is not known (`26_BUILD_RC22_RECORD.md` §3). It did not fail in the RC-UAT-23 run (4,936
  passed) or the RC-UAT-24 run (4,940 passed, 0 failed); it stays a known intermittent until
  explained. If it recurs, the assertion message names the field.
* B-13 is built but partly open: whether reinstatement should instead be refused outright after
  a merge (`19_OWNER_QUESTIONS.md` §0000); the re-link and close choices are stand-ins B-15 to B-20.
* The quote GST/HST wording is confirmed (OD-109, 2026-10-24); domestic shipments cannot be
  quoted on screen (P-10); the builds' stand-ins A-1 to A-14, B-1 to B-20 and D-1 to D-12 in
  `19_OWNER_QUESTIONS.md` §0000, the remaining invoice stand-ins of I-1 to I-13 in §00000 (I-1,
  I-10, I-11 and I-12 answered in RC-UAT-24), R-1 to R-14 in §000.
* Retention deletion is built but **off**; periods undecided (OD-01, OD-36). Testers only dry-run it.
* Not started; Ben: skip for now (OD-112): returns (OD-22), staff MFA (OD-17), production email
  (OD-34), provider sync (OD-21).
* Python 3.15 waits for the pinned packages (P-8); browser Back from an unsaved invoice draft is
  not intercepted (F-9).
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-23: see `RC_UAT_23_BASELINE.md` §4, less I-1 (confirmed by Ben, DEC-0237)
  and I-10 (built, DEC-0236).

## 5. What the lead runs after committing

Done: application and tests committed as `f4a04a3`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `3151095` (RC-UAT-23), or do not merge `fix/owner-answers-rc17` past `bb9a89b`. The
build added no dependency and one data-only migration, `e7a9c1d3f5b6`, whose downgrade puts the
old default name back on settings rows holding exactly "Solaris Express Inc.". A UAT database is
disposable: rebuild it from the RC-UAT-23 checkout with `uat_env.py --reset` rather than
downgrade one in place.
