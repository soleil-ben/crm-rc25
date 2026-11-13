# RC-UAT-14 — the release candidate frozen for UAT round 11

**Identifier:** RC-UAT-14 · **Frozen:** 2026-10-18 · **Branch:** `fix/uat-round-10`
**Measured at:** `04123c1` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-13, measured at `f872068`
**Machine-readable:** `docs/RC_UAT_14_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-13 listed are unchanged.

## 1. Why RC-UAT-13 was superseded

UAT round 10 (`PROJECT_STATUS.md` §41) changed a screen, an API query parameter and
wording. No route, migration or dependency changed.

| Category | Changed |
|---|---|
| Screens | My shipments: the "Solaris Shipment ID" box (whole ID only) is **Search shipments**, a search box with a hint listing what it searches (DEC-0156) |
| API | `q` on `GET /api/v1/account/shipments`: partial, case- and accent-insensitive, over the Solaris Shipment ID, booking reference and origin and destination cities, after the ownership clause; 64 characters; LIKE wildcards literal. `reference` is unchanged |
| Wording | The box's label and hint; "Search for 64 characters or fewer." |

There are still 139 path–method pairs, and the Alembic head and both lock digests carry
over. RC-UAT-13's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_13_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 325 files |
| Backend | **2,923 passed, 2 failed**, 816 s. The two failures are environmental, as at RC-UAT-13: the worktree lacks the gitignored `data/solaris_crm.db` and `data/uat/solaris_uat.uat.db` that `test_e2e_safety.py` and `test_incident_cleanup.py` inspect. To be confirmed in the main checkout |
| `eslint .` | clean |
| Frontend unit | **491 passed**, 37 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`, ports 8120/5293) | **284 passed**, 0 failed, one worker, retries 0, 10.8 minutes, first run. Scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-13 | RC-UAT-14 |
|---|---:|---:|
| Backend tests | 2,904 | **2,925** (2,923 passing here) |
| Frontend unit tests | 483 | **491** |
| Playwright tests | 283 | **284** |
| Accessibility screen states (invocations) | 64 (127) | 64 (127) |
| Backend path–method pairs | 139 | 139 |
| Public tracking contract fields | 24 | 24 |
| Customer Account list filters | 4 | **5** (`q`) |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 155 | **156** |

## 4. Known risks carried

* The booking reference is searched but not shown, so a row found by it carries nothing
  saying why; a customer can confirm a substring of their own shipments' booking
  references, never anybody else's (§41.4 point 1).
* Accents are ignored as well as case, beyond the request (§41.4 point 2). Package
  references are not searched (§41.4 point 3).
* Two backend tests need the main checkout's gitignored databases (§41.2).
* Unchanged from RC-UAT-13: DEC-0155's lockout, the billing errors on an untouched form,
  the country list starting on Canada, English only (OD-39, DEC-0154), and the rest of
  RC-UAT-13 §4.

## 5. Rollback

Roll back to `f872068` (RC-UAT-13), or revert the merge of `fix/uat-round-10`. No
migration, no dependency step, and no data to undo: the search writes nothing. A
bookmarked `?q=` link shows the unfiltered list under RC-UAT-13.
