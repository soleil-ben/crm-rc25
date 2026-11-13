# 16 — Remaining work to UAT-ready (phases 14 to 17)

**Date:** 2026-10-20 · **Base:** 38b845f (Phase 13H) · **Scope:** air only, test data only

The owner (2026-10-20, 22:16) asked for the whole CRM to be finished to UAT-ready after the
Phase 13 plan. This compares the full scope -- the original package, `06_MERGE_PLAN.md`, the
"Not done" and "Stand-ins" sections of records 11 to 15, the owner-decision register and the
UAT pack -- with what is built. The owner's instruction of 19:44 applies throughout: nothing
waits for an owner answer unless it would save hours of recoding; a safe stand-in is used and
the question is listed.

## Phases

| Phase | Scope | Items |
|---|---|---|
| **14 — Staff screens for API-only features** (**done**, `17_PHASE_14_RECORD.md`) | Settings → Pricing: Air Standard / Express default rates, the 2/3 share, the default surcharge markup (OD-74) and per-rule surcharge policies (OD-44); master-level tracking events that fan out to members (v2.1 Test 2); complete / cancel a master; edit an item; a read-only tariff browser (versions, products, accessorials, beyond rates) with FX history and the approver-gated manual workbook import; staff editing of a customer's milestone choices; invoice due-days field; a printable customer quote (revenue only, Solaris service names) | gap items 1–6 |
| **15 — Workflow hardening** (**done**, `18_PHASE_15_RECORD.md`) | Milestone email never notifies a step behind the furthest milestone already reached, whatever the current state (on hold, exception, returned); customer timeline shows the standard event wording in the customer's language, with the staff's published text beneath it; resend a failed quote email; an accepted quote shows staff an "issue the invoice" prompt (no automatic invoice); approvers see a badge for tariff drafts awaiting review | gap items 7–10, 12 |
| **16 — Registers and staff documentation** (**done**, `20_PHASE_16_RECORD.md`; questions in `19_OWNER_QUESTIONS.md`) | Owner-decision register statuses brought up to date (24 stale `not_implemented`); OD-32 reconciled with OD-77 (quote totals in the account are the only financial figures shown); `STAFF_GUIDE.md` sections for the workspace, quotes, finance, tariffs and notifications; one owner question sheet (below) | gap items 11, 14–18, 20 |
| **17 — UAT readiness** (**done**, `21_PHASE_17_RECORD.md`; RC-UAT-17) | A UAT demo database with realistic synthetic data covering every phase; new UAT case groups for 13A–17 in the existing pack format with an owner walk-through script; `ENVIRONMENT.md` and the how-to-run updated (capture transport, `--once` workers); stale text fixed (Customer Account no longer English-only); RC-UAT-17 frozen with its baseline | gap items 19, 21, 22 |

Each phase: developer subagent builds, an independent tester and reviewer check, all gates green
(ruff, full backend suite, eslint, vitest, build, Playwright alone, Alembic round trip on a
scratch database, both verifiers), then a local commit.

## Stand-ins chosen (owner may overrule later; none needs recoding of more than a screen)

| Question | Stand-in |
|---|---|
| Customer timeline wording | Standard event wording in the customer's language, staff's published text beneath |
| Quote acceptance and invoicing | Acceptance records only; staff are prompted to issue the invoice |
| Quote expiry | None |
| Sending while a newer draft is open | Refused (kept) |
| Air Express default rate | Empty: Operations enters the rate per quote |
| OD-32 vs OD-77 | OD-77 is newer: the customer sees their quote's charges and total, nothing else financial |
| Live mailbox, email provider, scheduled workers | Upload / folder intake, capture transport, `--once` runs (production only) |

## Open questions for the owner (development continues on the stand-ins)

1. D-07: Express zone 2 price drop at 16 kg — typo or intended?
2. D-09: HCM air meat / egg / dairy / honey: 20,000 or the printed 10,000 VND/kg?
3. V-20: other per-kg surcharges on the item's own kg or the full carton (now the carton)?
4. Are the surcharge names customers see on quotes customer-safe (they come from the vendor sheet)?
5. Vietnamese wording review by Vietnamese-speaking staff (account, emails, quotes, tariff screens).
6. Air Express default rate, if one should apply.
7. Which mailbox provider (Microsoft 365 / Gmail) to connect for rate emails, when production is planned.
8. Carried from earlier: MFA (OD-17), label hardware (OD-18), accessibility reviewer (OD-19), returns (OD-22), hosting and retention (production only).
