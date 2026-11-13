# 22 — Fix pack: owner answers to the RC-UAT-17 questions → RC-UAT-18

**Date:** 2026-10-21 · **Branch:** `fix/owner-answers-rc17` (off RC-UAT-17, `911965b`, with its UAT
documents `f6948ea` cherry-picked as `432a9b9`) · **Migration:** `d4f7a2c9e1b8` (from
`c5e8a1f3d7b9`; three new tables, nothing existing altered) · **Decisions:** DEC-0219 to DEC-0222 ·
**Owner decisions:** OD-81 to OD-90 (Louis Tong, project owner, on Ben's behalf) · **Scope:** air only

Nothing is pushed or merged. Test data only; email is test capture only.

## 1. What changed, per owner answer

| # | Answer | Change |
|---|---|---|
| 1 (OD-81) | Express zone 2 drop at 16 kg is correct; no flag | The importer reports the three drops (HCM-AIR-CAD!F39, HN-AIR-CAD!F38, HN-AIR-CAD!G38) as owner-confirmed price steps, not anomalies, only at the confirmed printed price; any other drop is still an anomaly. Quotes use the printed band (unchanged) |
| 2 (OD-82) | HCM meat / egg / dairy / honey: 20,000 VND/kg for VN-CA | The curated rule carries route VN-CA explicitly and cites the decision; price and full-carton scope pinned by test |
| 3 (OD-83) | Per-kg basis follows the vendor notes; silent keeps current; pharma on the item's kg | Notes re-read: no air rule's note contradicts its current basis, so nothing changes; every per-kg air rule's scope is pinned by a regression test (table in `05_OPEN_DECISIONS.md`). HCM row 27 stays on the item's kg (silent note; follow-up F-1) |
| 4 (OD-84) | No vendor or carrier name customer-facing | `customer_labels.customer_safe_label`: a label naming a vendor (the `vendors` table plus "Kango"; case-, diacritic- and spacing-insensitive) reads "Phụ phí" / "Surcharge" on the Customer Account quote, printed quote, invoice document, draft and issued invoice PDFs; emails and receipts carry no tariff text. Review fixes: whole-word matching plus obfuscation ("Kan-go") for names of 5+ letters, minimum 4; staff-typed free text (tracking and account milestones and locations, invoice/receipt documents and PDFs) has only the vendor words replaced by "đối tác vận chuyển" / "carrier"; draft lines, notes, bill-to and PO naming a vendor are refused on save (422); a carrier link whose host or label names a vendor is hidden |
| 5 (OD-85) | Vietnamese wording accepted | No change |
| 6 (OD-86) | Air Express: no default rate | Confirmed; pinned by test |
| 7 (OD-87) | Rate emails to Ben's mailbox | Confirmed (intake defaults); pinned by test; the UAT seed keeps demo addresses |
| 8 (OD-88) | Booked master locks items and fees; Admin unlocks with a reason | DEC-0219: items and fee lines locked from booking; Admin unlock with reason (audited; a simultaneous second unlock is 409), Admin/Operations relock, automatic relock when a member quote is finalised; workspace lock badge and controls |
| 9 (OD-89) | Acceptance creates the invoice (draft); expiry only before receipt on a new tariff | DEC-0220, DEC-0221: a draft invoice on acceptance (no INV- number until Send); on tariff activation, quotes for goods not yet received expire (draft withdrawn), staff re-quote; received goods never expire. The booked-master stand-in reads the shipment's current master; the offer is expired by a conditional UPDATE that records the true previous status and withdraws a draft created by an acceptance committed meanwhile |
| 9a (OD-90) | Draft screen: Save, Send, Download, Edit; save before anything else | DEC-0221: draft screen with revision-checked Save, Send (issue + email), Download (PDF, DRAFT watermark while a draft), edits audited with a diff; Send and Download disabled while edits are unsaved, leaving warns. Review fixes: Send confirms (number, total, email); a draft behind a newer finalised version needs "Send at the accepted price (vN)" (else 409 `quote_superseded`) or staff withdraw it (`POST /invoice-drafts/{id}/withdraw`, audited) and invoice the latest version; PDFs page long content, wrap long words, VOID watermark; refetch never overwrites unsaved edits |

## 2. Stand-ins and follow-ups

All are in `19_OWNER_QUESTIONS.md` §0 (F-1 to F-10, Q-P1, Q-P2). None blocks UAT. Q-P2 is now
in force as "replaced on output" (staff-typed milestone text naming a vendor reads "đối tác vận
chuyển" / "carrier"); Q-P1's last-mile link is hidden when its host or label names a vendor.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,323 passed, 1 skipped; 2 failed, the known worktree-only pair (`test_e2e_safety` development-database probe, `test_incident_cleanup` UAT-database refusal) |
| ruff check / format | clean (343 files) |
| eslint, vitest | clean; 747 passed |
| vite build | built |
| Playwright (run alone) | 318 passed (a first run caught `accountQuotes.spec.js` not passing the new Send confirmation; fixed and rerun) |
| Alembic on a scratch database | upgrade head → `d4f7a2c9e1b8`, check clean, downgrade -1, upgrade |
| Verifiers | decision log, owner decisions, UAT blank (air pack 53 cases) |

Independent tester: 6 end-to-end golden tests (`test_rc18_golden.py`), no product defect.
Independent reviewer: no high finding; six medium (draft behind a newer version, name matching,
staff-typed free text, current master for the booked stand-in, expiry/acceptance race, Send
confirmation) and the low findings fixed.

## 4. Not done

No live mailbox and no email provider (production only). Browser Back from an unsaved draft is not
intercepted (F-9).
