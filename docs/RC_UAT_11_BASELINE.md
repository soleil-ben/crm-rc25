# RC-UAT-11 — the release candidate frozen for UAT round 8

**Identifier:** RC-UAT-11 · **Frozen:** 2026-10-16 · **Branch:** `fix/uat-round-7`
**Measured at:** `e74b388` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-10, measured at `ba3fce0`
**Machine-readable:** `docs/RC_UAT_11_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-10 listed are unchanged.

## 1. Why RC-UAT-10 was superseded

The owner's decisions of 2026-10-16 (`PROJECT_STATUS.md` §38) changed two of the
convention's categories:

| Category | Changed |
|---|---|
| Screens | The customer edit form shows a held email read-only, with "This is the sign-in email of the customer's account, which is active or suspended. To change it, deactivate the account first." (DEC-0142) |
| Schemas and wording | `email_held_by_account` on the customer detail; the server's refusal now names deactivation (DEC-0142) |

DEC-0143 (a suppression blocks marketing email only, shipment and operational email
included) and DEC-0144 (no notice to a former holder on a takeover) confirm behaviour
RC-UAT-10 already had, and add tests. No route, migration or dependency changed: 139
path–method pairs, the Alembic head and both lock digests carry over. RC-UAT-10's files are
unchanged and still verify 10 of 10 with `--baseline docs/RC_UAT_10_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 319 files |
| Backend | **2,857 passed**, 0 failed, 808 s |
| `eslint .` | clean |
| Frontend unit | **455 passed**, 34 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **272 passed**, 0 failed, one worker, retries 0, 10.6 minutes, first run; scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-10 | RC-UAT-11 |
|---|---:|---:|
| Backend tests | 2,850 | **2,857** |
| Frontend unit tests | 450 | **455** |
| Playwright tests | 272 | 272 |
| Accessibility screen states (invocations) | 64 (127) | 64 (127) |
| Backend path–method pairs | 139 | 139 |
| Frontend routes: staff / Customer Account | 17 / 15 | 17 / 15 |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 141 | **144** |

## 4. Known risks carried

* A linked customer's email changes only after an administrator deactivates the account
  (DEC-0142); customers cannot change their own (DEC-0125).
* A takeover sends no message to the former holder, by owner decision (DEC-0144).
* No shipment email exists; when built it must not read `contact_suppressions` (DEC-0143).
* The read-only email field is covered by unit tests and CA-APR-13, not by Playwright.
* Unchanged: evidence references may contain a typed name (DEC-0141); the profile screen is
  audited at desktop width only; the react-router advisories; the unexplained intermittent
  failure class.

## 5. Rollback

To `ba3fce0` (RC-UAT-10), or revert the merge of `fix/uat-round-7`. No migration, no
dependency step and no data written differently: the server already enforced the email
rule under RC-UAT-10.
