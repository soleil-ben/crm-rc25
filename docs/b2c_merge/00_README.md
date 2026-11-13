# B2C merge — combining the Louis handoff into this CRM

**Date:** 2026-10-19 · **Branch:** `phase-13-b2c-merge`, cut from `fix/uat-round-12` at
`d2802e1` (RC-UAT-16) · **Owner decision:** the existing CRM is the base; components from
"CRM handoff from Louis" (handoff bundle v1.6) are added into it. The v1.5 static app is
source material, not a code base.

**Backup taken first:** `CRM/Backups/2026-10-19_pre-merge/` — git bundle of all 27
branches (restore-tested), zips of both worktrees with databases and `.env`, `MANIFEST.md`,
`SHA256SUMS.txt`. Nothing in the Package was modified before that backup.

| Document | What it is |
|---|---|
| `01_HANDOFF_AUDIT.md` | What the handoff bundle contains and what the v1.5 code actually does (verified by reading, plus a Node simulation of its fee parser) |
| `02_KANGO_WORKBOOK_AUDIT.md` | The vendor tariff workbook vs the embedded JSON snapshot, and what the JSON omits |
| `03_FEATURE_MATRIX.md` | Every directive requirement vs this CRM: EXISTS / PARTIAL / MISSING, with evidence, and the KEEP / EXTEND / BUILD / DISCARD call for each handoff component |
| `04_ISSUE_REGISTER.md` | Defects and risks found in the handoff code that the merge must not import |
| `05_OPEN_DECISIONS.md` | Questions only the owner or the vendor can answer (pricing, rounding, policy) |
| `06_MERGE_PLAN.md` | The phased plan, data model additions, and acceptance tests |
| `07_DIRECTIVE_2_1_ASSESSMENT.md` | Whether Product Owner Directive v2.1 makes sense against this code base, section by section |
| `08_PHASE_13A_RECORD.md` | Completion record for Phase 13A: tariff importer, surcharge semantics, exchange-rate worker, evidence |
| `09_PHASE_13B_RECORD.md` | Completion record for Phase 13B: consolidation entity, memberships, master milestones, commodity items, payer, service mapping |
| `10_PHASE_13C_RECORD.md` | Completion record for Phase 13C: pricing engine, fee lines, versioned quotes, master cartons, owner decisions OD-46 to OD-63 (air only) |
| `11_PHASE_13D_RECORD.md` | Completion record for Phase 13D: the unified workspace screens, the local demo login, and the demo pricing data |
| `12_PHASE_13E_RECORD.md` | Completion record for Phase 13E: invoices, payments and receipts, vendor bills and reconciliation, receivables and payables, monthly profitability, M+7 close |
| `13_PHASE_13F_RECORD.md` | Completion record for Phase 13F: milestone email notifications (test capture), per-milestone choices, the Customer Account in Vietnamese first |
| `14_PHASE_13G_RECORD.md` | Completion record for Phase 13G: staff send a finalised quote; the customer accepts or declines it in the Customer Account (OD-77) |
| `15_PHASE_13H_RECORD.md` | Completion record for Phase 13H: vendor rate emails become draft tariff versions with a diff; only the designated approver activates (OD-76) |
| `17_PHASE_14_RECORD.md` | Completion record for Phase 14: staff screens for the API-only features (pricing settings and surcharge policies, master milestones, complete / cancel, item edit, tariff browser and manual import, milestone email choices, invoice terms, printable quote) |
| `18_PHASE_15_RECORD.md` | Completion record for Phase 15: workflow hardening (milestone emails never behind the furthest milestone reached, customer timeline standard wording, quote email resend, accepted-quote invoice prompt, tariff approver badge) |
| `19_OWNER_QUESTIONS.md` | One sheet for the owner: every open question, the stand-in in force, and what changes if he answers otherwise |
| `20_PHASE_16_RECORD.md` | Completion record for Phase 16: owner-decision register brought up to date, OD-32 narrowed by OD-77, staff guide sections for the workspace, quotes, finance, pricing, tariffs, notifications and the Customer Account |
| `21_PHASE_17_RECORD.md` | Completion record for Phase 17: UAT readiness (the seeded air dataset, the air UAT pack of 36 cases, how-to-run and the owner's walk-through, stale English-only text corrected, RC-UAT-17) |
| `22_FIXPACK_RC18_RECORD.md` | Completion record for the owner-answer fix pack (OD-81 to OD-90, DEC-0219 to DEC-0222): the booked-master lock with Admin unlock, draft invoices on acceptance, quote expiry on a new tariff before receipt, no vendor name customer-facing, migration `d4f7a2c9e1b8`, the `UAT-OWN` cases; RC-UAT-18 |
| `23_FIXPACK_RC19_RECORD.md` | Completion record for the owner answers of 2026-10-22 (OD-91 to OD-101, DEC-0223 to DEC-0226): GST/HST 13 % included and confirmed on draft invoices, generic customer tracking names (`carrier_links`), costume jewellery by manual amount, the UAT launcher for Python 3.11 to 3.14, migration `e6b1c4a8d2f3`, cases `UAT-OWN-18` to `-27`; RC-UAT-19 |
| `24_FIXPACK_RC20_RECORD.md` | Completion record for Ben's answers of 2026-10-23 (OD-102 to OD-108, DEC-0227 to DEC-0229) and the RC-UAT-19 UAT fixes: GST/HST by route on draft invoices (international 0 %, domestic included at the province's rate from Settings → GST/HST rates), costume jewellery by VND cost and CAD price, plain payment dates, Download after the tax tick, the tariff warnings panel, migration `f7c2d9e3a1b5`, cases `UAT-OWN-28` to `-35`; RC-UAT-20 |
| `25_BUILD_RC21_RECORD.md` | Completion record for the build run on Ben's direction of 2026-10-24 (OD-110, DEC-0230 to DEC-0233): release-agnostic UAT packaging, the quote GST/HST stand-in (OD-109, P-9), shipment CSV import and the legacy history baseline, password and sign-in email change, Admin reinstatement, Admin soft delete of old quote versions, retention machinery off by default, migrations `a1c3e5f7b9d2`, `b2d4f6a8c1e3`, `c3e5a7b9d2f4`, cases `UAT-BLD-01` to `-17`; RC-UAT-21, frozen at `be7d2df` |
| `26_BUILD_RC22_RECORD.md` | Completion record for RC-UAT-22 (DEC-0234): staff re-link or close of an account left without a customer after reinstatement (B-13, stand-ins B-15 to B-20), the Playwright blank-page flake fixed at its cause (one loopback address), `test_e2e_safety` honest in worktrees, migration `d4f6b8c0e2a5`, cases `UAT-BLD-18`, `-19`; RC-UAT-22, frozen at `61f5c22` |
| `27_BUILD_RC23_RECORD.md` | Completion record for RC-UAT-23 (OD-111, DEC-0235; OD-109 confirmed): invoices follow the Solaris Invoicing desk -- per-line GST/HST back-out at the destination province's rate, zero-rated international, net lines and a tax summary, English-only PDF, the Solaris Express Inc. company block, payment lines and footer; no migration; stand-ins I-1 to I-13; cases `UAT-BLD-20` to `-24`; RC-UAT-23, frozen at `3151095` |
| `28_BUILD_RC24_RECORD.md` | Completion record for RC-UAT-24 (OD-112, DEC-0236 to DEC-0239): Ben's evening answers of 2026-10-24 -- the legal entity Solaris Express Inc. on Settings, the login footer and the label sender (data-only migration `e7a9c1d3f5b6`), I-1 and I-12 confirmed, the draft editor's tax wording, held items skipped; case `UAT-BLD-25`; RC-UAT-24, frozen at `f4a04a3` |
| `29_BUILD_RC25_RECORD.md` | Completion record for RC-UAT-25 (OD-113, DEC-0240 to DEC-0247): Ben's live UAT fixes of 2026-10-25 -- red asterisks on required fields, the declared value currency list (CAD, VND), saved addresses for the recipient, the sign-in email changed by an Admin only, "Received at warehouse", correcting a recorded timeline event, the blank Financials tab fixed (root cause and error boundary), quote, cost and invoice on the shipment page; migration `a5c7e9b1d3f6` (two new tables); stand-ins RC25-A1 to A8, B1 to B13, C1 to C7; cases `UAT-BLD-26` to `-33`; RC-UAT-25, frozen at `bccbddf` |
| `BUILD_STATUS.md` | One page: what is built, what is held for Ben (returns, staff MFA, production email, ShipStation, retention off), and what the phase names mean |

Vocabulary used throughout: **Package** = this repository (FastAPI + React, RC-UAT-16).
**v1.5** = `Solaris_B2C_CRM_Full_Review_v1.5.zip` from the handoff. **Directive v2.0** =
"Master AI Development & Multi-Agent Orchestration Instruction v2.0". **Directive v2.1** =
"Product Owner Directive v2.1".
