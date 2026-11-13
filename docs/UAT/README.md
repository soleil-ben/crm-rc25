# User acceptance testing — materials

> # ⚠ PREPARED, NOT EXECUTED
>
> **No UAT has been carried out. No member of staff has run any case in this pack, and no
> case has passed or failed.** Every pass/fail field is deliberately blank and must be
> filled in by the person who actually performs the step.
>
> Preparing UAT materials is not the same as real staff completing them. This pack is
> ready to be run; it is not evidence that anything works for the people who will use it.

---

## What this pack is

| File | Contents |
|---|---|
| `README.md` | This file: how to run UAT, severity, triage, retest, sign-off |
| `UAT_CASES.md` | Every test case, grouped by role |
| `UAT_SUMMARY.md` | The summary sheet to fill in as cases are run |
| `DEFECT_TEMPLATE.md` | One defect report per finding |
| `ENVIRONMENT.md` | Building, starting, resetting and destroying the UAT environment, and **what it cannot show a tester** |
| `CUSTOMER_ACCOUNT_UAT_PACK.md` | The Customer Account's own pack — registration, approval, shipment history, and the cross-cutting phone/keyboard/language cases. Separate from `UAT_CASES.md` so the staff pack stays executable on its own |
| `AIR_UAT_PACK.md` | Phase 17: the air pricing, quotes and money pack for Phases 13A to 15 — workspace and quotes, quote acceptance in the Customer Account, finance, pricing settings, tariffs and rate emails, milestone emails, the Vietnamese-first account — against the seeded air dataset |
| `HOW_TO_RUN.md` | One page: build, reset, start, sign in, emails, the `--once` workers |
| `UAT_SCRIPT_FOR_BEN.md` | The owner's guided 60–90 minute walk-through of the air pack, plus short parts for the owner answers of 21, 22 and 23 October and the build of 24 October (Part 9) |
| `REVIEW_customer_account_copy.md` | The customer-facing English copy, reviewed for wording that does not disclose. **Not reviewed** |
| `REVIEW_accessibility.md`, `REVIEW_vietnamese_ui.md`, `REVIEW_vietnamese_templates.md`, `REVIEW_physical_label.md` | The other four review sheets. **None reviewed** |
| `../OWNER_DECISIONS.md` | The owner-decision register. **Read it before marking anything `Blocked`** — it is what a `Blocked` result points at |

Some cases cannot be completed until the owner answers a question. Those are listed under
"Blocked by an open owner decision" at the top of `UAT_CASES.md`, and at the top of
`CUSTOMER_ACCOUNT_UAT_PACK.md` for that surface. A blocked case is recorded as `Blocked`,
never as `Fail`: nothing is broken, the question is unanswered.

**Three packs, three counts.** `UAT_CASES.md` holds 49 staff and public cases;
`CUSTOMER_ACCOUNT_UAT_PACK.md` holds 60 Customer Account cases, counted by heading
(`CA-REG` 9, `CA-APR` 17, `CA-SHP` 20, `CA-PRF` 4, `CA-SEC` 7, `CA-XP` 3; DEC-0136,
DEC-0162); `AIR_UAT_PACK.md` holds 104 cases (`UAT-WSQ` 7, `UAT-QAC` 4, `UAT-FIN` 8,
`UAT-PRC` 4, `UAT-TAR` 5, `UAT-MLS` 4, `UAT-VIA` 4; DEC-0218; `UAT-OWN` 35: 17 added for
RC-UAT-18 by the owner answers of 2026-10-21, 10 for RC-UAT-19 by those of 2026-10-22, and 8
for RC-UAT-20 by those of 2026-10-23; and `UAT-BLD` 33 (17 for RC-UAT-21, the build of
2026-10-24, OD-110, 2 for RC-UAT-22, B-13, 5 for RC-UAT-23, the invoices, 1 for RC-UAT-24, the legal entity, and 8 for RC-UAT-25, Ben's live UAT of 2026-10-25, OD-113; `UAT-BLD-10` was withdrawn in RC-UAT-25 and keeps its heading, so it still counts) — its account cases live there too, on the seeded A1 and A2 accounts, so
the Customer Account pack stays at 60). `scripts/verify_uat_blank.py`
checks all three counts. They are counted separately and signed off separately, and
the release-candidate baseline's case check measures only the first — which is a property of the
baseline script, recorded in `docs/customer_account/UAT_IMPACT_MAP.md` §6, not a statement
that the second matters less. The bot-executed run of 2026-10-14 listed 57 Customer
Account cases; which two it omitted is not recoverable from the pack, and the heading
count is the one these documents use until that list is reconciled.

**The seed carries the pack's data since the 2026-10-14 fix pack.** The five test people
P1–P5 of `UAT_CASES.md` exist on a fresh reset (P4 sharing P1's phone, P5 without one);
P1 has an in-transit shipment with published milestones, a cancelled one and a
cancelled-and-rebooked pair; one customer has 28 shipments across every operational state
so list paging can be exercised; and `STCA-000001` has one non-demo shipment, which is the
only kind a linked Customer Account can see. `scripts/uat_env.py --check` reports each of
these as a category. Testers who want their own copies should still suffix the names as
the table in `UAT_CASES.md` says.

## Roles

Five, matching the application exactly. Every role gets its own cases, **including cases
that test what the role may *not* do** — a permission that has never been tested from the
wrong side has not been tested.

| Role | Who | Cases |
|---|---|---|
| **Admin** | Owner, system administrator | `UAT-AD-*` |
| **Operations** | Booking, packages, labels, milestones | `UAT-OP-*` |
| **Marketing** | Segments, consent, campaigns | `UAT-MK-*` |
| **Read-only manager** | Oversight without editing | `UAT-RM-*` |
| *(cross-role)* | Public tracking, accessibility, failure states | `UAT-XX-*` |
| *(air pack, mostly Operations and Admin; A1 and A2 as customers)* | Workspace and quotes, quote acceptance, finance, pricing settings, tariffs, milestone emails, the Vietnamese-first account, the owner answers of 2026-10-21, 2026-10-22 and 2026-10-23, the build of 2026-10-24 (imports, account security, reinstatement, quote soft delete, retention), the account re-link of RC-UAT-22, the invoices of RC-UAT-23, the legal entity of RC-UAT-24 and the fixes of Ben's live UAT in RC-UAT-25 (asterisks, the currency list, the saved recipient, the Admin's sign-in email change, "Received at warehouse", editing a published event, the Financials tab) | `UAT-WSQ-*`, `UAT-QAC-*`, `UAT-FIN-*`, `UAT-PRC-*`, `UAT-TAR-*`, `UAT-MLS-*`, `UAT-VIA-*`, `UAT-OWN-*`, `UAT-BLD-*` (`ROLE_MERGE_COVERAGE_MAP.md` §8) |

---

## Before you start

### The environment

- [ ] UAT runs against a **dedicated UAT environment with synthetic data**, never against
      production and never against a copy of real customer data
- [ ] The database has been seeded with the synthetic fixtures
- [ ] Every tester has their **own** account in their **own** role — never a shared login,
      and never an Admin account "just to get through it"
- [ ] Testers have this pack, and a way to report defects
- [ ] An observer is available to answer questions and record what happens

**Start here for RC-UAT-25** (RC-UAT-24 plus the fix pack for Ben's live UAT of 2026-10-25,
OD-113: a red `*` beside each required label instead of "(required)", DEC-0240; the declared
value currency a list of CAD and VND, DEC-0241; saved addresses for the recipient, DEC-0242;
the customer can no longer change the sign-in email, an Admin does from the staff account
screen, DEC-0243; "Received at warehouse", DEC-0244; Admin and Operations can edit a recorded
or published timeline event, DEC-0245; the blank Financials tab fixed at its cause with an
error boundary around every shipment tab, DEC-0246; a **Quote and invoice** card on the
shipment, DEC-0247; record `docs/b2c_merge/29_BUILD_RC25_RECORD.md`; migration `a5c7e9b1d3f6`,
two new tables; stand-ins RC25-A1 to A8, B1 to B13 and C1 to C7 in
`docs/b2c_merge/19_OWNER_QUESTIONS.md` §000000; its new cases are `UAT-BLD-26` to `-33` in
`AIR_UAT_PACK.md`, `UAT-BLD-09` is now the Admin's change and `UAT-BLD-10` is withdrawn).
Baseline in force: `docs/RC_UAT_25_BASELINE.md`, measured at the application commit `bccbddf`.
Before it: **RC-UAT-24** (RC-UAT-23 plus Ben's evening answers of 2026-10-24, OD-112: the
legal entity reads **Solaris Express Inc.** on Settings, the staff login footer and the demo
label sender, I-10, DEC-0236; the draft invoice editor says "Tax included in the price" with
the invoice's summary labels, I-11, DEC-0239; I-1 and I-12 confirmed as built, DEC-0237,
DEC-0238; record `docs/b2c_merge/28_BUILD_RC24_RECORD.md`; data-only migration `e7a9c1d3f5b6`;
its new case is `UAT-BLD-25` in `AIR_UAT_PACK.md`, and `UAT-OWN-20` and `-28` read the new
editor wording; baseline `docs/RC_UAT_24_BASELINE.md` (superseded), measured at the application
commit `f4a04a3`). Before that: **RC-UAT-23** (RC-UAT-22 plus invoices that follow the Solaris Invoicing desk,
Ben's direction of 2026-10-24, OD-111: GST/HST backed out per line at the destination
province's rate on domestic courier lines, international Air Freight zero-rated, each line at
its net with a Tax column and summary rows, the total still the all-in total; English-only
invoice PDFs without accents, with the Solaris Express Inc. company block, Terms: Due on
receipt, the E-transfer and BMO wire lines and the desk's footer; quotes keep their inclusive
wording, OD-109 now confirmed; record `docs/b2c_merge/27_BUILD_RC23_RECORD.md`; no migration;
DEC-0235; stand-ins I-1 to I-13 in `docs/b2c_merge/19_OWNER_QUESTIONS.md` §00000; its new cases
are `UAT-BLD-20` to `-24` in `AIR_UAT_PACK.md`; baseline
`docs/RC_UAT_23_BASELINE.md` (superseded), measured at the application commit `3151095`). Earlier:
**RC-UAT-22** (RC-UAT-21 plus the build of B-13: Admin re-links an account left
without a customer after reinstatement — history previewed and acknowledged, the single email
rule, audited — or closes it, a reversible deactivation, on **Customer accounts → Accounts
needing a customer**; stand-ins B-15 to B-20; the Playwright blank-page flake fixed at its cause
and `test_e2e_safety` honest in worktrees; record `docs/b2c_merge/26_BUILD_RC22_RECORD.md`;
migration `d4f6b8c0e2a5`, one new table; DEC-0234; its new cases are `UAT-BLD-18` and `-19` in
`AIR_UAT_PACK.md`, and `UAT-BLD-13` now points to `-18`; baseline
`docs/RC_UAT_22_BASELINE.md` (superseded), measured at the application commit `61f5c22`). Earlier:
**RC-UAT-21** (RC-UAT-20 plus the build Ben asked for on 2026-10-24, OD-110:
shipment CSV import and the legacy history baseline; the customer's and the staff member's own
password change and the customer's sign-in email change (since RC-UAT-25, the Admin's change of a customer's sign-in email (customers cannot change it, RC-UAT-25));
Admin reinstatement of a deactivated
account; the customer quote's GST/HST line following the invoice rule — the OD-109 stand-in,
pending Ben —; Admin soft delete of old quote versions; and the retention machinery, **off**,
which testers only dry-run; record `docs/b2c_merge/25_BUILD_RC21_RECORD.md`; migrations
`a1c3e5f7b9d2`, `b2d4f6a8c1e3`, `c3e5a7b9d2f4`; DEC-0230 to DEC-0233; its new cases are
`UAT-BLD-01` to `-17` in `AIR_UAT_PACK.md`, and `UAT-OWN-35`, `UAT-WSQ-02` and `UAT-QAC-01`
were updated for the quote wording; open questions `docs/b2c_merge/19_OWNER_QUESTIONS.md`
§0000; import templates in `artifacts\sample-imports\`; baseline
`docs/RC_UAT_21_BASELINE.md` (superseded), measured at the application commit `be7d2df`). Before it: **RC-UAT-20** (RC-UAT-19 plus the fix pack for Ben's answers of 2026-10-23,
OD-102 to OD-108: GST/HST on the draft invoice by route — international 0 %, domestic
included at the destination province's rate, kept in **Settings → GST/HST rates** —;
costume jewellery with both the vendor's VND cost and the customer price; the RC-UAT-19
findings fixed (payment date, Download waiting for the GST/HST check, the vendor on the final
delivery leg, tariff warnings on Settings); record `docs/b2c_merge/24_FIXPACK_RC20_RECORD.md`;
migration `f7c2d9e3a1b5`; DEC-0227 to DEC-0229; its new cases are `UAT-OWN-28` to `-35` in
`AIR_UAT_PACK.md`, and `UAT-OWN-18` to `-27` were updated; baseline
`docs/RC_UAT_20_BASELINE.md` (superseded), measured at the application commit `98ca88b`). Before it: **RC-UAT-19** (RC-UAT-18 plus the fix pack for the owner answers of
2026-10-22, OD-91 to OD-101: GST/HST 13 % included and checked on the draft invoice, generic
tracking names on customer pages, costume jewellery by amount; record
`docs/b2c_merge/23_FIXPACK_RC19_RECORD.md`; cases `UAT-OWN-18` to `-27`; baseline
`docs/RC_UAT_19_BASELINE.md` (superseded), measured at the application commit `418cf3f`). Before that:
**RC-UAT-18** (RC-UAT-17 plus the
fix pack for the owner answers of 2026-10-21, OD-81 to OD-90:
`docs/b2c_merge/22_FIXPACK_RC18_RECORD.md`; cases `UAT-OWN-01` to `-17`; baseline
`docs/RC_UAT_18_BASELINE.md`, measured at `03b943d`). Python: see `HOW_TO_RUN.md` §1
(64-bit 3.11 to 3.14). Follow `HOW_TO_RUN.md`: build with `uat_env.py --reset`,
then start the stack the way `ENVIRONMENT.md` **§3a** gives it — with
`ACCOUNT_EMAIL_TRANSPORT=capture` and `TARIFF_INTAKE_DIR` — not the way §3 alone gives it.
§3 starts a stack on which the Customer Account appears to work and silently writes no
message anywhere. Run `UAT_CASES.md`, `CUSTOMER_ACCOUNT_UAT_PACK.md` and `AIR_UAT_PACK.md`
in their own passes, resetting between them. Run the Customer Account pack **in case
order**: its accounts are created by `CA-REG-01`; the two seeded accounts (A1, A2) belong
to the air pack only. In the air pack, run the account cases `UAT-BLD-08` to `-13` last and
reset afterwards: they change A1's password, the Operations password and, as Admin, A2's
sign-in email (`-10` is withdrawn).

### Prewritten fields and recorded fields

Two kinds of field appear in both packs and in all five review sheets, and a reader must
never mistake one for the other.

| Class | Where it appears | State before testing |
|---|---|---|
| **Evidence to capture** / **Content under review** | Both packs; every review sheet | Prewritten as part of the case or the thing being judged |
| **Evidence obtained** | Both packs; every review sheet | **Blank** |
| **Reviewer response** | The review sheets | **Blank** |
| **Result**, **Defect**, **Tester**, **Date**, sign-off | Both packs; every review sheet | **Blank** |

**A prewritten instruction is not evidence.** `Evidence to capture` names what a tester
should collect; it says nothing about whether anybody collected it. Only `Evidence
obtained` does that, and it stays blank until the tester writes in it. The split is
checked by script:

```bash
backend/.venv/Scripts/python scripts/verify_uat_blank.py
```

### What testers should be told

**"We are testing the software, not you."** If a step is confusing, that is a finding, and
one of the more valuable kinds. Write down where you hesitated even if you completed the
task — a workflow that works only because someone explained it will not work at 5pm on a
Friday.

### What is deliberately not in scope

| Not tested, and why |
|---|
| **ShipStation or any carrier integration.** No provider is connected (DEC-0075). Integration health reads `not_configured`, which is the correct result, not a defect |
| **Physical label printing and scanning.** A separate hardware check — print `artifacts/sample-labels/*.pdf` at 100% on the real thermal printer and scan with the real handheld |
| **Real customer data.** Synthetic only |
| **Load or performance at scale.** Measured separately (`scripts/report_query_review.py`) |
| **Email and SMS *delivery*.** Nothing is sent to a real address. The Customer Account's messages, the quote-sent emails, the invoice-sent emails (RC-UAT-18) and the milestone emails are composed, and in UAT they are written to `data/uat/account_mail` as files and read from there — `ENVIRONMENT.md` §3a. Whether a real provider would deliver them is untestable here and is blocked on OD-34 |
| **Retention deletion.** The machinery exists (RC-UAT-21) but is off, and testers only dry-run it: the periods are undecided (OD-01, OD-36) and turning it on needs the owner's written approval (`UAT-BLD-17`) |
| **A vendor mailbox and a live exchange rate.** No mailbox is connected (rate emails are uploaded or dropped in the intake folder), and the bank is never called: every rate is a demo reading. Both are the behaviour under test, not gaps (`ENVIRONMENT.md` §7) |

---

## Severity

Assign severity from **impact on the business**, not from how hard it looks to fix.

| Severity | Definition | Examples | Launch |
|---|---|---|---|
| **S1 — Critical** | Data loss, a privacy breach, or a core workflow that cannot be completed at all | A customer's details visible to another customer; public tracking exposing a private field; a confirmed booking losing its Solaris ID; an import creating duplicates | **Blocks launch.** No exceptions |
| **S2 — Major** | A core workflow is completable but wrong, or a permission does not hold | A shipment count including cancelled bookings; an export containing a column a role may not see; a duplicate merged without review | **Blocks launch** unless the owner accepts it in writing with a workaround |
| **S3 — Moderate** | Works, but incorrectly or confusingly in a way that will cause errors | A status label that reads as the opposite of what it means; a date in the wrong timezone; a validation message that does not say what to fix | Fix before launch if possible; may ship with a documented workaround |
| **S4 — Minor** | Cosmetic, or a small inconvenience with an obvious workaround | Misalignment; an awkward tab order; inconsistent capitalisation | May ship. Record for later |
| **S5 — Observation** | Not a defect. A suggestion, a question, or a note about wording | "Vietnamese phrasing sounds formal"; "I expected this button on the left" | Does not block. **Still record it** |

**Anything touching customer privacy is S1 until proven otherwise.** Do not downgrade a
privacy finding because it seems unlikely; establish the facts first.

## Triage

Within one working day of being reported.

1. **Reproduce.** A defect nobody can reproduce is a defect nobody can fix. If it cannot
   be reproduced, say so on the report and keep it open — do not close it.
2. **Confirm severity** with someone other than the reporter. Severity set by one person
   alone drifts.
3. **Classify**: product defect / data problem / environment problem / **expected
   behaviour misread as a defect** / documentation gap.
4. **Assign** and set a target.
5. **Check for a pattern.** Three S4s in the same screen are often one S2.

**The fourth classification matters.** Several things in this system look like defects and
are deliberate: counts excluding drafts and cancellations, a blank where a figure is
genuinely unknown, no trend arrows, the public page not refreshing itself, and integration
health reading `not_configured`. When a case is closed as expected behaviour, **write down
why** — and consider whether the guide or the interface should have made it clearer. A
tester misreading it is evidence about the design, not about the tester.

## Retest

1. Retest the **exact original steps**, by the **original tester** where possible.
2. Retest on the build that contains the fix, and record the build.
3. Check for regression in the immediate area, and anywhere sharing the mechanism — a
   permission fix in one export should prompt a look at all of them.
4. Update the summary sheet: **Pass**, **Fail (still)**, or **Fail (differently)**.
5. **A defect is closed by the person who reported it**, not by the person who fixed it.

## Sign-off

UAT is complete when every case has a result, every S1 and S2 is closed or accepted in
writing, and the sign-offs below are filled in.

| | Name | Role | Date | Signature |
|---|---|---|---|---|
| Test lead | | | | |
| Operations representative | | | | |
| Marketing representative | | | | |
| **Owner** | | | | |

**Owner acceptance statement** — to be completed only after the above:

> I confirm that the cases in this pack have been executed by the named staff, that the
> results recorded are the results obtained, and that the outstanding defects listed on
> the summary sheet are accepted, with their workarounds, for launch.
>
> Signed: ________________________  Date: ____________

**This statement must not be signed in advance, and no part of this pack may be
represented as completed until the cases have actually been run.**
