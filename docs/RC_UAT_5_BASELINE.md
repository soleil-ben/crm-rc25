# RC-UAT-5 — the release candidate frozen for human UAT round 2

**Identifier:** RC-UAT-5 · **Frozen:** 2026-10-14 · **Branch:** `fix/uat-round-1`
**Measured at:** `0dfaf23` (the application commit; the freeze commit that follows touches
only documents and scripts) · **Supersedes:** RC-UAT-4, measured at `0b772e0`
**Machine-readable:** `docs/RC_UAT_5_BASELINE.json`, checked by
`scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The nine launch blockers RC-UAT-4 listed are
unchanged; none of them is a development task (§7).

---

## 1. Why RC-UAT-4 was superseded

The owner had both UAT packs executed by a bot on 2026-10-14 (106 cases: 67 passed, 11
failed, 28 blocked) and approved a thirteen-item fix pack from it, then a one-hour reset
link. `PROJECT_STATUS.md` §31 and §32 describe the work. The re-freeze convention keeps an
identifier only when nothing a tester sees changed; this work changed all four things the
convention names:

| Category | Changed |
|---|---|
| Screens | Duplicates tab with compare and merge; staff create, deactivate and reactivate; the Customer Account status card (suspend, reinstate); tags in the customer form; gross profit; `/customers/new`; referral recorder |
| Routes | `GET /customer-account/identities/{ref}`, `POST …/suspend`, `POST …/reinstate`; the staff `/customers/new` screen |
| Schemas | `ReferralOut.recorded_by`; `costs.gross_profit`; `counting_guard.route_groups`; the identity status models; the link-template parameter `expires_after` |
| Wording and behaviour | Public tracking shows only published milestones and answers a cancelled booking with the generic not-found (DEC-0118); link tokens travel in the URL fragment (DEC-0119); "expires in 1 hour" (DEC-0121); CA-APR-17 rewritten |

**No migration and no dependency changed.** The Alembic head is still `6af30fcdd3a8` and
both lockfile digests are RC-UAT-4's. That is why `verify_rc_baseline.py` reported 10 of 10
against RC-UAT-4 on this tree: its ten checks are invariants, the migration head, the two
lockfiles and the staff case count, and none of them hashes application code. A clean
report against a superseded baseline does not mean nothing moved.

RC-UAT-4's two files are unchanged. Re-check it with:

```
backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_4_BASELINE.json
```

## 2. Evidence at `0dfaf23`, measured 2026-10-14

Windows 11, Python 3.12.10, Node 24.11.1, npm 11.6.2, SQLite 3.49.1. Every gate was run at
this commit; nothing is carried forward.

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 226 files |
| Backend (`pytest`) | **2,689 passed**, 0 failed, 0 skipped, 900 s |
| `eslint .` | clean |
| Frontend unit (`vitest`) | **363 passed**, 25 files |
| `vite build` | succeeds, three shell chunks |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **263 passed**, 0 failed, one worker, retries 0, 11.2 minutes; scratch database and run directory removed, `data/e2e` empty afterwards |
| `npm audit` | 2 moderate, both react-router 6.30.6, unchanged and unreachable (RC-UAT-4 §0) |
| `verify_rc_baseline.py` | 10 of 10 against this baseline |
| `verify_uat_blank.py` / `verify_owner_decisions.py` / `verify_decision_log.py` | pass / pass / pass (the next free decision number is 0122) |

## 3. Counts

| | RC-UAT-4 | RC-UAT-5 |
|---|---:|---:|
| Backend tests | 2,632 | **2,689** |
| Frontend unit tests | 323 | **363** |
| Playwright tests | 259 | **263** |
| Accessibility screen states audited (× 2 viewports) | 62 | 62 |
| Backend path–method pairs | 126 | **129** |
| Staff API | 111 | **114** |
| Customer Account review routes (staff) | 8 | **11** |
| Staff frontend routes | 15 | **16** |
| Customer Account routes (API / frontend) | 10 / 14 | 10 / 14 |
| Public tracking contract fields | 24 | 24 |
| Staff UAT cases | 49 | 49 |
| Customer Account UAT cases (by heading) | 59 | 59 |
| Decision log records | 117 | 121 |

## 4. The invariants that must not move

Unchanged and verified: no production adapter, both integration resource allowlists
empty, the public contract at 24 fields, tracking source modes `manual` and
`external_link` only, `connected_api` refused, no provider webhook route, no public
correlation header.

## 5. Known risks carried by this freeze

* **Public tracking shows only published milestones** (DEC-0118). A delivery staff record
  without "Publish this update" leaves the public page at the last published milestone.
  Brief Operations before UAT round 2.
* **The committed link URL is in Chromium's history database** (DEC-0119). The reset link
  now lives one hour (DEC-0121); the verification link 24.
* **Customer identity deactivation is not routed** (DEC-0120), pending OD-35's execution.
* **57 or 59.** The Customer Account pack has 59 case headings; the bot run listed 57.
* **The unexplained intermittent failure class** (RC-UAT-4 §11) recurred once during the
  fix pack: one run failed waiting for the staff applications heading inside an
  activation helper, and every other run passed. Not classified as fixed.
* The two moderate react-router findings, eslint 9's support status and the Vitest async
  ceiling are as RC-UAT-4 recorded them.

## 6. Rollback

To `0b772e0` (RC-UAT-4), or revert the merge of `fix/uat-round-1` on main. No migration
and no dependency step. Reseed any UAT database from the restored checkout. Reset and
verification links issued under RC-UAT-5 carry the token in the fragment, which RC-UAT-4's
landing pages do not read, so such links must be re-requested after a rollback.
`data/solaris_crm.db`, `data/uat/` and `backups/` were not written by this work.

## 7. What this baseline does not say

It does not say any UAT case passed: no human has executed either pack, and every result
field is blank (`verify_uat_blank.py`). It does not say the product is production-ready:
OD-34, OD-37, OD-39, OD-19, OD-01/OD-36, DEC-0006, OD-17, the secret store and the deferred
provider integration are unchanged.
