# RC-UAT-1 — the frozen release-candidate baseline

> ## ⚠ SUPERSEDED BY `RC-UAT-2` ON 2026-09-15
>
> **Nothing below has been changed.** Every measurement, count and invariant is exactly as
> it was recorded on 2026-09-14, and the commit this was measured at is unchanged. This
> notice is the only addition, because a superseded baseline that quietly acquires new
> numbers is worse than no baseline at all.
>
> **Why it was superseded.** The pre-UAT gate review added failure-only diagnostic capture
> to the end-to-end harness (`frontend/tests/e2e/diagnostics.js`, plus the one-line import
> change in each spec and a unit test for its redaction). That changes the tested tree, so
> the tree handed to human UAT is no longer the tree measured here. See
> `docs/RC_UAT_2_BASELINE.md` and `PROJECT_STATUS.md` section 13.
>
> **It is still verifiable.** The drift guard can re-check this baseline directly:
>
> ```bash
> backend/.venv/Scripts/python scripts/verify_rc_baseline.py --baseline docs/RC_UAT_1_BASELINE.json
> ```
>
> The unexplained `staffKeyboard.spec.js:212` failure recorded in section 4 stays in the
> record. It was investigated rather than discarded; what was found is in
> `PROJECT_STATUS.md` section 13.

> ## ⚠ THIS IS NOT A PRODUCTION RELEASE
>
> `RC-UAT-1` is a **pre-release identifier**. It carries no production release number and
> no production-ready label. It means one thing: *this is the exact build handed to human
> UAT.* It is not evidence that the application works for the people who will use it, and
> it may not be quoted as such.
>
> Production deployment remains **prohibited** (OD-20: nobody is yet authorised to perform
> one).

---

## 1. What is frozen

| | |
|---|---|
| Identifier | `RC-UAT-1` |
| Branch | `phase-6-release-candidate-uat` |
| Measured at commit | `ee14523c258122a5ea90b28ccdf10b1ed0ed38fa` |
| Phase 5B closure commit | `8621b9e66b8eb7a69074061d583afc71d0b5e6de` |
| Alembic head | `e5623fcf8018` |
| Frozen | 2026-09-14 |

The machine-readable copy is `docs/RC_UAT_1_BASELINE.json`. That file, not this one, is
what the verification command reads.

### Toolchain

| | |
|---|---|
| Python | 3.12.10 |
| Node | 24.11.1 (npm 11.6.2) |
| SQLite | 3.49.1 |

### Dependency locks

| File | SHA-256 |
|---|---|
| `backend/requirements.lock.txt` | `13741cf2dc1c344528475a9ea9a4fba94be05c4fa84f56bf8e6ebba595d695fc` |
| `frontend/package-lock.json` | `4ab7a6dee7d7eb22c622099c80fb5162788665445b29ce4497a1e26ef42e675d` |

### Counts

| | |
|---|---|
| Backend tests | 1244 passed, 0 skipped |
| Frontend unit tests | 206 passed (15 files) |
| Playwright tests | 149 passed, 0 skipped, 0 failed |
| Accessibility audit calls | 34 (26 staff, 8 public) |
| Audited viewports | 2 — 1280×800 and 375×812 |
| UAT cases | 45, **0 executed** |

### Invariants — the things that must not move

| | |
|---|---|
| Public tracking contract | exactly **24** fields |
| Production adapters registered | **0** |
| Integration resource host allowlist | **0** |
| Integration resource path-prefix allowlist | **0** |
| Tracking source modes | `manual`, `external_link` — `connected_api` refused |
| Integration health | `not_configured` |

---

## 2. Verifying the baseline

```bash
backend/.venv/Scripts/python scripts/verify_rc_baseline.py
```

Exit status 0 means every check matches; 1 means something drifted, and the output names
what. `--json report.json` writes the full report.

The script re-measures the four invariants the phase brief names, plus the Alembic head
and both lock digests. It makes no network request, starts no server, and writes nothing
unless `--json` is given.

**It deliberately does not assert test counts.** They change whenever a test is added —
including by adding a guard — so asserting them would make the guard fail for the one
reason that is not a regression. The counts above are re-measured by running the suites,
which is the only honest way to confirm them.

The same four invariants are *also* asserted inside the backend suite, in
`backend/tests/test_phase5b_seam_and_contracts.py`, so drift fails a normal test run as
well as this command. No new test was added for the baseline, precisely so the counts
recorded above remain the counts a fresh checkout measures.

---

## 3. Provisional dispositions in force for RC-UAT-1

These are **temporary UAT dispositions**, not owner decisions and not production approval.
The owner-decision register holds the open questions.

| Item | Disposition for RC-UAT-1 | Decision |
|---|---|---|
| `PUBLIC_CARRIER_LINK_HOSTS` | **9 hosts retained**, so manual/external-link tracking can be validated | OD-07 — open for production |
| Integration resource host allowlist | **empty** | remains empty |
| Integration resource path-prefix allowlist | **empty** | remains empty |
| `PUBLIC_HELP_URL` | **empty** — the contact link is omitted, not invented | OD-06 — open |
| MFA | **not implemented**, not decided | OD-17 — open |
| Retention deletion | disabled | OD-01 — open |
| Proxy-header trust | disabled | DEC-0087 |
| Production deployment | prohibited | OD-20 — open |

The nine carrier hosts are **retained for UAT, not reviewed or approved for production**.
Before launch the owner must review each exact hostname, any permitted subdomains,
redirect behaviour, and required path restrictions.

---

## 4. Evidence behind the freeze

The Phase 5B closure run reported "149 passed, 0 failed". It did not reproduce, and the
failure was in test cleanup rather than the product. Two harness defects were found and
corrected on this branch before the freeze; both are recorded in `PROJECT_STATUS.md`
section 12 and in the commit messages of `71dd3f1` and `e962376`.

Runs performed against a scratch database and a scratch stack, after the correction:

| Run | Scope | Result |
|---|---|---|
| 1 | Focused rate-limit spec, fresh stack, cold start | 4 passed |
| 2 | Focused spec against a deliberately exhausted limiter (`Retry-After: 54`) | 4 passed in 242 s, inside the 363 s hook budget |
| 3 | Cold start, Vite cache cleared | 4 passed |
| 4 | Complete Playwright suite | **149 passed, 0 skipped, 0 failed** |
| 5 | Complete suite immediately again | 1 failed — see below |
| 6 | Complete Playwright suite | **149 passed, 0 skipped, 0 failed** |
| 7 | Complete suite immediately again | **149 passed, 0 skipped, 0 failed** |

Run 5 recorded one failure, `staffKeyboard.spec.js:212` "label printing is reachable from
the keyboard", on a **blank rendered page** with no backend error and no Vite error in
either log. It did not reproduce: the same test passed three times out of three in
isolation immediately afterwards, and the two complete suites that followed both passed.
It is recorded here rather than discarded, and it is **not** claimed to be understood —
a transient client-side render failure during back-to-back runs is the description, not a
diagnosis.

`retries` is 0 in `playwright.config.js`, so Playwright cannot report a "flaky"
designation; the absence of one is therefore not evidence of stability, and the
consecutive-run results above are what the claim rests on.

Backend 1244 passed and frontend 206 passed were re-measured at the baseline commit. The
backend count rose from 1206 by the 38 tests covering the production refusals for UAT
credentials, which are part of this release candidate.
Repository lint (`ruff check .`, `ruff format --check .`) and `eslint .` are clean.

---

## 5. What this baseline does not prove

Everything in `PROJECT_STATUS.md` section 10C.8 still stands. In particular: no disabled
person has used this application, no screen reader has been run against it, no label has
been printed or scanned, the Vietnamese wording is unreviewed in both the staff catalogue
and the customer templates, and **no UAT case has been executed by anyone**.
