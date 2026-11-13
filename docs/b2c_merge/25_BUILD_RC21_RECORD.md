# 25 — Build run: every remaining feature → RC-UAT-21

**Date:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17` (on RC-UAT-20, `16d80fc`) ·
**Migrations:** `a1c3e5f7b9d2` (imports), `b2d4f6a8c1e3` (accounts), `c3e5a7b9d2f4` (quote delete,
retention) -- new tables only, nothing existing altered · **Decisions:** DEC-0230 to DEC-0233 ·
**Owner decisions:** OD-109 (P-9 stand-in, pending Ben), OD-110 (Ben's build direction) ·
**Scope:** air only

Ben's direction (2026-10-24): build every remaining feature now; testing and fixes come once
staff use it; use safe stand-ins and record each as an open question. Not started, waiting for
Ben: returns (OD-22), staff MFA (OD-17), production email (OD-34), provider sync (OD-21).
Nothing is pushed or merged. Test data and synthetic fixtures only; email is test capture only.

## 1. What was built

| # | Feature | Summary |
|---|---|---|
| 1 | Packaging | `uat_package` names no release: the build derives `RC-UAT-<N>`, the folder and the application commit from the newest `docs/RC_UAT_<N>_BASELINE.json`; payload placeholders filled; refuses an uncommitted payload or an unfilled placeholder; `verify_uat_zip.ps1` checks the newest zip and finds its folder; the smoke GST/HST check follows Ben's route rule (zero-rated international invoice, domestic drafts backed out at the destination province's rate) |
| 2 | P-9 stand-in (OD-109, DEC-0232) | Customer quotes: domestic "GST/HST included" at the destination province's rate; international zero-rated; total label "Tổng cộng" kept |
| 3 | Phase A (DEC-0230) | Shipment CSV import and legacy history baseline, dry-run first (same user, same bytes, unused, under 24 h), customer-import limits, ISO dates, formula-safe, no quote/invoice/email/notification from an import; legacy records staff-only, outside finance and operational lists, whole-baseline void, moved on customer merge |
| 4 | Phase B (DEC-0231) | Customer and staff change password (sessions rotated, others signed out); customer email change verified at the new address, notice to the old one at request and on confirm, single-email rule re-checked at confirm, cancelled by a password change or reset; Admin reinstatement of a deactivated account (back to pending approval when its customer was merged) |
| 5 | Phase D (DEC-0233) | Admin soft delete and restore of eligible old quote versions (reason, audit; refused when tied to an issued invoice, a live draft or an accepted offer); retention-deletion machinery with configurable periods, a dry-run report and a hand-run worker, **disabled by default** |

Open questions: `19_OWNER_QUESTIONS.md` §0000 (P-9 and the stand-ins A-1 to A-14, B-1 to B-14,
D-1 to D-12). UAT cases: the "Build of 2026-10-24 (RC-UAT-21)" group and Part 9 of the script.

## 2. Evidence

| Gate | Result |
|---|---|
| ruff | clean (382 files) |
| alembic | up, current, check, down, up -- head `c3e5a7b9d2f4` |
| verifiers | decision log, owner decisions (OD-01 to OD-110), UAT blank (49/60/88) -- pass |
| eslint, vitest | clean; 825 passed |
| build | OK |
| backend pytest | 4,852 passed, 1 skipped; 1 worktree-only failure (`test_e2e_safety`, environment, as in RC-UAT-19 and -20) |
| Playwright | 325 passed (full suite run alone, Vite on port 5473) |
| tester | 11 golden tests (`test_rc21_golden.py`); the smoke route-tax rule passed against a reset UAT database |
| reviewer | 2 high, 4 medium, 7 low findings -- all fixed before commit |

Playwright note: three earlier full runs on the default port each lost one different account
spec to `ERR_CONNECTION_REFUSED` on a Vite module request (blank page); each spec passed alone,
and the full run on another port passed. Recorded as an environment flake, not a product defect.

## 3. Not done

Returns, staff MFA, production email and provider sync (waiting for Ben). Retention stays off until
periods are decided (OD-01, OD-36). A staff re-link path for an account reinstated to pending
approval after a merge (B-13).
