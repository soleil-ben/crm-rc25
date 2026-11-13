# RC-UAT-13 — the release candidate frozen for UAT round 10

**Identifier:** RC-UAT-13 · **Frozen:** 2026-10-18 · **Branch:** `fix/uat-round-9`
**Measured at:** `f872068` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-12, measured at `3d46044`
**Machine-readable:** `docs/RC_UAT_13_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-12 listed are unchanged.

## 1. Why RC-UAT-12 was superseded

UAT round 9 (`PROJECT_STATUS.md` §40) changed screens, validation, audit behaviour and
wording. No route, migration or dependency changed.

| Category | Changed |
|---|---|
| Screens | Registration's first section is **Address**; the billing box reads "Billing address is the same as the address above" (DEC-0150). Country, Address line 1, City, Province or state and Postal code are marked "(required)" with an inline error each, for the address and for billing when unticked (DEC-0151, DEC-0152). The driver note is "Notes for driver (buzz code, contact concierge, security,...)" (DEC-0150) |
| Validation | The server refuses the first missing address part, then the first missing billing part when unticked, 422 with `field` naming it |
| Behaviour | Sign-in and sign-out audit rows carry the actor `customer_account:CA-…` (DEC-0153). A refused sign-in is committed, so its audit row and the per-account lockout take effect over HTTP (DEC-0155) |
| Wording | The new form text and the server's address and billing sentences |

There are still 139 path–method pairs, and the Alembic head and both lock digests carry
over. RC-UAT-12's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_12_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 323 files |
| Backend | **2,902 passed, 2 failed**, 791 s. The two failures are environmental: the worktree lacks the gitignored `data/solaris_crm.db` and `data/uat/solaris_uat.uat.db` that `test_e2e_safety.py` and `test_incident_cleanup.py` inspect. To be confirmed in the main checkout |
| `eslint .` | clean |
| Frontend unit | **483 passed**, 36 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`, ports 8130/5330) | **283 passed**, 0 failed, one worker, retries 0, 10.9 minutes. This was the second full run: the first failed one existing case that expected exactly one problem, and the fix is `f872068`. Scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-12 | RC-UAT-13 |
|---|---:|---:|
| Backend tests | 2,874 | **2,904** (2,902 passing here) |
| Frontend unit tests | 471 | **483** |
| Playwright tests | 278 | **283** |
| Accessibility screen states (invocations) | 64 (127) | 64 (127) |
| Backend path–method pairs | 139 | 139 |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 149 | **155** |

## 4. Known risks carried

* DEC-0155 was not requested: the per-account lockout now takes effect over HTTP. It is in
  its own commit, `ae3d62f` (§40.4 point 1).
* An untouched form lists billing errors along with the address errors until a street is
  typed (§40.4 point 2).
* The country list starts on Canada, so its required error is not reachable from the form
  (§40.4 point 3). Postal code is required for Vietnam too.
* Two backend tests need the main checkout's gitignored databases (§40.2).
* The Customer Account is English only (OD-39, DEC-0154).
* Unchanged from RC-UAT-12: DEC-0148 values in Audit access; DEC-0142, DEC-0143, DEC-0141;
  the profile screen is audited at desktop width only; the react-router advisories; the
  unexplained intermittent failure class.

## 5. Rollback

Roll back to `3d46044` (RC-UAT-12), or revert the merge of `fix/uat-round-9`. To drop only
DEC-0155, revert `ae3d62f`. No migration and no dependency step. Complete addresses and the
new audit rows are ordinary data under RC-UAT-12, and a locked account unlocks on its own
after 15 minutes.
