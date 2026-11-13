# Pull request: cross-platform paths, patched dependencies, three deprecations cleared, RC-UAT-4 re-frozen

**Branch:** `chore/cleanup-xplat-deps-deprecations` → `main`
**Commits:** `0b772e0` (the cleanup), then the RC-UAT-4 re-freeze and the decision register
**Prepared:** 2026-10-11, for Ben. Nothing has been pushed or merged; this file is the text
to paste into the pull request and the checklist to work through before pressing merge.

---

## Description

### What this changes

**No feature.** No route, schema, migration, screen or wording changed. The branch answers
a third-party audit of the Phase 12 tree (run on Linux, Python 3.13, Node 20) that found
every suite green and raised three housekeeping items.

1. **Cross-platform.** Two Playwright helper files hard-coded the Windows interpreter path,
   so the end-to-end suite could only run on Windows. One module,
   `frontend/scripts/pythonInterpreter.mjs`, now resolves `Scripts/python.exe` or
   `bin/python` from its own location, and the three files that spawn the interpreter
   import it. Ten `scripts/*.py` docstrings name the Linux and macOS form. `.gitattributes`
   fixes LF line endings; the index already held every text file as LF, so there is no
   renormalisation diff.
2. **Dependencies.** `npm audit` went from 10 findings (2 critical, 3 high, 5 moderate) to
   2 moderate. Vitest 2.1.9 → 4.1.11 removed `tinypool` 1.1.1 and the duplicated Vite 5 /
   esbuild 0.21 subtree; Vite, `brace-expansion` and `source-map-js` patched. Backend:
   Starlette 1.6.0 → 1.7.0; `httpx` replaced by `httpx2` (Starlette's test-client
   dependency; nothing in `app/` imports either).
3. **Deprecations.** The backend run ended with three warnings, all from `.venv`; it now
   ends with none. The one with code behind it is `backend/app/core/sqlite_codecs.py`,
   which registers Python's four deprecated `sqlite3` date/datetime codecs transcribed, so
   stored bytes are identical before and after. Seven tests prove it. React Router's
   `v7_relativeSplatPath` future flag is on; `v7_startTransition` is deliberately not,
   because it breaks the report-filter checkboxes bound to `useSearchParams` (caught by
   Playwright, explained in a comment in `App.jsx`).

### What was reviewed

`0b772e0` against `ffa03ad`: 27 files, 3 of them application code. Verdict: **no
unintended functional change.** The detail is `docs/RC_UAT_4_BASELINE.md` §0.

### Evidence

| Gate | Result at `0b772e0` |
|---|---|
| `ruff check` / `ruff format --check` | clean, 295 files |
| Backend `pytest` | 2,632 passed, 0 failed, 0 skipped, 0 warnings |
| `eslint` | clean |
| Frontend unit | 323 passed, 21 files |
| `vite build` | succeeds |
| Alembic (disposable database) | 8 up, check clean, 8 down, 8 up, check clean |
| Playwright (`npm run e2e`) | 259 passed, 0 failed, one worker, retries 0, 10.0 minutes; scratch database and run directory removed, data/e2e empty afterwards |
| `npm audit` | 2 moderate, both `react-router` 6.30.6, neither reachable here |
| `verify_rc_baseline.py` | 10 of 10 after the re-freeze |

### The two residual audit findings

Both on `react-router` 6.30.6, both fixed only in 7.18.4 (a major).

* **GHSA-wrjc-x8rr-h8h6** (open redirect via backslash in `<Link>` / `useNavigate`,
  moderate). Needs an attacker-controlled string to reach a navigation target. None does:
  the only dynamic targets are a path this application wrote into history state (and
  prefix-checks before use), a fixed set of session destinations, and report links built
  server-side as literal `/…` paths. **Not exploitable in this setup.**
* **GHSA-337j-9hxr-rhxg** (constructor injection during SSR hydration, moderate, CVSS 6.1).
  Needs server-side rendering with a data router. This application is client-rendered
  with `createRoot` and uses no data router. **Not exploitable in this setup.**

React Router 7 is assessed in `docs/DECISION_REGISTER.md` §4.4 as post-launch work.

### RC-UAT-4

Re-frozen on `0b772e0`, **identifier kept**, because what a tester sees and does is
unchanged. `docs/RC_UAT_4_BASELINE.json` carries the new lock digests with the previous
pair beside them, a re-freeze history, the audit assessment, the gate evidence, known
risks and a rollback procedure. No human has executed a UAT case against either
measurement.

### Rollback

No migration; the Alembic head is `6af30fcdd3a8` on both sides; no database file is
touched. Revert the merge commit (or check out `ffa03ad`), then `npm ci` in `frontend/`
and `pip install -r requirements.lock.txt` in `backend/`. The previous warnings and audit
findings return; that is the expected state. Full steps: `docs/RC_UAT_4_BASELINE.md` §0.

### Not in this PR

ESLint 10 (blocked by `eslint-plugin-react`'s peer range), React Router 7 (a major that
changes the tested tree), `v7_startTransition` (needs the report filters moved to local
state first), and the command examples in `docs/*.md`, which still show the Windows path.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Merge checklist

Work through this in order. Each line is something to *do* or *confirm*, not something to
read.

### Before merging

- [ ] The pull request targets `main` from `chore/cleanup-xplat-deps-deprecations` and
      contains exactly the commits listed at the top of this file (`git log main..HEAD
      --oneline`).
- [ ] `git diff main...HEAD --stat` shows no file under `data/`, `backups/`, or any `.env`.
- [ ] `git diff main...HEAD -- backend/app frontend/src` shows only `core/db.py`,
      `core/sqlite_codecs.py` and `app/App.jsx`.
- [ ] On the branch, from the repository root:
      `backend/.venv/Scripts/python scripts/verify_rc_baseline.py` prints **10 of 10**.
- [ ] `backend/.venv/Scripts/python scripts/verify_uat_blank.py`,
      `scripts/verify_owner_decisions.py` and `scripts/verify_decision_log.py` each end
      with "Every check passed" (or the blank-field equivalent).
- [ ] You have read `docs/RC_UAT_4_BASELINE.md` §0 and accept the two residual
      `npm audit` findings as unreachable. If you do not, stop: the alternative is the
      React Router 7 sprint in `docs/DECISION_REGISTER.md` §7 first.
- [ ] You accept the one Vitest 4 consequence: Testing Library's async ceiling is 5 s in
      `frontend/tests/setup.js` (no assertion changed).
- [ ] Optional but recommended on a second machine (Linux or macOS): `cd backend && pip
      install -e ".[dev]" && python -m pytest -q`, then `cd frontend && npm ci && npm
      test && npm run e2e`. This is the cross-platform claim being checked, not the code.

### Merging

- [ ] Merge with a merge commit (not squash), so `0b772e0` keeps the SHA that
      `docs/RC_UAT_4_BASELINE.json` names in `measured_at_commit`. If you squash, the
      baseline must be re-measured at the squashed SHA before any tester starts.
- [ ] Do not rebase the branch first; same reason.

### After merging

- [ ] On `main`, run `scripts/verify_rc_baseline.py` once more: **10 of 10**.
- [ ] Every developer re-installs: `cd frontend && npm ci` (Vitest 4) and `cd backend &&
      pip install -e ".[dev]"` (Starlette 1.7, `httpx2`). An un-refreshed backend venv
      still works but prints the three deprecation warnings again.
- [ ] If Playwright has never been run on the machine: `cd frontend && npx playwright
      install chromium`. The cleanup found this environment gap; it is not a code change.
- [ ] Delete the branch locally and on the remote once `main` carries the merge commit.
- [ ] Human UAT can start against RC-UAT-4 at `0b772e0`. Until a tester has executed a
      case, keep `main` free of application changes; anything that touches
      `backend/app` or `frontend/src` means a re-freeze (RC-UAT-5).

### If something is wrong after merging

- [ ] `git revert -m 1 <merge commit>` on `main`, then `npm ci` and
      `pip install -r requirements.lock.txt`. No database action. Expect the previous
      warnings and audit findings to return.
