# 23 — Fix pack: owner answers to the RC-UAT-18 follow-ups, and the UAT Python fix → RC-UAT-19

**Date:** 2026-10-22 · **Branch:** `fix/owner-answers-rc17` (on RC-UAT-18, `8b954e4`) ·
**Migration:** `e6b1c4a8d2f3` (from `d4f7a2c9e1b8`; one new table `invoice_draft_tax`, nothing
existing altered) · **Decisions:** DEC-0223 to DEC-0226 · **Owner decisions:** OD-91 to OD-101
(Louis Tong, on Ben's behalf) · **Scope:** air only

Nothing is pushed or merged. Test data only; email is test capture only.

## 1. The UAT blocker: START_UAT.bat could not find Python (DEC-0226)

Louis's PC has Python installed, but the launcher only tried `py -3.12`, `py -3.13`, `py -3.11`
and `python` and accepted 3.11 to 3.13. It now looks in `UAT_PYTHON` (quotes tolerated), `py
-0p`, the standard install folders (`%LOCALAPPDATA%\Programs\Python\Python3*`,
`%LOCALAPPDATA%\Python\pythoncore-3*`, `%ProgramFiles%\Python3*`, `%ProgramFiles(x86)%\Python3*`,
`C:\Python3*`) and `PATH`; skips `WindowsApps` (the Microsoft Store alias); accepts 64-bit 3.11 to
3.14 (prefers 3.12); on failure lists every Python seen (version, path, reason) with the fix
steps; rebuilds a `backend\.venv` whose Python is gone; no longer treats stderr output as failure
(PowerShell 5.1). `uat\uat.ps1 python` prints the list without starting anything.

**Python 3.14: supported.** All 57 pinned packages have Windows wheels for 3.14; a venv built from
`requirements.lock.txt` with the official CPython 3.14.9 (python.org NuGet package, signature
verified: Python Software Foundation) passed a 434-test backend subset; the RC-UAT-19 zip is also
verified end to end with 3.14 (§3). **Python 3.15: not supported yet** -- httptools 0.8.0,
MarkupSafe 3.0.3, pydantic_core 2.46.5, PyYAML 6.0.3 and watchfiles 1.2.0 have no 3.15 wheel
(pydantic_core would need a Rust build); the launcher says so and falls back to another Python.

## 2. Owner answers (OD-91 to OD-101)

| # | Answer | Change |
|---|---|---|
| OD-91 (Q-P1) | Carrier tracking links stay visible; hide the vendor name around them | Carrier links (UPS, Canada Post …) shown with a generic label; stored labels never reach customers; a link whose host names the vendor stays hidden (stand-in P-5) |
| OD-92 (Q-P2) | Generic customer-facing leg names | "Master Tracking" (Vietnam to the vendor's Canadian warehouse), "Last Mile Tracking" (onward); at most one link per name (`carrier_links`); Vietnamese proposed for review (P-4) |
| OD-93 (F-1) | Costume jewellery (HCM row 27): manual quote input | New basis `manual_amount`: staff enter the vendor's quoted VND for the line (stand-in P-3); finalising blocked until entered; amount validated (rounded to the cent, > 0, capped); a line still priced per kg from the old reading blocks until re-entered |
| OD-94 (F-3) | Tax on draft invoices: all-in, auto-filled, confirmed | Drafts open at GST/HST 13 % included (backed out: tax = total × 13 / 113); a confirmation (with the totals and mode the screen showed) is required for Save and Send; staff may change rate and mode; PDFs and document say "Prices include GST/HST 13 %". Pending Louis: P-1 rate, P-2 included vs added |
| OD-95, OD-98 | Quotes with an issued invoice / on a booked master do not expire | Unchanged; retention with minimal storage; Admin manual delete logged as a future item (P-7), not built |
| OD-96, OD-97, OD-99, OD-100, OD-101 | Confirmed as built | Unchanged |

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,397 passed, 1 skipped; 3 failed: the environmental `test_e2e_safety` (worktree-only), and two tests still pinning the public field count at 24 (`test_phase5b_seam_and_contracts`, `test_uat_round_12`) -- updated to 25 with `carrier_links` named, registered as AS-36 and AS-37, and rerun green with the register guard (189 passed) |
| ruff check / format | clean (346 files) |
| eslint, vitest | clean; 757 passed |
| vite build | built |
| Playwright (run alone) | 319 passed (a first run caught `accountQuotes.spec.js` sending without the GST/HST confirmation; fixed and rerun) |
| Alembic on a scratch database | upgrade head → `e6b1c4a8d2f3`, check clean, downgrade -1, upgrade |
| Verifiers | decision log, owner decisions (101), UAT blank (air pack 63) |
| Python 3.14.9 | venv from the pinned lock, 434-test backend subset passed |

Independent tester: 6 golden tests (`test_rc19_golden.py`); one product defect (row-27 amounts
rounding to zero or overflowing) fixed. Independent reviewer: no high finding; launcher (quoted
`UAT_PYTHON`, stderr under PowerShell 5.1), single tracking link, tax confirmation echo and
re-import of row-27 lines fixed, and the low findings. Superseded assertions registered as AS-27
to AS-37.

## 4. Not done

The Admin manual delete of retained quote records (future, P-7). The manual Issue invoice path
(no draft) still adds tax on top (P-6). Python 3.15 waits for the pinned packages (P-8).
