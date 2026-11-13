# RC-UAT-8 — the release candidate frozen for UAT round 5

**Identifier:** RC-UAT-8 · **Frozen:** 2026-10-15 · **Branch:** `fix/uat-round-4`
**Measured at:** `4374407` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-7, measured at `d9f61ee`
**Machine-readable:** `docs/RC_UAT_8_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-7 listed are unchanged.

## 1. Why RC-UAT-7 was superseded

UAT round 4 fix pack 4 (`PROJECT_STATUS.md` §35) changed all four of the convention's
categories:

| Category | Changed |
|---|---|
| Screens | Suppress address on the Consent tab; Deactivate account on the review screen, behind a confirmation; an Admin override badge on Audit access; the decision forms removed once decided; an internal-notes confirmation; linked error-summary entries on registration; no milestone invitation on a cancelled booking's empty timeline |
| Routes | `POST /api/v1/customer-account/identities/{ref}/deactivate` (Admin only, DEC-0131) and `POST /api/v1/customers/{id}/consent/suppressions` (Marketing and Admin, DEC-0130). 139 path–method pairs, was 137 |
| Schemas | `admin_override` on audit rows (DEC-0129); `deactivated_at` and `can_deactivate` on the identity status; two permissions, `customer_account:deactivate` and `suppression:add` |
| Wording and behaviour | An all-skip import can be finished; the reset 429 carries the recovery sentence (DEC-0132); a named `shipment.internal_notes_update` audit row |

No migration and no dependency changed. The Alembic head and both lock digests carry over.
RC-UAT-7's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_7_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 313 files |
| Backend | **2,811 passed**, 0 failed, 780 s |
| `eslint .` | clean |
| Frontend unit | **433 passed**, 31 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **270 passed**, 0 failed, one worker, retries 0, 10.3 minutes; scratch removed. One earlier run failed 3 (summary-link target size, a spec expecting the removed decision buttons, and a status-card refetch defect); all fixed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-7 | RC-UAT-8 |
|---|---:|---:|
| Backend tests | 2,785 | **2,811** |
| Frontend unit tests | 421 | **433** |
| Playwright tests | 269 | **270** |
| Accessibility screen states (invocations) | 63 (125) | 63 (125) |
| Backend path–method pairs | 137 | **139** |
| Frontend routes: staff / Customer Account | 17 / 15 | 17 / 15 |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 128 | **132** |

## 4. Known risks carried

* A deactivated account's link stays active and still blocks a customer merge (owner question).
* Operations can still suppress through a "suppressed" consent event (owner question).
* The resend-verification 429 still shows its throttle notice (owner question).
* Email change is deferred by the owner (DEC-0125).
* Unchanged: the profile screen is audited at desktop width only; 57 or 59; the
  react-router advisories; the unexplained intermittent failure class.

## 5. Rollback

To `d9f61ee` (RC-UAT-7), or revert the merge of `fix/uat-round-4`. No migration and no
dependency step. Accounts deactivated and addresses suppressed under RC-UAT-8 stay that way;
an Admin releases a suppression through the existing release route. Rebuild a UAT database with
`uat_env.py --reset` for a clean seed.
