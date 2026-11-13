# RC-UAT-7 — the release candidate frozen for UAT round 4

**Identifier:** RC-UAT-7 · **Frozen:** 2026-10-15 · **Branch:** `fix/uat-round-3`
**Measured at:** `d9f61ee` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-6, measured at `92d3331`
**Machine-readable:** `docs/RC_UAT_7_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-6 listed are unchanged.

## 1. Why RC-UAT-6 was superseded

UAT round 3 fix pack 3 (`PROJECT_STATUS.md` §34) changed what a tester sees in three of the
convention's four categories:

| Category | Changed |
|---|---|
| Screens | Import duplicate decisions start undecided and the import button waits for all of them; Export audience on each segment; a Details column on Audit access; Record event hidden on a cancelled booking; Add follow-up hidden without `task:write`; account-menu arrow keys; focus into the Record event form and onto the customer shipment heading |
| Routes | None added or removed |
| Schemas | `costs` omitted, not `null`, without cost access; `marketing.delivery_blocked` on the profile and consent responses; `reason_code` and `changed_fields` on audit rows |
| Wording and behaviour | An undecided duplicate refuses the import commit; events refused on a cancelled booking; the cancelled count honours the route filter; one preferred-language source (DEC-0128); booking, not package; the stale Shipments-tab copy removed; the registration 429 carries the generic sentence; the plain suppressed-address note (DEC-0127) |

The UAT seed gained `UAT-CA-SHP-10`, booked 23:30 Toronto time. `scripts/expire_account_link.py`
and `ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER` support CA-REG-07 and CA-REG-09
(`docs/UAT/ENVIRONMENT.md` §3b and §3c). No migration and no dependency changed. The Alembic
head and both lock digests carry over. RC-UAT-6's files are unchanged and still verify
10 of 10 with `--baseline docs/RC_UAT_6_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 311 files |
| Backend | **2,785 passed**, 0 failed, 880 s |
| `eslint .` | clean |
| Frontend unit | **421 passed**, 30 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **269 passed**, 0 failed, one worker, retries 0, 10.8 minutes; scratch removed. One earlier run failed 2 on locators that found "Declined" twice; the specs were fixed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-6 | RC-UAT-7 |
|---|---:|---:|
| Backend tests | 2,728 | **2,785** |
| Frontend unit tests | 389 | **421** |
| Playwright tests | 269 | 269 |
| Accessibility screen states (invocations) | 63 (125) | 63 (125) |
| Backend path–method pairs | 137 | 137 |
| Frontend routes: staff / Customer Account | 17 / 15 | 17 / 15 |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 123 | **128** |

## 4. Known risks carried

* Deactivation is decided (Admin-only, DEC-0126) but still not routed.
* Email change is deferred by the owner (DEC-0125).
* The internal-notes "empty after save" report had no reliable reproduction. The fix shows
  the saved value from the save response.
* Carrier events for a cancelled booking are now rejected, not applied.
* The password-reset per-connection limit still answers "Too many requests".
* Unchanged: the profile screen is audited at desktop width only; 57 or 59; the
  react-router advisories; the unexplained intermittent failure class.

## 5. Rollback

To `92d3331` (RC-UAT-6), or revert the merge of `fix/uat-round-3`. No migration and no
dependency step. A UAT database built under RC-UAT-7 holds the extra seeded shipment.
Rebuild it with `uat_env.py --reset` for a clean RC-UAT-6 seed.
