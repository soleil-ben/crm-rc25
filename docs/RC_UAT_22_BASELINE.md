# RC-UAT-22 — the release candidate frozen for UAT of the B-13 build of 2026-10-24

**Identifier:** RC-UAT-22 · **Frozen:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `61f5c22` (`61f5c22f3f215ebbdada8999d9a6309e955a9e9a`), the application commit of
the RC-UAT-22 build · **Supersedes:** RC-UAT-21, measured at `be7d2df`
**Machine-readable:** `docs/RC_UAT_22_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-21 listed are unchanged.

## 1. Why RC-UAT-21 was superseded

The RC-UAT-22 build (`PROJECT_STATUS.md` §62, DEC-0234, record
`docs/b2c_merge/26_BUILD_RC22_RECORD.md`, status page `docs/b2c_merge/BUILD_STATUS.md`) built
B-13 and fixed the Playwright blank-page flake at its cause. It changed what a tester sees.

| Category | Changed |
|---|---|
| Screens | **Customer accounts → Accounts needing a customer** (Admin only): an account approved once that holds no link and no pending proposal — typically reinstated after its customer was merged or archived — is **re-linked** to a named customer after previewing and acknowledging the history the link opens (fingerprint-checked; the merge survivor suggested; no customer already holding a link; the single email rule), or **closed** as a reversible deactivation (`orphan_closed`, nothing emailed). Stand-ins B-15 to B-20 (DEC-0234). Dialogs taller than the window now scroll |
| Routes | 269 → **273** backend path–method pairs. Staff 238 → **242** (+4), all in the customer-account review set (17 → **21**): `GET /customer-account/identities-orphaned`, `GET /customer-account/identities/{account_reference}/relink-preview`, `POST /customer-account/identities/{account_reference}/relink`, `POST /customer-account/identities/{account_reference}/close-orphan`. Customer Account 26 (mutations 18), public 2, other 3, unchanged |
| Public contract | `PublicTrackingResult` 25, `AccountShipmentDetail` 26, list item 18, `AccountQuoteDetail` 18 — unchanged |
| Permissions | 55, unchanged (the same set): the four routes require `customer_account:review` and `customer_account:deactivate`, Admin's alone |
| Schema | Alembic head `c3e5a7b9d2f4` → **`d4f6b8c0e2a5`**: one new table, `customer_account_relinks`; nothing existing altered |
| Test harness | `run_e2e.mjs` binds Vite and the API to the literal `127.0.0.1` and gives the browser that origin (the `ERR_CONNECTION_REFUSED` blank page: Vite listened on `::1` only while Chromium could connect over IPv4); `test_e2e_safety` asserts the development database is unchanged — absent stays absent — instead of failing in every worktree |
| UAT seed | Nothing new: `UAT-BLD-18` and `-19` follow on from `UAT-BLD-13`, which leaves A1's account without a customer |
| Packaging | Unchanged: `uat_package` derives `RC-UAT-<N>` and the application commit from the newest `docs/RC_UAT_<N>_BASELINE.json` |
| Dependencies | None. Both lock digests carried from RC-UAT-21 (no change between `be7d2df` and `61f5c22`) |
| UAT packs | `AIR_UAT_PACK.md` 88 → **90** (`UAT-BLD-18`, `-19`; `UAT-BLD-13` now points to `-18`); Ben's script step 41. `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-21's files are unchanged. Against this tree they drift on 1 of 10 checks (the Alembic
head), which is the evidence of what the build changed. Its other changes (the screen, the
routes) are not hashed by any of the ten checks.

## 2. Evidence

From the build's gates on the application tree (`26_BUILD_RC22_RECORD.md` §2):

| Gate | Result |
|---|---|
| ruff | clean (386 files formatted) |
| Backend, full | **4,881 passed**, 1 skipped, in six foreground chunks; `test_e2e_safety` passes in the worktree. One intermittent failure, passed on rerun (§4) |
| eslint, vitest, vite build | clean; **835 passed** (10 new in `rc22AccountRelink.test.jsx`); built |
| Playwright | **326 passed, then 326 passed** — two full runs in a row after the harness fix, on the default port 5173 (browser at `127.0.0.1:5173`), no failure, no retry |
| Alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database — head `d4f6b8c0e2a5`, no drift |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_21_BASELINE.json` | 1 of 10 drifted: Alembic head `d4f6b8c0e2a5`, expected `c3e5a7b9d2f4` (expected) |
| `verify_uat_blank.py` | pass (49 / 60 / 90) |
| `verify_decision_log.py` | pass (234 records; the next free decision number is 0235) |
| `verify_owner_decisions.py` | pass (110 recorded, 87 answered, 23 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process (no database opened); the same walker over `be7d2df` reproduces RC-UAT-21's 269, and the two route tables differ by exactly the four routes above |

## 3. Counts

| | RC-UAT-21 | RC-UAT-22 |
|---|---:|---:|
| Backend tests | 4,852 | **4,881** passed (+1 skipped) |
| Frontend unit tests | 825 | **835** |
| Playwright tests | 325 | **326** (twice) |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 269 | **273** |
| Permissions | 55 | 55 |
| Public tracking contract fields | 25 | 25 |
| Customer Account detail / list item / quote fields | 26 / 18 / 18 | 26 / 18 / 18 |
| UAT cases: staff / Customer Account / air | 49 / 60 / 88 | 49 / 60 / **90** |
| Owner decisions recorded (open) | 110 (23) | 110 (23) |
| Decision log records | 233 | **234** |
| Supported Python (UAT) | 3.11 to 3.14 | 3.11 to 3.14 |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* `test_phase14_golden.py::test_document_deep_scan_is_customer_safe` failed once in the build's
  backend run and passed on the immediate rerun of its chunk and alone. Nothing it exercises
  changed in RC-UAT-22 and the leak list was not captured, so the cause is not known
  (`26_BUILD_RC22_RECORD.md` §3); if it recurs, the assertion message names the field.
* B-13 is built but partly open: whether reinstatement should instead be refused outright after
  a merge (`19_OWNER_QUESTIONS.md` §0000); the re-link and close choices are stand-ins B-15 to B-20.
* The quote GST/HST wording is a stand-in (OD-109, P-9), pending Ben; domestic shipments cannot
  be quoted on screen (P-10); the builds' stand-ins A-1 to A-14, B-1 to B-20 and D-1 to D-12 in
  `19_OWNER_QUESTIONS.md` §0000, R-1 to R-14 in §000.
* Retention deletion is built but **off**; periods undecided (OD-01, OD-36). Testers only dry-run it.
* Not started, waiting for Ben: returns (OD-22), staff MFA (OD-17), production email (OD-34),
  provider sync (OD-21).
* Python 3.15 waits for the pinned packages (P-8); browser Back from an unsaved invoice draft is
  not intercepted (F-9).
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-21: see `RC_UAT_21_BASELINE.md` §4, less the two closed here — the B-13
  re-link path (built) and the Playwright `ERR_CONNECTION_REFUSED` flake (fixed at its cause;
  326 passed twice in a row on port 5173) — and the worktree-only `test_e2e_safety` failure
  (the test now passes in worktrees).

## 5. What the lead runs after committing

Done: application and tests committed as `61f5c22`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `be7d2df` (RC-UAT-21), or do not merge `fix/owner-answers-rc17` past `d25df41`. The
build added one migration (a new table only) and no dependency: rebuild the UAT database from
the RC-UAT-21 checkout with `uat_env.py --reset` rather than downgrading one that holds re-link
or close records.
