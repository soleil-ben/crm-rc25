# RC-UAT-10 — the release candidate frozen for UAT round 7

**Identifier:** RC-UAT-10 · **Frozen:** 2026-10-15 · **Branch:** `fix/uat-round-6`
**Measured at:** `ba3fce0` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-9, measured at `e1720f4`
**Machine-readable:** `docs/RC_UAT_10_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-9 listed are unchanged.

## 1. Why RC-UAT-9 was superseded

UAT round 6 fix pack 6 and the owner's decisions of 2026-10-15 (`PROJECT_STATUS.md` §37)
changed three of the convention's categories:

| Category | Changed |
|---|---|
| Screens | The approval preview shows "The customer's email will change" with both addresses, and "Approving ends a deactivated account's link"; "Submitted values written" can read "Only the email"; both evidence-reference fields say "Ticket or reference number only, no names" |
| Schemas and rules | `email_change` and `ends_link_of` on the approval preview; a linked customer's email cannot be changed by staff (DEC-0138) |
| Behaviour | Link-existing writes the sign-in email to the record, audited (DEC-0138); a suppression blocks marketing email only, so verification, reset and decision notices reach a suppressed address (DEC-0139); a takeover approval ends a deactivated account's link, audited (DEC-0140) |

No route, migration or dependency changed: 139 path–method pairs, the Alembic head and both
lock digests carry over. RC-UAT-9's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_9_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 317 files |
| Backend | **2,850 passed**, 0 failed, 774 s |
| `eslint .` | clean |
| Frontend unit | **450 passed**, 33 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **272 passed**, 0 failed, one worker, retries 0, 10.3 minutes, first run; scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-9 | RC-UAT-10 |
|---|---:|---:|
| Backend tests | 2,832 | **2,850** |
| Frontend unit tests | 444 | **450** |
| Playwright tests | 272 | 272 |
| Accessibility screen states (invocations) | 64 (127) | 64 (127) |
| Backend path–method pairs | 139 | 139 |
| Frontend routes: staff / Customer Account | 17 / 15 | 17 / 15 |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 137 | **141** |

## 4. Known risks carried

* A linked customer's email cannot be changed by staff while its account is active or
  suspended, and customers cannot change their own (DEC-0125); owner question, §37.4.
* A takeover sends no message to the deactivated account's former holder (owner question).
* Evidence references may still contain a typed name; the field now asks for none
  (DEC-0141) and the display refuses values with `@`.
* Unchanged: the profile screen is audited at desktop width only; the react-router
  advisories; the unexplained intermittent failure class.

## 5. Rollback

To `e1720f4` (RC-UAT-9), or revert the merge of `fix/uat-round-6`. No migration and no
dependency step. Emails written to linked customers stay on the records (audited); links
ended by a takeover stay revoked. Rebuild a UAT database with `uat_env.py --reset` for a
clean seed.
