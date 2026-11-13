# RC-UAT-9 — the release candidate frozen for UAT round 6

**Identifier:** RC-UAT-9 · **Frozen:** 2026-10-15 · **Branch:** `fix/uat-round-5`
**Measured at:** `e1720f4` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-8, measured at `4374407`
**Machine-readable:** `docs/RC_UAT_9_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-8 listed are unchanged.

## 1. Why RC-UAT-8 was superseded

UAT round 5 fix pack 5 and the owner's decisions of 2026-10-15 (`PROJECT_STATUS.md` §36)
changed three of the convention's categories:

| Category | Changed |
|---|---|
| Screens | An error summary on the Add customer dialog, entries linked to their fields; a malformed email in the registration summary; "Evidence reference" on Audit access; "Suppressed" no longer offered to Operations in the consent form; the resend-verification 429 goes to "Check your email" |
| Schemas and rules | `evidence_reference` on audit rows (DEC-0137); a `suppressed` consent event needs `suppression:add` (DEC-0133); a deactivated account's link no longer blocks a merge (DEC-0134); consent carried on link-existing (DEC-0137) |
| Wording and behaviour | One invalid-email sentence on every form; lifecycle audit summaries name the account; the resend 429 sentence (DEC-0135); a 409 is not retried |

No route, migration or dependency changed: 139 path–method pairs, the Alembic head and both
lock digests carry over. RC-UAT-8's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_8_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 315 files |
| Backend | **2,832 passed**, 0 failed, 772 s |
| `eslint .` | clean |
| Frontend unit | **444 passed**, 32 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **272 passed**, 0 failed, one worker, retries 0, 10.2 minutes, first run; scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-8 | RC-UAT-9 |
|---|---:|---:|
| Backend tests | 2,811 | **2,832** |
| Frontend unit tests | 433 | **444** |
| Playwright tests | 270 | **272** |
| Accessibility screen states (invocations) | 63 (125) | **64 (127)** |
| Backend path–method pairs | 139 | 139 |
| Frontend routes: staff / Customer Account | 17 / 15 | 17 / 15 |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 (confirmed, DEC-0136) |
| Decision log records | 132 | **137** |

## 4. Known risks carried

* On link-existing, consent is recorded for the applicant's address; if the linked record's
  own email differs, its email state row does not change (owner question, §36.4).
* A customer whose only link belongs to a deactivated account cannot be linked to a new
  account (owner question).
* Evidence references now appear in the audit trail; the display refuses values with `@`
  but not a typed name (owner question).
* Email change is deferred by the owner (DEC-0125).
* Unchanged: the profile screen is audited at desktop width only; the react-router
  advisories; the unexplained intermittent failure class.

## 5. Rollback

To `4374407` (RC-UAT-8), or revert the merge of `fix/uat-round-5`. No migration and no
dependency step. Consent events written on link-existing stay in the append-only history (a
withdrawal can be recorded); customers merged while their account was deactivated stay
merged. Rebuild a UAT database with `uat_env.py --reset` for a clean seed.
