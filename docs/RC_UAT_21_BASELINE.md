# RC-UAT-21 — the release candidate frozen for UAT of the build of 2026-10-24

**Identifier:** RC-UAT-21 · **Frozen:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `be7d2df` (`be7d2dfce0f0aa5019d24396e8129a2e50d3e1c0`), the application commit of
the RC-UAT-21 build run · **Supersedes:** RC-UAT-20, measured at `98ca88b`
**Machine-readable:** `docs/RC_UAT_21_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-20 listed are unchanged.

## 1. Why RC-UAT-20 was superseded

Ben directed on 2026-10-24 (OD-110) that every remaining feature be built now, with safe
stand-ins recorded as open questions. The build run (`PROJECT_STATUS.md` §61, DEC-0230 to
DEC-0233, record `docs/b2c_merge/25_BUILD_RC21_RECORD.md`) changed what a tester sees.

| Category | Changed |
|---|---|
| Screens | Shipment CSV import and the legacy history baseline, dry-run first, legacy records staff-only (DEC-0230); the customer's and the staff member's own password change, the customer's sign-in email change verified at the new address, Admin reinstatement of a deactivated account (DEC-0231); the customer quote's GST/HST line following the invoice rule — the OD-109 stand-in for P-9, pending Ben (DEC-0232); Admin soft delete and restore of old quote versions, and data-retention settings, **off** by default, with a dry-run report (DEC-0233) |
| Routes | 242 → **269** backend path–method pairs. Staff 216 → **238** (+22): ten shipment and legacy-history import routes, `GET /legacy-shipments` and `/legacy-shipments/{record_id}`, `GET /shipments/{shipment_id}/quote-history`, `POST /quote-versions/{version_id}/delete` and `/restore`, four `/admin/data-retention` routes, `POST /auth/password/change`, `GET /customer-account/identities-deactivated` and `POST /customer-account/identities/{account_reference}/reactivate` (review set 15 → 17). Customer Account 21 → **26** (+5; mutations 14 → 18): `GET /account/security`, `POST /account/password/change`, `POST /account/email/change`, `/confirm` and `/cancel`. Public 2, other 3, unchanged |
| Public contract | `PublicTrackingResult` 25, `AccountShipmentDetail` 26, list item 18 — unchanged; `AccountQuoteDetail` 17 → **18** (`tax`, the quote's GST/HST line) |
| Permissions | 53 → **55**: `quote:delete`, `retention:manage` (Admin only) |
| Schema | Alembic head `f7c2d9e3a1b5` → **`c3e5a7b9d2f4`** through `a1c3e5f7b9d2` (imports) and `b2d4f6a8c1e3` (accounts); new tables only, nothing existing altered |
| UAT seed | Nothing new: the `UAT-BLD` cases create their own data, the imports from the templates in `artifacts\sample-imports\` |
| Packaging | `uat_package` names no release: it derives `RC-UAT-<N>` and the application commit from the newest `docs/RC_UAT_<N>_BASELINE.json` |
| Dependencies | None. Both lock digests carried from RC-UAT-20 (no change between `98ca88b` and `be7d2df`) |
| UAT packs | `AIR_UAT_PACK.md` 71 → **88** (`UAT-BLD-01` to `-17`; `UAT-OWN-35`, `UAT-WSQ-02` and `UAT-QAC-01` updated). `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-20's files are unchanged. Against this tree they drift on 1 of 10 checks (the Alembic
head), which is the evidence of what the build changed. Its other changes (screens, routes,
permissions, the quote field) are not hashed by any of the ten checks.

## 2. Evidence

From the build's gates on the application tree (`25_BUILD_RC21_RECORD.md` §2):

| Gate | Result |
|---|---|
| `ruff check .` | clean (382 files) |
| Backend, full | **4,852 passed**, 1 skipped, 1 failed — the worktree-only `test_e2e_safety.py` |
| eslint, vitest, vite build | clean; **825 passed**; built |
| Playwright | **325 passed**, the full suite run alone, Vite on port 5473 (three earlier runs on the default port each lost one different spec to `ERR_CONNECTION_REFUSED`; each passed alone) |
| Alembic | up, current, check, down, up — head `c3e5a7b9d2f4` |
| Independent tester / reviewer | 11 golden tests (`test_rc21_golden.py`), the smoke route-tax rule passed against a reset UAT database; reviewer 2 high, 4 medium, 7 low findings, all fixed before commit |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_20_BASELINE.json` | 1 of 10 drifted: Alembic head `c3e5a7b9d2f4`, expected `f7c2d9e3a1b5` (expected) |
| `verify_uat_blank.py` | pass (49 / 60 / 88) |
| `verify_decision_log.py` | pass (233 records; the next free decision number is 0234) |
| `verify_owner_decisions.py` | pass (110 recorded, 87 answered, 23 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process (no database opened); the same walker over `98ca88b` reproduces RC-UAT-20's 242 |

## 3. Counts

| | RC-UAT-20 | RC-UAT-21 |
|---|---:|---:|
| Backend tests | 4,622 | **4,852** passed (+1 skipped; 1 environmental) |
| Frontend unit tests | 795 | **825** |
| Playwright tests | 319 | **325** |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 242 | **269** |
| Permissions | 53 | **55** |
| Public tracking contract fields | 25 | 25 |
| Customer Account detail / list item / quote fields | 26 / 18 / 17 | 26 / 18 / **18** |
| UAT cases: staff / Customer Account / air | 49 / 60 / 71 | 49 / 60 / **88** |
| Owner decisions recorded (open) | 108 (22) | **110** (**23**) |
| Decision log records | 229 | **233** |
| Supported Python (UAT) | 3.11 to 3.14 | 3.11 to 3.14 |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* `test_e2e_safety.py` needs the main checkout's gitignored databases.
* The quote GST/HST wording is a stand-in (OD-109, P-9), pending Ben; domestic shipments cannot
  be quoted on screen (P-10); the build's stand-ins A-1 to A-14, B-1 to B-14 and D-1 to D-12 in
  `19_OWNER_QUESTIONS.md` §0000, R-1 to R-14 in §000.
* Retention deletion is built but **off**; periods undecided (OD-01, OD-36). Testers only dry-run it.
* No staff re-link path for an account reinstated to pending approval after a merge (B-13).
* Not started, waiting for Ben: returns (OD-22), staff MFA (OD-17), production email (OD-34),
  provider sync (OD-21).
* Python 3.15 waits for the pinned packages (P-8); browser Back from an unsaved invoice draft is
  not intercepted (F-9).
* Playwright on the default Vite port lost one spec per full run to `ERR_CONNECTION_REFUSED` in
  three runs — the unexplained blank-page class, not classified as fixed.
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-20: see `RC_UAT_20_BASELINE.md` §4.

## 5. What the lead runs after committing

Done: application and tests committed as `be7d2df`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `98ca88b` (RC-UAT-20), or do not merge `fix/owner-answers-rc17` past `16d80fc`. The
build added three migrations (new tables only) and no dependency: rebuild the UAT database from
the RC-UAT-20 checkout with `uat_env.py --reset` rather than downgrading one that holds imported,
legacy, email-change or retention records.
