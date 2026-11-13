# RC-UAT-6 — the release candidate frozen for UAT round 3

**Identifier:** RC-UAT-6 · **Frozen:** 2026-10-15 · **Branch:** `fix/uat-round-2`
**Measured at:** `92d3331` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-5, measured at `0dfaf23`
**Machine-readable:** `docs/RC_UAT_6_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-5 listed are unchanged.

## 1. Why RC-UAT-5 was superseded

UAT round 2 fix pack 2 (`PROJECT_STATUS.md` §33) changed what a tester sees in all four of
the convention's categories:

| Category | Changed |
|---|---|
| Screens | My profile on the Customer Account; Profile change requests and the profile-change review in the Staff Portal; Tags column and Tag filter on the customer list; review screens refuse an unpermitted role outright |
| Routes | `GET /account/profile`, `POST /account/profile/direct`, `…/profile/proposals`, `…/profile/proposals/withdraw`, `…/consent/marketing`; staff `GET /customer-account/profile-proposals`, `GET …/identities/{ref}/profile-proposal`, `POST …/profile-proposal/decide` |
| Schemas | `app/schemas/account_profile.py`; the profile-review models |
| Wording and behaviour | Customer and public times read naive UTC as UTC (05:19 UTC shows 01:19 Toronto); the merge confirmation names both IDs; a customer's marketing choice is recorded while a suppression stands (DEC-0123) |

No migration and no dependency changed; the Alembic head and both lock digests carry over.
RC-UAT-5's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_5_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 230 files |
| Backend | **2,728 passed**, 0 failed, 918 s |
| `eslint .` | clean |
| Frontend unit | **389 passed**, 28 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **269 passed**, 0 failed, one worker, retries 0, 10.5 minutes; scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-5 | RC-UAT-6 |
|---|---:|---:|
| Backend tests | 2,689 | **2,728** |
| Frontend unit tests | 363 | **389** |
| Playwright tests | 259 → 263 | **269** |
| Accessibility screen states (invocations) | 62 (124) | **63 (125)** — the profile is audited at 1280 px only |
| Backend path–method pairs | 129 | **137** |
| Staff API | 114 | **117** |
| Customer Account API (mutations) | 10 (7) | **15 (11)** |
| Customer Account review routes (staff) | 11 | **14** |
| Frontend routes: staff / Customer Account | 16 / 14 | **17 / 15** |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 121 | 123 |

## 4. Known risks carried

* Profile change requests are a new staff queue with no owner yet.
* Customers cannot change their email address; that needs a verified email-change flow.
* The profile screen is audited at desktop width only.
* The CA-SEC-07 history residual is accepted (DEC-0122).
* Unchanged from RC-UAT-5: 57 or 59 Customer Account cases; identity deactivation unrouted;
  the react-router advisories; the unexplained intermittent failure class.

## 5. Rollback

To `0dfaf23` (RC-UAT-5), or revert the merge of `fix/uat-round-2`. No migration and no
dependency step. Profile proposals and marketing choices recorded under RC-UAT-6 stay in the
database as rows RC-UAT-5 has no screen for.
