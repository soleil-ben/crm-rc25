# RC-UAT-15 — the release candidate frozen for UAT round 12

**Identifier:** RC-UAT-15 · **Frozen:** 2026-10-18 · **Branch:** `fix/uat-round-11`
**Measured at:** `b81ad85` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-14, measured at `04123c1`
**Machine-readable:** `docs/RC_UAT_15_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-14 listed are unchanged.

## 1. Why RC-UAT-14 was superseded

UAT round 11 (`PROJECT_STATUS.md` §42, the owner's answers to §40.4 and §41.4) changed
screens, a response field, request validation and search behaviour. No route, migration or
dependency changed.

| Category | Changed |
|---|---|
| Screens | Registration: "Billing address is the same as the address above" starts ticked (DEC-0158); the postal code is "(optional)" for the address and billing (DEC-0159). My shipments: each row and card shows **Booking reference** (DEC-0160); the search hint names package IDs |
| API | `AccountShipmentListItem` gains `booking_reference` (18 fields; the detail stays 24). `q` also matches the shipment's own package references, after the ownership clause (DEC-0161). Registration requires country, line 1, city, and province or state; a blank postal code is never refused |
| Wording | The postal code and ZIP code labels; the search hint; "Booking reference" and "Not recorded" on the list |
| Confirmed, unchanged | DEC-0155's lockout; the Canada default; accent-insensitive search (DEC-0157) |
| UAT pack | CA-SHP-20 added; 60 cases (DEC-0162) |

There are still 139 path–method pairs, and the Alembic head and both lock digests carry
over. RC-UAT-14's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_14_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 327 files |
| Backend | **2,969 passed, 2 failed**, 773 s. The two failures are environmental, as at RC-UAT-13 and RC-UAT-14: the worktree lacks the gitignored `data/solaris_crm.db` and `data/uat/solaris_uat.uat.db` that `test_e2e_safety.py` and `test_incident_cleanup.py` inspect. To be confirmed in the main checkout |
| `eslint .` | clean |
| Frontend unit | **506 passed**, 38 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`, ports 8150/5350) | **289 passed**, 0 failed, one worker, retries 0, 10.9 minutes, first full run. Scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py` (60 Customer Account cases), `verify_owner_decisions.py`, `verify_decision_log.py` pass |

One defect was found during validation, in the tests: the first full backend run, at
`b13fbd7`, failed a third privacy scan that planted a booking reference on the customer's
list. `b81ad85` allows it on the list row only (AS-16); the whole suite was re-run there.

## 3. Counts

| | RC-UAT-14 | RC-UAT-15 |
|---|---:|---:|
| Backend tests | 2,925 | **2,971** (2,969 passing here) |
| Frontend unit tests | 491 | **506** |
| Playwright tests | 284 | **289** |
| Accessibility screen states (invocations) | 64 (127) | 64 (127) |
| Backend path–method pairs | 139 | 139 |
| Public tracking contract fields | 24 | 24 |
| Customer Account list item fields | 17 | **18** |
| Customer Account list filters | 5 | 5 (`q` also reads package references) |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / **60** |
| Decision log records | 156 | **162** |

## 4. Known risks carried

* The booking reference is on the list, not on the shipment detail (§42.4 point 1).
* Cancelled packages are searched (§42.4 point 2).
* There is no postal code format check, only the 30-character bound (§42.4 point 3).
* Only the form starts the billing box ticked; the API default is still `false` (§42.4
  point 4).
* Two backend tests need the main checkout's gitignored databases (§42.2).
* Unchanged from RC-UAT-14: DEC-0155's lockout and the Canada default (now confirmed by
  the owner, DEC-0157), English only (OD-39, DEC-0154), and the rest of RC-UAT-14 §4.

## 5. Rollback

Roll back to `04123c1` (RC-UAT-14), or revert the merge of `fix/uat-round-11`. No
migration, no dependency step, and no data to undo: a registration accepted without a
postal code simply has none, which RC-UAT-14 reads, and the list field and the package
search write nothing.
