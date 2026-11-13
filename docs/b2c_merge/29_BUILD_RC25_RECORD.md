# 29 — Build RC-UAT-25: Ben's live UAT fixes of 2026-10-25

**Date:** 2026-10-25 · **Branch:** `fix/owner-answers-rc17` (on RC-UAT-24, `9888196` / app
`f4a04a3`) · **Migration:** `a5c7e9b1d3f6` (revises `e7a9c1d3f5b6`; two new tables,
`customer_account_email_changes` and `shipment_event_revisions`; nothing existing altered) ·
**Decisions:** DEC-0240 to DEC-0247 · **Owner decision:** OD-113 · **Scope:** air only

Ben ran the CRM live on 2026-10-25 and reported eight findings. All eight are fixed here.
Nothing is pushed or merged; test data only; email is test capture only. The held items stay
unbuilt (returns OD-22, staff MFA OD-17, production email OD-34, ShipStation / provider sync
OD-21, retention periods OD-01 and OD-36). Refunds, voids and hosting are untouched.

## 1. What changed

| # | Ben's finding | Result |
|---|---|---|
| 1 | Labels end in "(required)" | A red `*` beside each required label, no words, in the Staff Portal (every form on the staff `Field`, incl. Create booking and **Record event**) and the Customer Account, English and Vietnamese; one shared `RequiredMark`, colour token `--required-mark`; the star is `aria-hidden`, the control carries `aria-required`; Customer Account "(optional)" moves under the control as "Optional" / "Không bắt buộc" (DEC-0240) |
| 2 | Customers should not change the sign-in email themselves | "Sign-in and security" shows the email read only; `POST /account/email/change` answers 403 to everyone, before reading the body; every outstanding link is refused and its request closed (`self_service_withdrawn`); an Admin changes it with `POST /customer-account/identities/{ref}/sign-in-email` ("Change sign-in email" on the staff account screen; reason code, optional note): the linked customer's email follows, every link and session ends, the old address is told and the new one gets the sign-in link; audited with keyed digests only; history in `customer_account_email_changes` (DEC-0243) |
| 3 | The declared value currency is free text | A list: —, CAD, VND (`booking_service.DECLARED_VALUE_CURRENCIES`, published as `declared_value_currencies` in `GET /shipments/meta`); any other code refused on draft create and edit (422) and per row in the CSV import (`invalid_currency`); a code stored before is kept (DEC-0241) |
| 4 | The recipient has no saved-address picker | The recipient card offers every non-billing saved address of the customer, recipient ones first, sender ones marked "(saved as sender)"; a registration saves the address as a sender address only, which is why the picker looked missing (DEC-0242) |
| 5 | "Received at Solaris" | Every label reads **Received at warehouse** / **Đã nhận hàng tại kho** (stored code unchanged); new standard update `received_at_solaris.v2` ("We have received your shipment at our warehouse."), `v1` retired (still renders on events that carry it, never offered); the catalogue gains a `retired` list (DEC-0244) |
| 6 | A published timeline event cannot be corrected | **Edit** on each live, staff-entered event (`tracking:write`, Admin and Operations): type, time, packages, leg, location, internal note, and — on a published event — the customer sentence, only to a standard update offered for its type; reason required; never publishes, unpublishes or emails; `POST /shipments/{id}/events/edit`, history in `shipment_event_revisions` and `GET /shipments/{id}/event-revisions`, audit `shipment.event_edit` (DEC-0245) |
| 7 | The Financials tab went blank after adding financial info | Fixed at its cause (below): the recorded-amounts currency must be three letters (422 otherwise), `formatMoney` never throws, a bad stored code shows as entered with a warning, and every shipment tab sits in `PanelErrorBoundary` ("This section could not be shown", **Try again**) (DEC-0246) |
| 8 | No clear way to see the cost and invoice from the shipment | The Financials tab opens with a **Quote and invoice** card (`GET /shipments/{id}/financial-summary`, `financial:read`): master, newest quote, quoted revenue, vendor cost and gross profit for `tariff:read`, and one next step (price, finalise, re-quote, **Issue invoice**, review draft, open invoice); Issue invoice disabled with the exact refusal (`finance_service.invoiceable_version`, shared with `issue_invoice`); the header gains **Quote & invoice** (DEC-0247) |

**Root cause of the blank Financials tab (item 7).** One crash, two missing safeguards on the way
to it. `formatMoney` (`frontend/src/utils/format.js`) passed the shipment's recorded currency
straight to `Intl.NumberFormat(…, { style: 'currency', currency })`, which throws `RangeError:
Invalid currency code` for anything that is not three ASCII letters (`"CA"`, `"$"`, `"C$"`,
`"VN"`, `" "` …). The tab formats every amount through it. Such a code could be stored because
the tab's own **Recorded amounts** Currency box was free text (up to three characters, no format
check) and the server accepted anything up to three characters (`max_length=3`, no validation in
`update_financials`). And because there was no React error boundary anywhere in `frontend/src`,
React 18 unmounted the whole root: header, tabs and shell disappeared — a blank page, not an
error state. Ben saved financial info on shipment 71 with such a code; every later visit to
`/shipments/71?tab=financials` repeated the crash (the other tabs worked). The exact characters
he typed are unknown (the database was not opened, by rule: RC25-C1). Twelve other financial
shapes (no master, amount only, unpriced, draft and finalised quotes, manual invoice with payment
and partial refund, legacy layout, voided invoice, accepted-quote draft, VND vendor bill …) were
built through the API and all read 200 and render without error.

**Tests added.** Backend: `test_rc25_booking_currency.py`, `test_rc25_email_admin_only.py`,
`test_rc25_warehouse_event.py`, `test_rc25_edit_published_event.py`,
`test_rc25_financials_tab.py` (incl. `test_every_financial_shape_reads_200_with_the_next_step`).
Frontend: `rc25Forms.test.jsx`, `rc25AccountsTimeline.test.jsx`, `rc25Financials.test.jsx`
(against the captured `fixtures/rc25Financials.json`, all 12 shapes); Playwright
`staffBookingForm.spec.js`, `staffFinancialsTab.spec.js`.

**Existing assertions changed.** Item 2 withdrew DEC-0231's self-service email change: fourteen
backend tests are registered as **AS-44 to AS-57** in
`docs/customer_account/SUPERSEDED_ASSERTIONS.md` (twelve in `test_rc21_account_security.py`, two
in `test_rc21_golden.py`; each now asserts the refusal or the Admin path; cited DEC-0231 and
DEC-0243). Four more there build the pre-RC-UAT-25 link with `legacy_link` (assertions
unchanged); `test_account_review_permissions.py` `EXPECTED` gains the Admin route;
`test_migrations_phase13f.py` `HEAD_REVISION` → `a5c7e9b1d3f6`. Frontend: the email-change tests
of `rc21AccountSecurity.test.jsx` now assert the read-only card and the "no longer works" page;
`accountSignInSecurity.spec.js`'s email part is an Admin change; the milestone checkbox reads
"Received at warehouse" in `customerNotifyFinanceSettings.test.jsx`, `accountNotifications.test.jsx`
and `staffNotifications.spec.js` (which now also edits the published milestone and still finds
exactly one notification). Item 1: Customer Account label locators lose "(required)" /
"(optional)" (vitest and Playwright, `{ exact: true }` where a label is a substring of another);
the "required in words" assertions of `uatRound9.test.jsx` and `accountRoundNine.spec.js` assert
`aria-required` instead; `uatRound11.test.jsx` expects the search hint followed by "Optional";
`workspace.test.jsx` expects "Reason for this rate" with `aria-required`. Items 3, 7 and 8 changed
no existing assertion (`FinancialsTab` moved to its own file and is re-exported from
`shipmentTabs.jsx`; `issue_invoice`'s refusals are unchanged word for word).

**Docs.** UAT: `UAT-BLD-26` to `-33` added, `UAT-BLD-09` rewritten in place (the Admin change),
`UAT-BLD-10` withdrawn (heading kept), `UAT-BLD-08` step 2 and the RC-UAT-21 stand-in rows
updated; air pack **104** cases; "Received at Solaris" replaced in the UAT packs, the staff guide
and the data dictionary; `REVIEW_vietnamese_templates.md` gains `received_at_solaris.v2`;
Ben's script step 40 rewritten and step 43 added.

## 2. Evidence

| Gate | Result |
|---|---|
| ruff | clean (399 files formatted) |
| alembic | upgrade, current, check, downgrade -1, upgrade on a scratch database -- head `a5c7e9b1d3f6`, "No new upgrade operations detected" |
| verifiers | decision log (DEC-0240 to DEC-0247), owner decisions (OD-113), UAT blank (49 / 60 / 104) -- pass |
| eslint, vitest | clean; 892 passed |
| build | OK |
| backend pytest | 5,055 passed, 1 skipped, 0 failed (eleven foreground chunks covering all 164 test files) |
| Playwright | full suite on port 5173, one run on the integrated tree: **328 passed** (14.1 min); no second run needed |

The three developers worked in the same tree at once; failures each saw in the others' in-progress
areas (vitest `shipmentDetail` / `accountNotifications`, Playwright `staffAccessibility` /
`staffFinance`) did not occur on the integrated tree above.

## 3. Known issues and open questions

Every choice the developers had to make is a stand-in in force, listed in full in
`19_OWNER_QUESTIONS.md` §000000: **RC25-A1 to A8** (asterisks, currency list, saved recipient),
**RC25-B1 to B13** (Admin-only sign-in email, "Received at warehouse", editing a published
event), **RC25-C1 to C7** (the Financials tab). The RC-UAT-21 stand-ins B-3, B-7 (email part),
B-11 (email part), B-12 and B-14 no longer apply (DEC-0243).

* **RC25-C1 — Ben's exact typed currency is unknown.** His database was not opened (by rule), so
  the characters he typed on shipment 71 are not known; every non-three-letter value reproduces
  the blank page and is now handled. A code already stored is not rewritten (RC25-C2): the tab
  shows it as entered with a warning, and staff correct it in the form. If shipment 71 shows a
  normal code, the error boundary now prints the browser's error on the page: send it.
* `docs/PRODUCT_SPEC.md` still lists "Received at Solaris" among the Phase 2–3 state names; it is
  a historical specification and was left as written.

## 4. Not done

Returns (OD-22), staff MFA (OD-17), production email (OD-34), ShipStation / provider sync
(OD-21) and retention periods (OD-01, OD-36): held by Ben. Refunds and voids: unchanged.
Hosting: not started.
