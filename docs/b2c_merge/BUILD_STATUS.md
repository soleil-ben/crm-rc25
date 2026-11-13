# Build status — what is built, what is held

**As of:** RC-UAT-25 (2026-10-25) · **Branch:** `fix/owner-answers-rc17` · **Scope:** air only ·
nothing pushed, merged or deployed. One page; the detail is in the numbered records.

## Built

| Area | Where it is recorded |
|---|---|
| Phase 13A–13H: tariff import, consolidation, pricing and versioned quotes, the workspace, finance (invoices, payments, receivables and payables, M+7 close), milestone emails (test capture), quote send and accept, vendor rate emails to draft tariffs | `08` to `15` records |
| Plan 16, phases 14–17: staff screens for API-only features, workflow hardening, registers and staff guide, UAT readiness | `16_REMAINING_WORK_PLAN.md` (all four marked done), `17`, `18`, `20`, `21` records |
| Owner-answer fix packs RC-UAT-18 to -20 (booked-master lock, draft invoices on acceptance, GST/HST by route, costume jewellery cost and price, tariff warnings …) | `22`, `23`, `24` records |
| RC-UAT-21 build run: release-agnostic UAT packaging; quote GST/HST wording stand-in (OD-109); shipment CSV import and legacy history baseline; password and sign-in email change; Admin reinstatement; Admin soft delete of old quote versions; retention machinery (off) | `25_BUILD_RC21_RECORD.md` |
| RC-UAT-22: staff re-link or close of an account left without a customer after reinstatement (B-13); the Playwright blank-page flake fixed; the worktree-only safety-test failure fixed | `26_BUILD_RC22_RECORD.md` |
| RC-UAT-23: invoices follow the Solaris Invoicing desk (per-line GST/HST back-out by destination province, zero-rated international, net lines and tax summary, English-only PDF, Solaris Express Inc. company block, payment lines and footer); OD-109 confirmed | `27_BUILD_RC23_RECORD.md` |
| RC-UAT-24: Ben's evening answers -- the legal entity reads Solaris Express Inc. on Settings, the login footer and the label sender (I-10); English-only PDF and the cent nudge confirmed (I-1, I-12); the draft editor's tax sentence uses the invoice's labels (I-11) | `28_BUILD_RC24_RECORD.md` |
| RC-UAT-25: Ben's live UAT fixes of 2026-10-25 -- a red asterisk on required fields; the declared value currency is a list (CAD, VND); the recipient can use a saved address; the sign-in email is changed by an Admin only; "Received at warehouse"; a recorded timeline event can be corrected, published or not; the Financials tab no longer blanks the page; quote, cost and invoice on the shipment page (OD-113, DEC-0240 to DEC-0247) | `29_BUILD_RC25_RECORD.md` |

## Held — not started; Ben: skip for now (2026-10-24, OD-112)

| Item | Register | State in the code |
|---|---|---|
| Returns workflow | OD-22 (open) | Return statuses exist for staff; nothing writes the returns columns; no customer return flow |
| Staff MFA | OD-17 (open) | None: email and password, rate limited, session expiry |
| Production email | OD-34 | Null and capture transports only; no provider is written, so no email reaches anybody |
| ShipStation / provider sync | OD-21 (open, deferred by DEC-0075) | Inert: adapter registry and both allowlists empty, `connected_api` refused |
| Retention deletion | OD-01 (open), OD-36 | Machinery built (RC-UAT-21) and **off**: every class off with no period, global switch off |

Open questions with the stand-in in force for each: `19_OWNER_QUESTIONS.md` (§000000 for the RC-UAT-25
live UAT fixes, §00000 for the RC-UAT-23 invoices, §0000 for the RC-UAT-21 and RC-UAT-22 builds).

## Phase names

Plan 16 numbers its phases **14 to 17**, and all four are done. The letters **A, B and D** are
only the item labels of Ben's RC-UAT-21 build brief (A imports, B account features, D admin and
retention), recorded in `25_BUILD_RC21_RECORD.md` and `19_OWNER_QUESTIONS.md` §0000; they do not
map to phases 14–17. **No Phase C or Phases E to H are defined anywhere in the repository**
(searched 2026-10-24). If a plan with those letters exists outside the repository, it has not
been handed over.
