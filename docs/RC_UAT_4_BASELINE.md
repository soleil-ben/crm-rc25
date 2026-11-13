# RC-UAT-4 — the release candidate frozen for human UAT

> ## ⚠ PRE-RELEASE. NOT PRODUCTION-READY. NOT UAT-TESTED BY A HUMAN.
>
> This is the build a tester should run against. It is **not** a build anybody should
> deploy, and **no human has executed a single UAT case against it**. Nine launch
> blockers are open, and none of them is a development task.
>
> **Customer Account registration is not production-ready.** It cannot even start in
> production: no email provider is selected (OD-34) and no approved terms text exists
> (OD-37), and the application refuses registration while either is true.

**Frozen:** 2026-09-21, from `phase-12-customer-account-frontend`
**Re-frozen:** 2026-10-11, from `chore/cleanup-xplat-deps-deprecations` (section 0)
**Measured at commit:** `0b772e0125431b7d2d42aa09f9b88a80ad6f277f`
**Previously measured at:** `48abca56d0ea7bd48e2f0f4ee06529bc07cdd408`
**Supersedes:** RC-UAT-3 (`98f1fde`)
**Machine-readable record:** [`RC_UAT_4_BASELINE.json`](RC_UAT_4_BASELINE.json)

```bash
backend/.venv/Scripts/python scripts/verify_rc_baseline.py
```

Every figure below is re-measured by that command from the running code. It reports **10
of 10 matching** at this commit.

---

## 0. The 2026-10-11 re-freeze

RC-UAT-4 was first frozen at `48abca5`. The branch `chore/cleanup-xplat-deps-deprecations`
(`PROJECT_STATUS.md` §29) then changed the dependency locks, which are two of the ten
things the verifier checks, so the baseline in force reported **8 of 10** until it was
re-measured. It is re-frozen here, **keeping the identifier**, because what a tester sees
and does is unchanged: no route, schema, migration, screen or wording moved. The previous
freeze stays verifiable by running the verifier from a checkout of `48abca5`.

### What the reviewed commit changed

Commit `0b772e0` against its base `ffa03ad`: 27 files. Three of them are application code.

| File | Change | Verdict |
|---|---|---|
| `backend/app/core/sqlite_codecs.py` (new) and `backend/app/core/db.py` | Registers four `sqlite3` date/datetime codecs that are the stdlib defaults transcribed, replacing the entries Python 3.12 deprecated | **Stored bytes unchanged.** Seven tests prove it: the "before" runs in a fresh `python -I` subprocess with nothing of the application imported; five sample values store byte-identically through both |
| `frontend/src/app/App.jsx` | `v7_relativeSplatPath` future flag on the `BrowserRouter` | Changes how relative links resolve inside the `/track/*` and `/account/*` splat routes. `frontend/src` has no relative `to=` or `navigate()` target, so nothing observable changes. `tests/utils.jsx` mirrors it |

Everything else is test harness (one interpreter-path module shared by three files, a
5-second async ceiling in `tests/setup.js`, one formatting fix), `scripts/*.py` docstrings,
the `.gitattributes` line-ending policy (no renormalisation diff: the index already held
every text file as LF), both lockfiles, and `PROJECT_STATUS.md`. **No unintended functional
change was found.**

### Evidence at `0b772e0`, measured 2026-10-11

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 295 files |
| Backend `pytest` | **2,632 passed**, 0 failed, 0 skipped, **0 warnings**, 14 min 40 s |
| `eslint .` | clean |
| Frontend unit (`vitest run`, 4.1.11) | **323 passed**, 21 files, 35 s |
| `vite build` | succeeds; three shell chunks |
| Alembic, disposable database | from empty 8 up, `alembic check` clean, 8 down to base, 8 up, `alembic check` clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`, one worker, retries 0) | 259 passed, 0 failed, one worker, retries 0, 10.0 minutes; scratch database and run directory removed, data/e2e empty afterwards |
| `npm audit` | 2 moderate, both `react-router` (below) |
| `verify_rc_baseline.py` | **10 of 10** against this file |
| `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` | pass |

### The two residual `npm audit` findings

Both are on `react-router` 6.30.6 and both are fixed only in 7.18.4, a major version.

| Advisory | Severity | What it needs | Reachable here? |
|---|---|---|---|
| GHSA-wrjc-x8rr-h8h6 — open redirect via backslash in `<Link>` / `useNavigate` (CWE-601; no CVSS score published) | moderate | An attacker-controlled string beginning `\` or `/\` reaching a navigation target | **No.** The dynamic targets in `frontend/src` are: `state.from` in the sign-in flow, which is a `location.pathname` this application wrote and is checked for the `/account/` prefix before use; `destinationForSession()`, a fixed set of paths; and report and dashboard rows, whose `link` is built server-side in `report_service.py` as a literal `/…` path with enum values in the query string. No query parameter, form field or API string ever reaches a navigation |
| GHSA-337j-9hxr-rhxg — constructor injection via `deserializeErrors()` during SSR hydration (CWE-470; CVSS 6.1) | moderate | Server-side rendering with a data router and `hydrateRoot` | **No.** `main.jsx` uses `createRoot`; there is no `StaticRouter`, `createBrowserRouter`, `RouterProvider` or `hydrateRoot` in `frontend/src` |

The React Router 7 upgrade is assessed in [`DECISION_REGISTER.md`](DECISION_REGISTER.md)
§4.4. It is post-launch engineering work, not a UAT or production blocker.

### Known risks carried by this re-freeze

* The two advisories above, accepted as unreachable.
* `eslint` 9.39.5 is marked unsupported on the registry and `eslint-plugin-react` 7.37.5
  does not accept ESLint 10. Development tooling only.
* Vitest 4 needed Testing Library's async ceiling raised to 5 s (`tests/setup.js`). No
  assertion changed.
* The intermittent blank page (§11) is still not classified as fixed.
* The UAT database was reseeded on 2026-09-28 and no longer matches the §27.19 digest in
  `PROJECT_STATUS.md`; it is recorded here by path only and was never a verifier check.
* The nine launch blockers (§10) are unchanged.

### Rollback

No migration was added and the Alembic head is `6af30fcdd3a8` on both sides, so **no
database file is touched** by a rollback.

1. Check out `48abca5` (the previous measurement) or `ffa03ad` (this branch's base; same
   application tree) in a clean working tree — or, once merged, `git revert` the merge
   commit of `chore/cleanup-xplat-deps-deprecations`.
2. `cd frontend && npm ci` — restores Vitest 2.1.9 and the Vite 5 subtree.
3. `cd backend && pip install -r requirements.lock.txt` — restores Starlette 1.6.0, httpx
   0.28.1 and httpcore 1.0.9. `httpx2`, `httpcore2` and `truststore` may stay installed.
4. Run `scripts/verify_rc_baseline.py` from the restored checkout; its baseline file
   carries the previous digests and reports 10 of 10.
5. Expect the three backend deprecation warnings and the ten `npm audit` findings to
   return. That is the state at `48abca5`.

`data/solaris_crm.db`, `data/uat/` and `backups/` were not written by anything in this
work and need no action.

That the UAT packs and review sheets hold no recorded result is a separate check, because
it is a property of the documents rather than of the code:

```bash
backend/.venv/Scripts/python scripts/verify_uat_blank.py
```

---

## 1. Why RC-UAT-3 was superseded

Phase 12 added a **third frontend application**. RC-UAT-3 was frozen against a build with
two shells — the Staff Portal and Public Tracking — and this one has three. The Customer
Account is fourteen routes a customer can open; the Staff Portal gained two approval
screens for an API that had none; and OD-41 added two exact-match filters to the
authenticated shipment list. The tested tree is not RC-UAT-3's in any of those places.

**The two drifts RC-UAT-3 carried are closed, by re-freezing rather than by changing
anything.** Its Alembic head was `e5623fcf8018` and the repository has been at
`6af30fcdd3a8` since Phase 10. Its UAT case count was 45 and `UAT_CASES.md` has held 49
since the role merge. Both are recorded here at their measured values, so from now on a
drift means something moved today.

RC-UAT-1, RC-UAT-2 and RC-UAT-3 are unchanged on disk and independently verifiable:

```bash
backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_1_BASELINE.json
backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_2_BASELINE.json
backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_3_BASELINE.json
```

Each reports its own drift. That is what superseded means, and the drift is the evidence.

## 2. The build

| | |
|---|---|
| Commit | `0b772e0125431b7d2d42aa09f9b88a80ad6f277f` (re-freeze); previously `48abca56d0ea7bd48e2f0f4ee06529bc07cdd408` |
| Branch | `chore/cleanup-xplat-deps-deprecations`, one commit on `ffa03ad`, which is `phase-12-customer-account-frontend` at sixteen commits from `bafbbc8` |
| Alembic head | `6af30fcdd3a8`, single head, `alembic check` green |
| Decision log | 117 records, `DEC-0001` … `DEC-0117`, no gap |
| Python / Node / npm / SQLite | 3.12.10 / 24.11.1 / 11.6.2 / 3.49.1 |
| `backend/requirements.lock.txt` | `2db64d6b56ab5d05c94a6fc04b2ae5294c20198b781f60a253dedb66b744c590` |
| `frontend/package-lock.json` | `e2c92eeb8777165683a994c6d07259999556b1b17f2bafa799ea0023f70e613f` |

**Both lock digests moved at the re-freeze and nowhere else.** Backend: Starlette 1.6.0 →
1.7.0; `httpx` + `httpcore` replaced by `httpx2` 2.13.1 + `httpcore2` 2.13.1 + `truststore`
0.10.4 (Starlette's test-client dependency; nothing in `app/` imports either name).
Frontend: Vitest 2.1.9 → 4.1.11, which removed `tinypool` 1.1.1 and the nested Vite 5.4.21 /
esbuild 0.21.5 subtree; Vite 6.4.3 → 6.4.4; `brace-expansion` and `source-map-js` patched.
`react-router` resolved at 6.30.6 both before and after; only the `package.json` floor
moved. The previous digests were `13741cf2…d695fc` and `4ab7a6de…f42e675d`, and the first
freeze's note still holds: Phase 12 itself added no dependency.

## 3. Test counts

| Suite | RC-UAT-3 | RC-UAT-4 | Note |
|---|---:|---:|---|
| Backend | 1,256 | **2,632** | 0 failed, 0 skipped, 0 warnings; 2,625 at the first freeze plus the 7 codec tests; re-measured at `0b772e0` |
| Frontend unit | 223 | **323** | 21 files, re-measured at `0b772e0` under Vitest 4 |
| Playwright | 149 | **259** | three runs at `fcd07a7`, 259 each, retries 0; re-measured at `0b772e0` (section 0) |
| Accessibility screen states | 32 | **62** | 7 public, 25 staff, 30 Customer Account |
| axe invocations | 64 | **124** | 62 states × 2 viewports |
| Staff UAT cases | 45 | **49** | executed: **0** |
| Customer Account UAT cases | — | **59** | executed: **0** |

The Playwright suite was run **twice consecutively** and then once more after clearing the
Vite cache. All three passed with 259, one worker, retries 0.

**At the first freeze two suites were measured at `fcd07a7` and carried forward**, because
no file under `frontend/` changed between `fcd07a7` and `48abca5`. **At the re-freeze
nothing is carried forward**: the cleanup changed both lockfiles, the test runner and the
router flag, so every suite was re-run at `0b772e0` (section 0).

### One defect this re-run found

A test fixture built a shipment reference as `SX-<route>-<uuid4().hex[:12]>`. The
unambiguous alphabet has no `0` and no `1`, so that reference parsed about **one time in
five**: the shipment could be listed and never opened by reference, and the failure
arrived wearing the product's own generic not-found. It has been latent since Phase 11,
and three consecutive full suites — including the 2,611-pass run this baseline was first
frozen on — had landed on the winning side of it.

Fixed in the fixtures, **not** in the parser: a reference space containing `0`/`O` and
`1`/`I` is one a customer reads out wrong over the telephone. DEC-0117, with eight guard
tests.

## 4. Route counts

| | Count |
|---|---:|
| Backend path/method pairs, total | 126 |
| — Staff API under `/api/v1` | 111 |
| — Customer Account under `/api/v1/account` | 10 |
| — of those, mutations | 7 |
| — of those, shipment reads | 2 |
| — Staff Customer Account review under `/api/v1/customer-account` | 8 |
| — Public Tracking under `/api/v1/public` | 2 |
| — health and non-API | 3 |
| — **provider webhook** | **0** |
| Frontend Customer Account routes | 14 |
| Frontend Staff Portal routes | 15 |
| Frontend Public Tracking routes | 3 |

**Seven Customer Account mutations, and not one of them touches a shipment**: register,
verify-email, resend, sign-in, sign-out, forgot password, reset password. The two shipment
routes are reads. There is still no route by which a customer can book, cancel, edit or
claim anything.

## 5. Field counts

| Schema | Fields |
|---|---:|
| `PublicTrackingResult` | **24** |
| `AccountShipmentListItem` | **17** |
| `AccountShipmentDetail` | **24** |
| Registration field allowlist | 43 keys |

The authenticated detail holds the same 24 values the public contract does, **re-declared**
field by field in its own module. Neither inherits from the other, and
`test_public_contract_unchanged.py` is untouched.

## 6. The filters, after OD-41

| Filter | Kind |
|---|---|
| `status_group` | closed vocabulary, four groups |
| `booked_from` / `booked_to` | bounded date range |
| `reference` | **exact** Solaris shipment reference (OD-41) |
| `route_group` | **exact** route vocabulary (OD-41) |

Free-text search is still declined, and OD-41 does not reopen it. An unknown reference, a
foreign one and a malformed one all produce the same empty page.

## 7. Accessibility

| | |
|---|---|
| Screen states audited | **62** |
| Viewports | 1280 × 800 and 375 × 812, **both**, for every state |
| axe invocations | **124** |
| Serious violations | **0** |
| Critical violations | **0** |
| Rules suppressed | **0** |

`EXPECTED_FINDINGS` is empty and a test fails if an entry stops matching anything, so a
suppression cannot outlive the finding it was written for.

**One serious finding was fixed rather than suppressed**: `link-in-text-block` — the
Customer Account's inline links were distinguished from the sentence around them by colour
alone. Inline links are underlined now.

> **This is not a human accessibility review.** No screen reader has been run against the
> Customer Account, no zoom above 100% has been tested, forced-colors mode has not been
> exercised, and only Chromium has been used. **OD-19 is open and no reviewer is
> assigned.**

## 8. The invariants that must not move

| Invariant | Value |
|---|---|
| Public tracking contract | **24 fields** |
| Production adapters registered | **0** |
| Integration resource host allowlist | **0** |
| Integration resource path-prefix allowlist | **0** |
| Tracking source modes | `manual`, `external_link` |
| `connected_api` | **excluded from the vocabulary** |
| Integration health | `not_configured` |
| Provider webhook routes | **0** |
| Public correlation header | absent |
| Provisional public carrier-link hosts | **9**, unchanged |

## 9. Human UAT

| | |
|---|---:|
| Staff pack cases | 49 |
| Staff pack executed | **0** |
| Customer Account pack cases | 59 |
| Customer Account pack executed | **0** |
| Review sheets | 5 |
| Review sheets completed | **0** |

**No human has executed any case in either pack, and no review sheet has been filled in.**
Every Evidence obtained, Result, Defect, Tester, Date and sign-off field is blank, checked
by `scripts/verify_uat_blank.py` rather than by eye.

**`Evidence` was one field and is now two.** It used to hold prewritten text naming what a
tester should collect, which a reader -- or a script counting non-blank cells -- could
mistake for a record of evidence obtained. It is now **`Evidence to capture`**, prewritten
and part of the case definition, and **`Evidence obtained`**, blank until a tester fills it
in. The review sheets draw the same line between *Content under review*, *Reviewer
response*, *Evidence obtained* and *Result / sign-off*. This was a UAT-record correction
only: no case step, expected result or application file changed, and RC-UAT-4's tested
application commit is still `48abca5`.

Four of the 59 Customer Account cases — `CA-PRF-01` … `CA-PRF-04` — are **out of scope**
rather than merely unexecuted: they depend on the *My information* and *Notification
preferences* screens, which the owner's Phase 12 instruction excluded by name.

## 10. Unresolved launch blockers

None of these is a development task. Each is an owner or reviewer action.

| # | Blocker | Decision |
|---:|---|---|
| 1 | No production email provider; data residency, an authenticated sending domain, and bounce and complaint handling all unaddressed | **OD-34** |
| 2 | No approved terms or privacy text. Both versions are placeholders that name themselves as placeholders | **OD-37** |
| 3 | Customer-facing English copy not reviewed. `REVIEW_customer_account_copy.md` is written and blank | **OD-39** |
| 4 | No accessibility reviewer assigned. 124 automated audits are not a human review | **OD-19** |
| 5 | Retention periods undecided, so no canonical deletion schedule exists | **OD-01 / OD-36** |
| 6 | Rate limiting is in-process and per-worker; more than one worker needs a shared store | **DEC-0006** |
| 7 | Staff MFA undecided. Customer MFA is deferred separately by OD-33 | **OD-17** |
| 8 | Secrets are not in a secret store | existing gate |
| 9 | Provider integration deferred: no adapter, no allowlisted host, no webhook | **DEC-0075**, OD-21 |

And still open, still constraining: **OD-22** — no linked return-shipment workflow, and
none was built.

## 11. The unexplained observation, restated

The intermittent first seen at RC-UAT-1 — `staffKeyboard.spec.js:212` on a blank rendered
page, once in seven runs, never reproduced — is **not** classified as fixed.

Three consecutive complete suites at this commit passed, 259 each. Earlier in the phase,
at an intermediate commit, two instances of the same class appeared: once as
`staffAccessibility.spec.js` failing to find a report heading that was present on every
other run, and once as the Vite dev server answering `ERR_CONNECTION_REFUSED` mid-run with
nothing in its log. Neither reproduced. Neither is explained. The failure-only diagnostic
capture added at RC-UAT-2 remains in place.

## 12. What this baseline does not say

It does not say the product works for the people who will use it. It says that a
particular tree, at a particular commit, measures a particular way, and that the same
measurements can be taken again by anyone who doubts them.

Whether a customer can register, wait, sign in and find their parcel — and whether an
Operations reviewer can read a disclosure preview and decide well from it — is what human
UAT is for, and it has not happened.
