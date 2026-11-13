# 24 — Fix pack: Ben's answers of 2026-10-23 and UAT bug fixes → RC-UAT-20

**Date:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17` (on RC-UAT-19, `f90927a`) ·
**Migration:** `f7c2d9e3a1b5` (from `e6b1c4a8d2f3`; new tables `tax_rates` (seeded),
`invoice_draft_tax_route`, `fee_line_manual_prices`; nothing existing altered) · **Decisions:**
DEC-0227 to DEC-0229 · **Owner decisions:** OD-102 to OD-108 (Ben) · **Scope:** air only

Nothing is pushed or merged. Test data only; email is test capture only.

## 1. What changed

| # | Ask | Change |
|---|---|---|
| 1 (OD-102) | GST/HST by route, replacing the 13 % stand-in | International (one end outside Canada) auto-fills 0 % (zero-rated; documents say "Zero-rated (0 %)"). Domestic auto-fills tax included and backed out at the destination province's rate from the new `tax_rates` table (ON 13, NS 14, NB/NL/PE 15, others 5 % GST), province from the recipient postal code first, then the address text; unknown means staff choose. Admin edits the table (Settings → GST/HST rates, audited). Staff may change the rate; the tick stays required. Directly issued invoices unchanged (OD-106) |
| 2 (OD-103) | Costume jewellery: cost and price | Staff enter the vendor's VND cost and the customer CAD price, no defaults; finalising blocked until both; the charge is exactly the price (no markup); negative-margin rule still applies |
| 3 (OD-104 to OD-107) | Decisions | Vietnamese leg names approved; vendor-addressed links stay hidden; direct invoices unchanged; Admin delete later |
| 4 | Payment date shifted back a day | Stored and shown as a plain date end to end (offsets ignored); "not in the future" and the M+7 lock judged by that date; legacy rows keep their old local date |
| 5 | Download before the tax tick | Refused (422 `tax_unconfirmed`) until the tick is saved for the current revision, like Send; read-only users see a neutral message |
| 6 | Final delivery leg provider; leg labels | The vendor provider is offered on every leg type including final delivery; staff legs show the generic "Master Tracking" / "Last Mile Tracking" label (never a vendor or carrier name), as the customer views do |
| 7 | "39 tariff warnings" not findable | Settings → Tariffs → Tariff versions → View shows the version's warnings (39 for the seeded tariff: 35, 2, 1, 1 by kind) with the 3 owner-confirmed price steps listed apart |
| 8 (OD-108) | Keep wording | "Tổng cộng" with the tax-on-invoice note, and "Ghi chú từ Solaris Express", pinned by test |
| 9 | UAT script | Part 8 and cases UAT-OWN-28 to -35; earlier tax, costume-jewellery and tariff-warning steps corrected; the UAT seed adds three Canada-to-Canada shipments (NS, NB, unknown province) with drafts, on their own master, for UAT only |

New open questions P-9 (domestic quote wording vs backed-out tax) and P-10 (no domestic service
to quote today) and the stand-ins R-1 to R-14 are in `19_OWNER_QUESTIONS.md` §000.

## 2. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,622 passed, 1 skipped; 1 failed, the environmental worktree-only `test_e2e_safety` |
| ruff check / format | clean (356 files) |
| eslint, vitest | clean; 795 passed |
| vite build | built |
| Playwright (run alone) | 319 passed |
| Alembic on a scratch database | upgrade head → `f7c2d9e3a1b5`, check clean, downgrade -1, upgrade |
| Verifiers | decision log, owner decisions (108), UAT blank (air pack 71) |

Independent tester: 11 golden tests (`test_rc20_golden.py`), no product defect. Independent
reviewer: no high finding; province detection (postal code first), seeded domestic drafts,
legacy payment dates, saved-rate validation, zero-rated wording, read-only message, rate-panel
accessibility and a costume-jewellery negative-margin test fixed; the domestic quote-wording
contradiction is logged as P-9 (wording kept as the owner asked).

## 3. Not done

Domestic shipments cannot be quoted on screen (P-10). Admin delete of retained quotes (OD-107).
Python 3.15 (P-8).
