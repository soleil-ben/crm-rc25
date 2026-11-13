# RC-UAT-17 — the release candidate frozen for UAT of the air features

**Identifier:** RC-UAT-17 · **Frozen:** 2026-10-21 · **Branch:** `phase-13-b2c-merge`
**Measured at:** `911965b` (`911965bd7ddf575c94792f89ba1b791b16d6e700`), the application commit holding `1089257` plus the
Phase 17 dry-run fixes · **Supersedes:** RC-UAT-16, measured at `58f2039`
**Machine-readable:** `docs/RC_UAT_17_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-16 listed are unchanged,
with OD-39 now read together with OD-71 (the Vietnamese-first copy is unreviewed too).

## 1. Why RC-UAT-16 was superseded

The B2C merge, Phases 13A to 16 (`PROJECT_STATUS.md` §44 to §56, records in
`docs/b2c_merge/`), changed what a tester sees, and Phase 17 (§57, DEC-0218) prepared it for
UAT.

| Category | Changed |
|---|---|
| Screens | Workspace (air masters, items, fees, quotes, send to customer, master milestones), Finance (invoices, payments, refunds, voids, vendor bills, receivables, payables, profitability, month close), Settings → Pricing, Tariffs, Tariff updates, Customer notifications; in the Customer Account, Quotes and Notifications, and every screen Vietnamese first (OD-71) |
| Routes | 139 → **228** backend path–method pairs (staff 202, Customer Account 21, public 2, other 3) |
| Schema | Alembic head `6af30fcdd3a8` → **`c5e8a1f3d7b9`** |
| Dependencies | `backend/requirements.lock.txt`: `openpyxl` 3.1.5 and `et_xmlfile` 2.0.0 (Phase 13A). Digest re-measured. `frontend/package-lock.json` unchanged |
| UAT data | `uat_env.py --reset` adds the air dataset (`scripts/uat_seed_phase13.py`); `--refresh-fx` adds a demo exchange rate |
| UAT packs | A third pack, `docs/UAT/AIR_UAT_PACK.md`, 36 cases. `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged in count; `CA-XP-03` rewritten for OD-71 |
| Phase 17 dry-run fixes | A published master milestone is no longer a repeat of an unpublished one (UAT-MLS-04); the Customer Account session's last-seen touch is best effort on every account route (no more "database is locked" on two loads at once); Issue invoice warns, and the audit notes, a withdrawn or declined offer; the intake mailbox is settable by the service and the first-save audit records "owner default". No route, migration or lockfile |

RC-UAT-16's files are unchanged. Against this tree they drift on 2 of 10 checks (the Alembic
head and the backend lock), which is the evidence of what the merge changed.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean |
| Backend, targeted | The new `test_uat_seed_phase13.py` (14) and `test_phase17_fixes.py` (9), with the consolidation, event, notification, account session and boundary, quote, finance, tariff intake and every `test_uat_*` file: **665 passed, 1 skipped** |
| Backend, full | **Not re-run for the freeze.** At `1089257` (Phase 16 record §3): 4,188 passed, 1 skipped, 2 failed — the environmental pair (`test_e2e_safety.py`, `test_incident_cleanup.py`) that needs the main checkout's gitignored databases |
| eslint, vitest, vite build | clean; **734 passed** (54 files); built — on the uncommitted tree |
| Alembic | head `c5e8a1f3d7b9` (read from the migration files); up/down measured at `1089257` in Phase 16 |
| Playwright | Not re-run after the fixes. At `1089257`: **316 passed**, run alone through `npm run e2e` |
| UAT environment | `uat_env.py --reset`, then `--check`: every required category present (summary in `docs/b2c_merge/21_PHASE_17_RECORD.md`) |
| Verifiers | `verify_rc_baseline.py` **10 of 10**; `verify_uat_blank.py` (49 / 60 / 36), `verify_owner_decisions.py`, `verify_decision_log.py` pass |

The dry run found three application defects, fixed here (§1). The full backend suite and
Playwright were not re-run after them; run both on the app+tests commit.

## 3. Counts

| | RC-UAT-16 | RC-UAT-17 |
|---|---:|---:|
| Backend tests | 3,045 | **4,214** (4,191 at `1089257` + 14 + 9) |
| Frontend unit tests | 538 | **734** |
| Playwright tests | 295 | **316** |
| Accessibility screen states (invocations) | 64 (127) | not re-counted |
| Backend path–method pairs | 139 | **228** |
| Public tracking contract fields | 24 | 24 |
| Customer Account detail / list item / quote fields | 25 / 18 / — | 25 / 18 / **17** |
| UAT cases: staff / Customer Account / air | 49 / 60 / — | 49 / 60 / **36** |
| Decision log records | 166 | **218** |

## 4. Known risks carried

* The full backend suite and Playwright were not re-run for the freeze; accessibility counts
  are not re-measured.
* Two backend tests need the main checkout's gitignored databases.
* The air dataset's dates follow the day of the reset (the closed month is the last month
  past M+7); demo exchange rates count as live for a day (`--refresh-fx`).
* No vendor mailbox; the FX worker is not run in UAT because it calls the bank.
* The owner's open questions in `docs/b2c_merge/19_OWNER_QUESTIONS.md` (stand-ins in force).
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-16: see `RC_UAT_16_BASELINE.md` §4, except "English only", which
  OD-71 replaced.

## 5. What the lead runs after committing

Done: application and tests committed as `911965b`; the SHA is in the JSON and this header;
documents and scripts committed on top (the freeze).

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `58f2039` (RC-UAT-16), or do not merge `phase-13-b2c-merge`. The merge added
migrations and a dependency: restore a pre-merge database backup rather than downgrading a
database holding tariff, quote or finance rows, and reinstall the backend lock.
