# RC-UAT-2 — the release-candidate baseline in force

> ## ⚠ THIS IS NOT A PRODUCTION RELEASE
>
> `RC-UAT-2` is a **pre-release identifier**. It carries no production release number and
> no production-ready label. It means one thing: *this is the exact build handed to human
> UAT.* It is not evidence that the application works for the people who will use it.
>
> Production deployment remains **prohibited** (OD-20: nobody is yet authorised to perform
> one).

---

## 1. What is frozen

| | |
|---|---|
| Identifier | `RC-UAT-2` |
| Supersedes | `RC-UAT-1`, frozen 2026-09-14 and preserved unchanged |
| Branch | `phase-6-release-candidate-uat` |
| Measured at commit | `21e01a71c75ca389a4a9ca5d10035466882437c1` |
| Phase 5B closure commit | `8621b9e66b8eb7a69074061d583afc71d0b5e6de` |
| Alembic head | `e5623fcf8018` |
| Frozen | 2026-09-15 |

Machine-readable copy: `docs/RC_UAT_2_BASELINE.json`. That file, not this one, is what the
verification command reads.

### Why RC-UAT-1 was superseded

**No application code changed.** Not one file under `backend/app` or `frontend/src` is
different. What changed is the end-to-end harness:

| Change | Why it forced a new candidate |
|---|---|
| `frontend/tests/e2e/diagnostics.js` and the one-line import in each spec | Failure-only diagnostic capture, added so the unexplained blank page is diagnosable if it returns |
| `frontend/tests/e2eDiagnostics.test.js` | Pins the redaction promise; raises the frontend unit count from 206 to 219 |
| `frontend/tests/e2e/axeHelpers.js` | The "our origin" allowlist was hard-coded to port 5173 |
| `frontend/tests/e2e/zzRateLimit.spec.js` | The cleanup drain inferred a full window from a probe that cannot detect one |

A baseline is the tree that was tested. The tree that was tested is no longer RC-UAT-1's,
so the identifier moved rather than the numbers underneath it.
`docs/RC_UAT_1_BASELINE.md` is unchanged apart from a supersession notice, and is still
verifiable:

```bash
backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_1_BASELINE.json
```

### Toolchain

| | |
|---|---|
| Python | 3.12.10 |
| Node | 24.11.1 (npm 11.6.2) |
| SQLite | 3.49.1 |

Unchanged from RC-UAT-1, as are both dependency-lock digests.

### Counts

| | | |
|---|---|---|
| Backend tests | 1244 passed, 0 skipped | unchanged |
| Frontend unit tests | 219 passed (16 files) | 206 + 13 redaction tests |
| Playwright tests | 149 passed, 0 skipped, 0 failed | unchanged |
| Accessibility audit calls | 34 (26 staff, 8 public) | carried forward, not re-measured |
| Audited viewports | 2 — 1280×800 and 375×812 | unchanged |
| UAT cases | 45, **0 executed** | unchanged |

### Invariants — the things that must not move

| | |
|---|---|
| Public tracking contract | exactly **24** fields |
| Production adapters registered | **0** |
| Integration resource host allowlist | **0** |
| Integration resource path-prefix allowlist | **0** |
| Tracking source modes | `manual`, `external_link` — `connected_api` refused |
| Integration health | `not_configured` |
| Provider webhook routes | **none exist** |
| Public correlation header | **absent** — the staff API carries `X-Correlation-ID`, the public API does not |

---

## 2. Verifying the baseline

```bash
backend/.venv/Scripts/python scripts/verify_rc_baseline.py
```

Exit status 0 means every check matches; 1 means something drifted, and the output names
what. `--json report.json` writes the full report. `--baseline <path>` checks a different
baseline file — that is how RC-UAT-1 stays verifiable.

It deliberately does not assert test counts, for the reason RC-UAT-1 gave and this
candidate demonstrates: adding a guard changes them.

---

## 3. Stability evidence behind this freeze

RC-UAT-1 recorded one unexplained failure — `staffKeyboard.spec.js:212`, a blank rendered
page during run 5 of 7. It was investigated rather than dismissed. It **did not
reproduce**:

| Run | Scope | Result |
|---|---|---|
| A ×25 | The exact test, `staffKeyboard.spec.js:212`, consecutively, one worker | **25 / 25 passed** |
| B ×12 | The complete `staffKeyboard.spec.js`, consecutively | **12 / 12 passed** (10 tests each) |
| C1 | Complete Playwright suite, correctly cleaned scratch environment | **149 passed, 0 failed** |
| C2 | Complete suite again, immediately, same environment | **149 passed, 0 failed** |
| D1 | Complete suite from a cold Vite start (cache removed) | **149 passed, 0 failed** |

`retries` is 0 throughout, one worker, no sleep added to any test. 37 consecutive
repetitions of the failing test and its file, plus three complete suites, produced no
failure and no diagnostic artifact.

**It is classified as an unresolved intermittent observation, not a fixed defect.** No
cause was found, nothing was changed that would have addressed it, and 37 repetitions
cannot prove absence. What changed is that a recurrence is now diagnosable in one shot —
see `PROJECT_STATUS.md` section 13.

### Three failures that did reproduce, and what they were

None of them is the blank page; all three are recorded because they cost real time and
would cost a UAT operator the same.

| Observed | Cause | Status |
|---|---|---|
| Sign-in failed on a repeated staff run, page showing a danger banner | The suite was re-run 9 times inside the 300 s login window; production default is 8 attempts | Operator error. The stack must be started with the raised limits `docs/OPERATIONS.md` section 8 requires; `docs/UAT/ENVIRONMENT.md` now says so |
| Every accessibility test failed naming a self-hosted font as an external resource | `axeHelpers` hard-coded `http://localhost:5173` as "our origin" | **Fixed.** Derived from `E2E_BASE_URL` |
| The second of two consecutive complete suites failed its first public lookups on 429 | The cleanup drain returned early when its first probe answered 404, leaving the deliberate burst inside the window | **Fixed.** The spec that exhausts the limiter now says so instead of letting a probe guess |

---

## 4. Provisional dispositions in force for RC-UAT-2

**Temporary UAT dispositions, not owner decisions and not production approval.** The
register is `docs/OWNER_DECISIONS.md`; a disposition is counted there as **open**.

| Item | Disposition for RC-UAT-2 | Decision |
|---|---|---|
| `PUBLIC_CARRIER_LINK_HOSTS` | **9 hosts retained**, so manual/external-link tracking can be validated | OD-07 — open for production |
| Integration resource host allowlist | **empty** | remains empty |
| Integration resource path-prefix allowlist | **empty** | remains empty |
| `PUBLIC_HELP_URL` | **empty** — the contact link is omitted, not invented | OD-06 — open |
| MFA | **not implemented**, not decided | OD-17 — open |
| Retention deletion | disabled | OD-01 — open |
| Proxy-header trust | disabled | DEC-0087 |
| Production deployment | prohibited | OD-20 — open |
| **Return shipment records** | **no workflow creates one; none in the dataset** | **OD-22 — open** |

The nine carrier hosts are **retained for UAT, not reviewed or approved for production**.

---

## 5. What this baseline does not prove

Everything in `PROJECT_STATUS.md` section 10C.8 still stands, and RC-UAT-1 section 5 still
reads true: no disabled person has used this application, no screen reader has been run
against it, no label has been printed or scanned, the Vietnamese wording is unreviewed in
both the staff catalogue and the customer templates, and **no UAT case has been executed by
anyone**.

Added by this candidate: **the blank-page observation is not explained**, and no return
shipment record has ever existed in this system.
