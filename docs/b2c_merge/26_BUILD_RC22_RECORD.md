# 26 — Build RC-UAT-22: orphaned accounts, the Playwright flake, honest gates

**Date:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17` (on RC-UAT-21, `d25df41` / app
`be7d2df`) · **Migration:** `d4f6b8c0e2a5` (one new table, nothing existing altered) ·
**Decision:** DEC-0234 · **Owner questions:** B-13 built; stand-ins B-15 to B-20 ·
**Scope:** air only

Nothing is pushed or merged. Test data and synthetic fixtures only; email is test capture only.
Not started, waiting for Ben: returns (OD-22), staff MFA (OD-17), production email (OD-34),
ShipStation / provider sync (OD-21); retention stays off (OD-01, OD-36). One-page view:
`BUILD_STATUS.md`.

## 1. What was built

| # | Item | Summary |
|---|---|---|
| 1 | B-13 (DEC-0234) | **Customer accounts → Accounts needing a customer** (Admin only, the reinstatement permission): accounts approved once that hold no link and no pending proposal -- typically reinstated after their customer was merged or archived. **Re-link** to a named customer (suggestion: the merge survivor; approval's target rules; no customer already holding a link) after previewing and acknowledging the history the link opens (fingerprint-checked), applying the single email rule, through the approval's link constructor and a guarded `active` writer; or **Close** (deactivation, reason `orphan_closed`, reversible by reinstatement). Each action is a `customer_account_relinks` row and an audit event; reading the list and a preview are audited. Routes `GET /api/v1/customer-account/identities-orphaned`, `GET …/identities/{ref}/relink-preview`, `POST …/identities/{ref}/relink`, `POST …/identities/{ref}/close-orphan` |
| 2 | Playwright blank-page flake | Root cause: the harness started Vite without `--host`, so on Windows it listened on `::1` only, while Chromium resolves `localhost` itself and, when its periodic IPv6 probe says no, connects over IPv4 -- refused, one module missing, a blank page, a different spec each run. Fix: `run_e2e.mjs` binds both servers to the literal `127.0.0.1` and gives the browser that same origin; `diagnostics.js` probes the host of `E2E_BASE_URL`. No name is resolved anywhere in a run |
| 3 | `test_e2e_safety` in worktrees | The test required `data/solaris_crm.db` to exist and failed in every worktree, which has none. It now asserts the property itself -- the development database is unchanged, and absent before means absent after -- as its UAT twin already did. Passes in the main checkout and in worktrees |
| 4 | Modal height | Found by the new browser test: a dialog taller than the window had its buttons out of reach. Dialogs are now capped at the window height and their body scrolls (`ui.css`); only dialogs taller than the window change |
| 5 | Docs | `BUILD_STATUS.md` (built vs held, phase names); `UAT-BLD-18`, `-19` and Ben's script step 41; air pack 90 cases; `UAT-BLD-13` now points to `-18` |

**Phase names.** Plan 16's phases are numbered 14 to 17, all done. A, B and D were the item
labels of the RC-UAT-21 brief; no Phase C or E to H is defined anywhere in the repository (see
`BUILD_STATUS.md`).

## 2. Evidence

| Gate | Result |
|---|---|
| ruff | clean (386 files formatted) |
| alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database -- head `d4f6b8c0e2a5`, no drift |
| verifiers | decision log, owner decisions, UAT blank (air pack 90) -- pass |
| eslint, vitest | clean; 835 passed (10 new in `rc22AccountRelink.test.jsx`) |
| build | OK |
| backend pytest | 4,881 passed, 1 skipped, run in six foreground chunks; `test_e2e_safety` passes in this worktree. One intermittent failure, see §3 |
| Playwright | full suite on port 5173 (browser at `127.0.0.1:5173`), two runs in a row after the fix: **326 passed, then 326 passed** (13.5 and 13.4 min), no failure, no retry |

## 3. Known issues

* `test_phase14_golden.py::test_document_deep_scan_is_customer_safe` failed once inside its
  chunk and passed on the immediate rerun of the same chunk and alone. Nothing it exercises
  changed in RC-UAT-22, and the leak list was not captured, so the cause is not known. Logged
  here rather than retried until green; if it recurs, the assertion message names the field.
* B-13 remains partly open: whether reinstatement should instead be refused outright after a
  merge (`19_OWNER_QUESTIONS.md` §0000).

## 4. Not done

Returns, staff MFA, production email, ShipStation / provider sync; enabling retention.
