# 19 — Open questions for Ben (one sheet)

**Date:** 2026-10-21 · **As of:** Phase 16; answers recorded 2026-10-21 (RC-UAT-18 fix pack) · **Scope:** air only, test data only

Nothing below stops development. Each row has a safe stand-in that is in force today. If your
answer is the stand-in, nothing changes. Otherwise the last column says what we would change.
Sources: `16_REMAINING_WORK_PLAN.md`, records 13 to 18, and the open decisions in
`docs/OWNER_DECISIONS.json`.

## 000000. RC-UAT-25 live UAT fixes (Ben, 2026-10-25) -- built, with stand-ins

**Ben's eight findings from his live UAT of 2026-10-25 (OD-113), fixed in RC-UAT-25** (record
`29_BUILD_RC25_RECORD.md`; migration `a5c7e9b1d3f6`, two new tables):

1. Required fields show a **red asterisk**, not "(required)" / "(bắt buộc)", in the Staff Portal
   and the Customer Account, English and Vietnamese (DEC-0240).
2. The **sign-in email is changed by an Admin only**: the customer sees it read only on
   "Sign-in and security"; an Admin changes it on the staff account screen ("Change sign-in
   email"), every session ends, both addresses are told (DEC-0243). The RC-UAT-21 self-service
   change is withdrawn; stand-ins B-3, B-7 (email part), B-11 (email part), B-12 and B-14 in §0000
   no longer apply.
3. The booking's **declared value currency is a list**: CAD or VND, enforced by the server and the
   CSV import (DEC-0241).
4. The **recipient can use a saved address** too: every non-billing saved address of the
   customer, recipient ones first (DEC-0242).
5. "Received at Solaris" reads **"Received at warehouse"** / "Đã nhận hàng tại kho" everywhere;
   new standard update `received_at_solaris.v2`, v1 retired (DEC-0244).
6. A recorded timeline event, **published or not, can be corrected** by Admin and Operations
   with a reason, kept in an edit history; an edit never re-publishes and never emails
   (DEC-0245).
7. The **blank Financials tab** is fixed at its cause: a recorded-amounts currency that was not
   three letters crashed the money formatter and, with no error boundary, unmounted the app.
   The code is now checked, a bad stored code is shown as entered, and each tab sits in an
   error boundary (DEC-0246).
8. **Quote, cost and invoice on the shipment page**: the Financials tab opens with a **Quote and
   invoice** card and one next step (price, finalise, issue invoice, review draft, open
   invoice); the header gains **Quote & invoice** (DEC-0247).

The choices the developers had to make (each is the stand-in in force; tell us if you want
otherwise):

### A -- asterisks, currency list, saved recipient (items 1, 3, 4)

- **RC25-A1 — Where the asterisk sits for screen readers.** Stand-in in force: the star is
  visual only (aria-hidden, outside the `<label>`); the control carries `aria-required`, so a
  screen reader says "Email address, required", and the accessible name stays "Email address".
- **RC25-A2 — Customer Account "optional" wording.** Stand-in in force: optional fields show
  "Optional" / "Không bắt buộc" under the control (as the staff forms' "optional" hint), no
  longer "(optional)" in the label. Staff wording unchanged (lower-case "optional").
- **RC25-A3 — Dark mode.** Stand-in in force: the CRM has no dark theme today; the star uses one
  token, `--required-mark` (danger red), which a future dark theme overrides in one place.
- **RC25-A4 — Which currencies.** Stand-in in force: CAD and VND only (what payments and vendor
  bills accept); no USD. Adding one is a one-line change to the server list.
- **RC25-A5 — Currency default.** Stand-in in force: no default (blank); there was no existing
  route- or service-to-currency rule. Should VCA/CAV/CAD bookings default to CAD?
- **RC25-A6 — Legacy currency codes.** Stand-in in force: a code stored before the list stays
  as it is, is accepted when re-sent unchanged, and is copied by a rebook; only a *change* to a
  code outside the list is refused.
- **RC25-A7 — Which saved addresses the recipient picker offers.** Stand-in in force: all of the
  customer's non-billing, non-archived addresses, recipient/both first, sender ones marked
  "(saved as sender)". Alternative: recipient-tagged only (but registered customers have none).
- **RC25-A8 — Saving a new recipient to the address book.** Stand-in in force: a recipient typed
  by hand is stored on the shipment only, not added to the customer's address book (as for the
  sender today).

### B -- Admin-only sign-in email, "Received at warehouse", editing a published event (items 2, 5, 6)

- **RC25-B1 — Links already sent for a self-service email change.** Stand-in in force: refused at
  confirmation with the generic sentence (the live link is consumed and its request closed
  `refused` / `self_service_withdrawn`); a pending request is closed when the customer opens
  "Sign-in and security", otherwise it lapses with its link; no data migration.
- **RC25-B2 — Which accounts an Admin may move.** Stand-in in force: pending approval, active and
  suspended. Not pending verification (the address was never proved — the applicant registers
  again), not rejected, not deactivated (reinstate first).
- **RC25-B3 — Permission for the Admin change.** Stand-in in force: `customer_account:deactivate`
  (with `customer_account:review`), Admin only, the same as reinstatement and re-link.
  Operations cannot change a sign-in email.
- **RC25-B4 — Verification of the new address.** Stand-in in force: the Admin's change is not
  confirmed by a link to the new address (the Admin vouches; the new address is told and the old
  one is warned). `email_verified_at` is left as it was.
- **RC25-B5 — Sessions on an Admin change.** Stand-in in force: every session of the account ends;
  the password is unchanged; the customer signs in again with the new address.
- **RC25-B6 — Reason codes for the Admin change.** Stand-in in force: `customer_request`,
  `mailbox_lost`, `entered_in_error`, plus an optional staff-only note (≤ 500) kept on the change
  row, never in the audit.
- **RC25-B7 — Old "…at our facility." wording on events already published.** Stand-in in force:
  kept as published (immutability); only new events use the warehouse sentence. The edit form
  can switch an old event to the new sentence (recorded as a wording change).
- **RC25-B8 — Customer-visible wording on an edit.** Stand-in in force: a published event's sentence
  changes only to a standard update offered for its type; own wording can be kept, not
  rewritten; no second-person approval (the publish flow has none).
- **RC25-B9 — Publishing through an edit.** Stand-in in force: an edit never publishes or
  unpublishes.
- **RC25-B10 — Milestone email on an edit.** Stand-in in force: none, ever (no queue, send or
  withdraw), even when the type moves to a later milestone.
- **RC25-B11 — Who may edit.** Stand-in in force: `tracking:write` (Admin and Operations), no
  extra Admin-only permission for published events.
- **RC25-B12 — Packages on an edit.** Stand-in in force: a removed package's row is voided with the
  reason "Removed from this event by an edit: …"; an added package gets a row with the original
  entry time and author.
- **RC25-B13 — Does the customer see that an event was corrected?** Stand-in in force: no marker on
  the tracking page or in the account; staff see "Edited" and the edit history.

### C -- the Financials tab (items 7, 8)

* **RC25-C1** — What exactly did Ben type as the currency on shipment 71? *Stand-in in force:* a
  non-three-letter code such as "CA" or "$" (every such value reproduces the blank page; I could not
  open his database). If his shipment shows a normal code, send the browser console error from
  `/shipments/71?tab=financials` — the new error boundary now prints it on the page.
* **RC25-C2** — A bad code already stored (shipment 71) is not rewritten. *Stand-in in force:* the tab
  shows the amounts with the code as stored and a warning; staff correct it in the form. No data
  migration.
* **RC25-C3** — Which currencies are allowed for the recorded amounts? *Stand-in in force:* any three
  letters (as `Intl` accepts), not just CAD/VND — the booking's declared-value list (developer A,
  item 3) is a separate field; tell us if the recorded amounts should be limited to CAD and VND too.
* **RC25-C4** — Who sees vendor cost on the shipment page? *Stand-in in force:* the quote's vendor cost
  follows `tariff:read` (Admin, Operations), as in the Workspace and vendor bills; the manually
  recorded shipping cost keeps its own rule (`financial_cost:read`, Admin only). So Operations sees
  the quote's vendor cost but not the manual "Shipping cost".
* **RC25-C5** — Issue invoice from the shipment page uses the manual path (0 / 5 / 13 %, tax added on
  top), exactly as the Workspace button. *Stand-in in force:* no route-based default rate here; a
  domestic shipment invoiced with tax included still goes through the draft (accept the quote first).
* **RC25-C6** — A shipment that is in no master cannot be priced (a quote needs a master). *Stand-in in
  force:* the tab says "Not in a master yet" and links to the Workspace list; it does not create a
  master.
* **RC25-C7** — The header action. *Stand-in in force:* a secondary **Quote & invoice** button (not the
  primary action, which stays Confirm / Print labels) that opens the Financials tab.

## 00000. RC-UAT-23 invoices (Ben, 2026-10-24) -- confirmed, with stand-ins

**Answered on the evening of 2026-10-24 (Ben, OD-112; RC-UAT-24):** I-1 **confirmed** (English-only
PDF, names without accents, DEC-0237); I-12 **confirmed** (the cent nudge on tiny amounts,
DEC-0238); I-10 **built** (Settings legal entity, login footer and label sender read Solaris
Express Inc., DEC-0236); I-11 **tidied** (the draft editor says "Tax included in the price" with
the invoice's labels, DEC-0239). The held items -- returns (OD-22), staff MFA (OD-17), production
email (OD-34), ShipStation / provider sync (OD-21), retention periods (OD-01, OD-36) -- are
skipped for now, on Ben's word.

**Answered (OD-109, OD-111):** domestic courier rates include GST/HST, and the CRM mimics the
Solaris Invoicing desk. P-9 is closed: quotes keep the tax-inclusive wording; issued invoices
show the net lines and a tax summary (DEC-0235). The choices the developers had to make:

* **I-1 — Vietnamese text on the invoice PDF.** **Confirmed by Ben 2026-10-24 (DEC-0237).** As built: every string printed on a
  new-layout PDF (bill-to name and address, line descriptions, PO, notes) is transliterated —
  NFKD, combining marks dropped, đ→d, Đ→D ("Phạm Thị Thu Trang" → "Pham Thi Thu Trang"). The
  stored data, the staff screens and the invoice email keep the diacritics. Open: is a customer
  name without accents acceptable on a legal invoice?
* **I-2 — Manual Issue invoice.** Stand-in in force: stays **added on top** with its 0 / 5 / 13 %
  picker (the owner's earlier decision), now per line (tax = round_half_up(line × r) per line,
  which can differ by a cent from the old whole-subtotal tax) and on the new layout, with the
  quote lines' quantities (Rate = amount / qty, 4 dp).
* **I-3 — Quantity on draft lines.** Stand-in in force: a draft line has no quantity; it prints
  **Qty 1** and Rate = its net. Staff cannot enter a quantity on a draft.
* **I-4 — Invoices issued before.** Stand-in in force: untouched — gross lines, the whole-total
  figures of DEC-0223, the old PDF layout and labels (Vietnamese for a Vietnamese customer,
  "Prices include …"); only the company block on their PDF is today's. Nothing is migrated.
* **I-5 — One tax row.** Stand-in in force: an invoice carries one rate, so one summary row; the
  code groups by tax code should a mixed invoice ever exist.
* **I-6 — Terms.** Stand-in in force: "Terms: Due on receipt" when `invoice_due_days` is 0 (the
  default, kept); "Terms: Net N days" otherwise, ("Net 1 day" for N = 1). An issued
  invoice computes N from its own issue and due dates.
* **I-7 — STCA- / QuickBooks.** Stand-in in force: no QBO export exists in the CRM, so the desk's
  STCA- customer-ID rule has nothing to change.
* **I-8 — Sale of Product.** Stand-in in force: none; the CRM has no product sale and none is
  invented.
* **I-9 — Language of the new invoice.** Stand-in in force: the invoice document (staff print
  page) and the PDF of a v1 invoice are English for every customer; the "invoice sent" email
  stays in the customer's language (unchanged). A vendor-naming line already stored on a draft
  as the Vietnamese neutral label "Phụ phí" prints as "Phu phi"; an issued line naming a vendor
  reads "Surcharge".
* **I-10 — Other company names.** **Answered 2026-10-24: built in RC-UAT-24 (DEC-0236)** -- Settings, the login footer and the label sender now read Solaris Express Inc. Before: only `finance_service.COMPANY` changed
  (invoices, receipts, printable quote). The staff Settings legal-entity name ("Soleil Global
  Transportation Inc." — `models/staff.py` default, the i18n `legalEntity` strings, the label
  sender in `seed.py` / `scripts/render_sample_labels.py`, `README.md`, `CRM.md`) is untouched.
  Open: should those follow?
* **I-11 — Staff draft wording.** **Tidied in RC-UAT-24 (DEC-0239):** "Tax included in the price: subtotal before tax …, HST ON @ 13% …". Before: the draft editor's tax summary keeps "Prices
  include HST 14 %: subtotal …" (staff UI; amounts are still entered all-in); only documents drop
  the sentence. The typed-form preview (`taxPreview`, echoed on Save and checked by the server)
  now works per line in JS, mirroring the server; the "As the invoice will show it" table is the
  server's breakdown of the saved draft.
* **I-12 — The cent nudge.** **Confirmed by Ben 2026-10-24 (DEC-0238).** As built: the nudge always moves the **net**; the tax stays
  round_half_up(net × r) of the un-nudged net. E.g. 100.00 at 13 % → 88.49 + 11.51 (DEC-0223
  read 88.50 + 11.50).
* **I-13 — UAT pack wording.** Done in RC-UAT-23: the air pack cases that read the old invoice wording now read per DEC-0235; `UAT-BLD-20` to `-24` cover the new layout.

## 0000. RC-UAT-21 build (Ben's direction of 2026-10-24) -- open questions with stand-ins

Ben asked (2026-10-24, OD-110) for every remaining feature to be built now with safe stand-ins,
each recorded here instead of waiting. Nothing below blocks use; each line says what is in force.
Returns (OD-22), staff MFA (OD-17), production email (OD-34) and provider sync (OD-21) were not
started and wait for Ben.

### P-9 (OD-109) -- quote tax wording: **confirmed by Ben, 2026-10-24** (§00000)

Stand-in in force: domestic quotes say GST/HST is included at the destination province's rate
("Giá đã bao gồm HST 13 %" / "Prices include HST 13 %"), matching the invoice back-out;
international quotes say zero-rated ("Thuế suất 0 (0 %)" / "Zero-rated (0 %)"). Confirm, or say
if domestic invoices should add the tax on top instead.

### Phase A -- shipment import and legacy history baseline (OD-15, OD-16)

- **A-1** One CSV row per shipment, with packages and items in `;`-separated cells (not one
  row per package). *Is there a real source export whose shape should win instead?*
- **A-2** Customers are matched by Solaris customer ID (or a former ID) or by the
  `source_record_id` a customer import set; an import never creates a customer; an
  archived or merged-away customer is refused. *Should an import be able to match on phone
  or email, or create the customer?*
- **A-3** A commit needs an **unused** dry run of the same bytes and options by the same
  staff member within 24 hours; a successful commit consumes it (its audit entry records
  `dry_run_event_id`), so a second commit needs a new dry run. A failed commit consumes
  nothing. *Is 24 hours right; may a second person commit another's dry run
  (four-eyes)?*
- **A-4** An import creates no quote, invoice, email, milestone event or notification;
  `booking_state` may be `draft` (default) or `confirmed` (normal confirmation, Solaris ID
  issued, no customer email). *Should confirmed imports email the customer, or start a
  quote?*
- **A-5** Air only; route group defaults to VCA (VN→CA); CAV, CAD and XUS are accepted as the
  booking model allows, still air. *Which route groups should the import accept?*
- **A-6** A mixed file commits its valid rows and reports the rest (rejected, refused
  duplicates), as the customer import does; each row is created in its own savepoint.
  *Should any invalid row block the whole file instead?*
- **A-7** Legacy records are staff-only: shown on Import › Legacy history (search, customer
  link), not on the Customer Account timeline, not on the customer profile, and **not**
  counted in lifetime figures, lifecycle status or repeat-customer share (OD-16 unchanged).
  *Should customers see their own history; should it count in customer metrics?*
- **A-8** Legacy history uses fixed milestone date columns and four final statuses
  (delivered, returned, cancelled, lost); dates only, no times or locations. *Does the old
  system carry more (times, locations, free events)?*
- **A-9** A re-run matches records already live and never updates them; only a whole
  baseline can be voided (no per-record void), with a reason; voided records are kept.
  *Should a re-run update changed records; is per-record correction needed?*
- **A-10** Permissions as the customer import: dry run, commit and void are Admin's alone
  (`import:*`), reading legacy records needs `shipment:read`. *Should Operations import
  shipments?*
- **A-11** Same limits as the customer import (2 MiB, 5,000 rows); a package over 500 kg or
  more than 99 packages per shipment is a row error. *Do these fit the real files (OD-14)?*
- **A-12** Identifier cells (`external_reference`, `legacy_reference`, `customer_ref`)
  starting with `= + - @` or a control character are refused; other text is stored as
  text and escaped on every export (DEC-0081).
- **A-13** Duplicate detection is by `external_reference` among imported shipments only; a
  shipment typed by hand with the same booking reference is not detected. *Should the
  import also compare booking references or recipient + date?*
- **A-14** The baseline cutoff date is optional, and the source system is fixed
  (`legacy_csv`, `csv_shipment_import`). *Is there one cutoff date, and more than one
  source system?*

### Phase B -- password and email change, reinstatement

* **B-1** Staff password change sends no email: there is no staff email seam (the account seam
  is for customers). Should staff be told by email when their password changes?
* **B-2** Customer password change **rotates** the current session (new cookie) rather than
  keeping the same one; every other session is signed out. OK?
* **B-3** **Superseded by RC-UAT-25 (DEC-0243): customers no longer change the sign-in email.** Was: Email change and the customer record: on confirmation the linked customer's email is
  set to the new address (single email rule), written directly (not through the staff edit,
  which refuses a change while the account holds the link). An address on **another** customer
  record (not merged) refuses the change, with the same answer as success. Archived customers
  count as "another customer record". Is that the rule wanted, or should staff review an email
  change like a name/phone change (proposal)?
* **B-4** Reinstating an account that was **suspended** when it was deactivated returns it to
  `suspended` (staff then lift the suspension separately). OK?
* **B-5** Deactivations that are **not** reversible: `privacy_request` only (and a declined
  application). Should `duplicate_account` or `abuse_or_test` also be irreversible?
* **B-6** Reinstating to `active` puts the account's sign-in email back on the linked customer
  if staff changed it while the account was deactivated (as an approval does). OK?
* **B-7** (email part) **Superseded by RC-UAT-25 (DEC-0243): customers no longer change the sign-in email.** The password-change limit stands. Was: Rate limits: password change 5 per 15 minutes per account (customer and staff); email
  change 3 requests per hour per account; confirmation links share the token-redemption limit.
  Wrong current passwords do **not** lock the account (the rate limit does the work). OK?
* **B-8** A domestic quote whose destination province cannot be read says "Prices include
  GST/HST" with no rate (the invoice leaves the rate to staff there). OK?
* **B-9** The quote's tax wording is computed when the quote is read, from the shipment's route
  at that moment (not frozen when the quote was sent). OK?
* **B-10** (P-9 itself) The quote now says GST/HST is **included** for domestic routes and
  zero-rated for international ones, replacing OD-108's "Taxes, if any, are added on the
  invoice". Confirm, or restore OD-108's note.
* **B-11** (email part) **Superseded by RC-UAT-25 (DEC-0243): customers no longer change the sign-in email.** The password part stands. Was: A pending-approval account (no linked customer) may change its password and email;
  the email change has no customer record to update. OK?
* **B-13** Reinstating an account whose linked customer was merged (either direction since
  the deactivation) or archived ends the link and returns the account to `pending_approval`.
  **Built in RC-UAT-22 (DEC-0234):** such an account appears under **Customer accounts →
  Accounts needing a customer**, where an Admin re-links it to a customer (after reading and
  acknowledging the history the link opens) or closes it. The choices made are B-15 to B-20
  below. Still open: should reinstatement instead be refused outright in that case?
* **B-14** **Superseded by RC-UAT-25 (DEC-0243): customers no longer change the sign-in email.** Was: A pending email change is cancelled (not just left to expire) by a password change
  or reset, and the current address is told of every request. OK?
* **B-15** A re-linked account keeps its original approval date; the re-link is recorded on its
  own row (`customer_account_relinks`) rather than as a second approval. OK?
* **B-16** A re-link never takes over a customer that already holds a link of any kind (even a
  deactivated account's), unlike an approval, which may take over a deactivated account's link.
  Stand-in in force: refused; staff close or unlink the other account first. OK?
* **B-17** The approval's acknowledgement record needs a registration proposal, which an orphan
  does not have, so the re-link requires the same history preview and tick and stores the
  acknowledged figures on its own row. OK, or should a re-link need a second person?
* **B-18** The customer gets the ordinary "your account is approved" email when re-linked (test
  capture only). Stand-in in force; say if you want a different wording.
* **B-19** Closing an orphaned account sends the customer nothing. Stand-in in force; should
  they be told?
* **B-20** A closed orphan (`orphan_closed`) can be reinstated later by an Admin, which brings it
  back to the "Accounts needing a customer" list. Stand-in in force; or should closing be final?
* **B-12** **Superseded by RC-UAT-25 (DEC-0243): customers no longer change the sign-in email.** Was: A request refused by the single email rule still shows "pending" (so the screen does
  not reveal that the address is taken); it simply never completes and expires after 24 h. The
  owner of the other address is **not** told someone tried. OK?

### Phase D -- quote soft delete and retention (OD-01, OD-36, OD-107)

* **D-1** Which quote versions may be deleted. Stand-in: refuse drafts, versions on an unvoided
  invoice or a live draft invoice, offers still open, and accepted offers of shipments not yet
  invoiced; allow superseded, expired, withdrawn/declined and finalised-unsent versions.
* **D-2** Soft delete only (rows kept, hidden). Should an Admin ever be able to erase a quote
  outright, outside a decided retention period? Stand-in: no.
* **D-3** "Old" = older than a configurable minimum age, default **0 days** (any eligible
  version). What age does the owner want?
* **D-4** Restore is allowed (Admin, reason, audited). Should it be?
* **D-5** Is deleting the shipment's latest finalised-unsent version acceptable? Stand-in: yes,
  and it then cannot be sent or invoiced until restored or re-quoted.
* **D-6** Retention record classes and actions (eight listed above). Which records does the owner
  want covered, delete or anonymise, and with what period each (OD-01)? Financial records,
  payments, vendor bills and audit events are not covered at all.
* **D-7** Legal hold: none exists. Stand-in: classes under potential hold are simply not offered.
* **D-8** Tariff intake raw files: only the row's sender and subject are anonymised; the stored
  `.eml` files on disk are not touched. Should the files be deleted, and after how long?
* **D-9** Import dry-run reports: no stored dry-run report exists to clean up (previews are not
  persisted), so no class is offered. Revisit if Phase A stores previews.
* **D-10** Enabling: global switch by Admin with the typed phrase `ENABLE RETENTION`; then each
  class needs a period. Owner approval is required by wording only (no second approver). Should a
  second person (the owner) have to approve?
* **D-11** The worker never runs automatically (no scheduler). When a period is decided, should it
  be scheduled, and how often? Batch size 200, at most 1000 batches per class per run.
* **D-12** Customer Account: a deleted quote reads as "does not exist" (404). Should the customer
  be told it was removed instead?

## 000. Answered on 2026-10-23 (Ben) -- RC-UAT-20

P-1 to P-7 below are answered (OD-102 to OD-108, recorded in `05_OPEN_DECISIONS.md`). Still open:

| # | Question | In force now |
|---|---|---|
| P-8 | Python 3.15 on tester PCs: upgrade the pinned packages once they publish 3.15 builds? | 3.11 to 3.14 supported; 3.15 refused with a clear message |
| P-9 | **Confirmed by Ben 2026-10-24 (OD-109, OD-111; see §00000).** Domestic quotes say "Tổng cộng" with the note that tax is added on the invoice (kept as asked, OD-108), but a domestic draft invoice backs the tax out of that same total (OD-102). Should domestic quotes say "tax included", or should domestic invoices add the tax on top? | Wording kept; domestic invoices back the tax out |
| P-10 | Domestic (Canada to Canada) shipments cannot be quoted in the app today: air masters take Vietnam to Canada only, so the province rates are reachable only through the automated tests and three seeded UAT shipments. Is a domestic service coming, and on which product? | Rules built and tested; UAT uses seeded shipments |

Stand-ins introduced by the RC-UAT-20 work (in force; confirm or correct):

| # | Stand-in | In force |
|---|---|---|
| R-1 | Domestic shipment, destination province unknown | No rate filled in; staff must choose before Save; Send/Download refused until then |
| R-2 | Where the province comes from | The recipient postal code first (its first letter), then the address text (case-sensitive codes, English/French names); a disagreement means unknown |
| R-3 | Which countries define the route | Shipment codes, else sender/recipient address codes, else route group; any US end = international |
| R-4 | Rates are whole percents; Admin range 0–30; labels GST/HST only | Integer column on drafts |
| R-5 | A rate edit applies to drafts created afterwards; existing drafts keep theirs | |
| R-6 | Who sees / edits the table | `financial:read` sees; Admin (`settings:manage`) edits |
| R-7 | Costume jewellery customer price: no markup on top | Charge = CAD price exactly |
| R-8 | Costume jewellery CAD cap | 9,999,999,999.99 (column limit) |
| R-9 | Payment date "not in the future" | By date in America/Toronto, or the staff zone when ahead; an offset sent with a date is ignored |
| R-11 | Postal code and province text disagree, or the text names two provinces | Unknown: staff choose |
| R-12 | 0 % label in Vietnamese | "Thuế suất 0 (0 %)" (proposed) |
| R-13 | Table label on documents only when the draft's rate equals the province's auto-filled rate | Otherwise "GST/HST" |
| R-14 | Legacy payment rows (before the fix) | A non-midnight time keeps its old Toronto-local date; an exact 00:00 UTC row now reads as that plain date (one day later than before) |
| R-10 | UAT seed A1-1 (VN-CA) | Now invoiced at 0 % (route rule) instead of 13 %; `uat_env --check` "invoice tax choices" now 2 (0, 5 %) |

## 00. Answered on 2026-10-22 (Louis Tong) and new open questions (RC-UAT-19)

F-1 to F-10, Q-P1 and Q-P2 below are answered (OD-91 to OD-101, recorded in
`05_OPEN_DECISIONS.md`). New questions from those answers and from the RC-UAT-19 work, each with
the stand-in in force (nothing waits on them):

| # | Question | In force now |
|---|---|---|
| P-1 | **Answered 2026-10-23 (see §000).** Which GST/HST rate should auto-fill on a draft invoice for VN to CA air? (OD-64 said 0 % for international moves.) | 13 % auto-filled; staff change it per invoice |
| P-2 | **Answered 2026-10-23 (see §000).** Is GST/HST backed out of the all-in price, or added on top? | Backed out (included in the price) |
| P-3 | **Answered 2026-10-23 (see §000).** Costume jewellery manual quote: do staff enter the vendor's cost or the customer's price? | The vendor's quoted VND amount; the customer price follows conversion and markup |
| P-4 | **Answered 2026-10-23 (see §000).** Vietnamese leg names for customers: "Theo dõi chặng chính" (Master Tracking) and "Theo dõi chặng cuối" (Last Mile Tracking) -- acceptable? | Used as proposed, flagged for review |
| P-5 | **Answered 2026-10-23 (see §000).** A tracking link whose web address names the vendor: hide it (stand-in) or show it with a neutral label? | Hidden |
| P-6 | **Answered 2026-10-23 (see §000).** Shipments invoiced without a draft (manual Issue invoice) still add GST/HST on top at the chosen rate. Align them with drafts (13 % included)? | Unchanged: added on top |
| P-7 | **Answered 2026-10-23 (see §000).** Admin manual delete of retained quote records (OD-95, OD-98): when should we build it? | Future item; not built |
| P-8 | Python 3.15 on tester PCs: five pinned packages have no 3.15 build yet. Upgrade the pins when they do? | 3.11 to 3.14 supported (3.12 recommended, 3.14 tested); 3.15 refused with a clear message |

## 0. Answered on 2026-10-21 (Louis Tong, on Ben's behalf)

Rows 1 to 6, 8, 9 and 11 of sections 1 to 3 are answered (OD-81 to OD-90, recorded in
`05_OPEN_DECISIONS.md` and the register); they are kept below as history, marked **Answered**.
Applied in the RC-UAT-18 fix pack (`22_FIXPACK_RC18_RECORD.md`).

### New follow-up questions from the answers (stand-in in force; nothing waits on them)

| # | Question | In force now |
|---|---|---|
| F-1 | **Answered 2026-10-22 (see §00).** HCM row 27 costume jewellery (quoted case by case): its note is silent, the sheet footer says full carton, current behaviour is the item's own kg. Keep the item's kg? | Item's own kg (kept, OD-83) |
| F-3 | **Answered 2026-10-22 (see §00).** Draft invoice on acceptance: confirm staff still choose GST/HST before sending | Staff choose 0 / 5 / 13 % on the draft before Send |
| F-4 | **Answered 2026-10-22 (see §00).** A quote with an issued invoice when a new tariff becomes active (goods not yet received) | Does not expire; the issued invoice keeps the existing void / reissue rules |
| F-5 | **Answered 2026-10-22 (see §00).** Should the customer be emailed when their quote expires? | No email; the Customer Account shows it as expired and staff re-quote |
| F-6 | **Answered 2026-10-22 (see §00).** After an Admin unlock, when should a master lock again? | Admin or Operations locks it again by hand, or it relocks when a member's quote is finalised |
| Q-P1 | **Answered 2026-10-22 (see §00).** Public tracking and the Customer Account keep the last-mile carrier's tracking link (UPS, Canada Post and the other allowed hosts), which names that carrier (not the air vendor). Acceptable, or remove the link? | Kept; a link whose host or staff-typed label names the air vendor is hidden |
| Q-P2 | **Answered 2026-10-22 (see §00).** Staff-typed customer milestone messages: vendor names are now replaced on output by 'đối tác vận chuyển' / 'carrier'. Agree? | Replaced on output |
| F-7 | **Answered 2026-10-22 (see §00).** A quote on a booked or completed master does not expire on a new tariff (a booked master is priced at its booked tariff). Agree? | Does not expire |
| F-8 | **Answered 2026-10-22 (see §00).** An `exception` milestone alone does not count as "goods received" for expiry. Agree? | Not received |
| F-9 | **Answered 2026-10-22 (see §00).** Leaving the draft invoice with unsaved edits by the browser's Back button is not intercepted (links, reload and closing the tab are). Acceptable for now? | Not intercepted |
| F-10 | **Answered 2026-10-22 (see §00).** Vendor names are matched as whole vendor names (plus "Kango"); a partial name (e.g. "Demo Carrier" for "Demo Carrier Co") is not caught. Acceptable? | Whole names only |

## 1. Prices and vendor data

| # | Question | In force now | If you answer otherwise |
|---|---|---|---|
| 1 | **Answered (OD-81): correct, no flag.** **D-07:** the Express zone 2 price drops at 16 kg. Is that a typo or intended? | The printed bracket price is used as imported; flagged only in the import report, not at quote time (until OD-81) | We correct the imported rate. If the vendor sends a fixed workbook, it comes through the normal tariff approval. No code change |
| 2 | **Answered (OD-82): 20,000 VND/kg for VN-CA.** **D-09:** HCM air meat / egg / dairy / honey: is it 20,000 or the printed 10,000 VND/kg? | 20,000 VND/kg (the sheet's rate for "all other air routes"), priced, not flagged, on the whole carton | If 10,000 is right, we correct the rule's price. Quotes already finalised keep their figures |
| 3 | **Answered (OD-83): follow the notes; silent keeps current.** **V-20:** other per-kg surcharges (not pharma): are they charged on the item's own kg or on the whole carton? | The whole carton, as the sheet footer says (pharma is already on the item's own kg, OD-70) | We set the weight basis to "the item's own weight" in Settings → Pricing for those rules. A setting, not a code change |
| 4 | **Answered (OD-86): no default.** Should Air Express have a default selling rate? | None. Operations types the rate on each Air Express quote, and because there is no default, every Air Express rate needs a typed reason | Admin enters it in Settings → Pricing. A setting |

## 2. Wording customers read

| # | Question | In force now | If you answer otherwise |
|---|---|---|---|
| 5 | **Answered (OD-84): no vendor name; neutral labels.** Are the surcharge names on quotes safe for customers to see? They come from the vendor's sheet | The vendor's rule name is printed on the quote, the printed quote and the invoice | We add a customer-facing name per surcharge rule. That is a small screen and data change |
| 6 | **Answered (OD-85): accepted as is.** Can Vietnamese-speaking staff review the Vietnamese wording? This covers the Customer Account, emails, quotes, tariff screens and the 17 standard updates (OD-08, OD-09) | Machine-checked for completeness only. No native speaker has read it | We change the text in the translation files. No logic change |
| 7 | Are the account's standard update sentences the wording you want customers to read? | The standard sentence for each event, in the customer's language, with staff's published text underneath | We change the sentences in the translation files |

## 3. How the workflow runs

| # | Question | In force now | If you answer otherwise |
|---|---|---|---|
| 8 | **Answered (OD-89, OD-90): a draft invoice is created.** When a customer accepts a quote, should the invoice be issued automatically? | No. Staff get a prompt in the workspace and in Finance ("Accepted, not invoiced") and issue the invoice themselves, choosing GST/HST | Automatic issue would need a rule for the GST/HST choice. Small change |
| 9 | **Answered (OD-89): only before goods are received, when a new tariff becomes active.** Should a sent quote expire? | No expiry | We add an expiry date to the offer and the account page. Small change, probably with one new column |
| 10 | Should we allow sending a quote while a newer draft is open? | Refused: finalise the draft first | We would have to decide which price the customer sees. Not recommended |
| 11 | **Answered (OD-87): Ben's mailbox for now; provider still open.** Which mailbox should vendor rate emails come from (Microsoft 365 or Gmail), and when? | No mailbox is connected. Staff upload the `.eml` or drop it in the intake folder. Ben is the approver (OD-76) | We build the mailbox connection for that provider. Needs credentials and a production plan |
| 12 | Should approvers or customers get reminder emails? | None. Approvers see a count badge in Settings | We add the email. Small change, test capture only until a provider exists |

## 4. Open decisions in the register (OD-01 to OD-22)

| OD | Question | In force now | If you answer otherwise |
|---|---|---|---|
| OD-01 | How long do we keep each kind of record? | Nothing is ever deleted | We build a deletion job with its own audit trail. Production only |
| OD-02 / OD-03 | Final permissions for Operations and Marketing | Import and shipment/report exports are Admin only. Operations holds the tariff permission, so it sees vendor cost in the Workspace, Payables and Profitability; only Admin sees carrier costs (`financial_cost:read`). Marketing sees no cost and may export marketing segments | A permission change in one file. Staff need retraining |
| OD-04 | Customer lifecycle thresholds | 30 / 60 / 90 days. Admin can edit them in Settings | Admin changes them in Settings. No code |
| OD-05 | Which domain the public tracking page uses | A local development address. Production refuses it | A configuration value at deployment |
| OD-06 | Public help link | No link is shown | A configuration value |
| OD-07 | Which carrier tracking sites we may link to | Nine sites, allowed for UAT only | We edit the list |
| OD-10 to OD-13 | Hosting provider, where the data is stored (residency), RPO and RTO | Nothing is hosted. Backup targets are on paper only | Production planning. No app change expected |
| OD-14 | Import file limits | 2 MiB and 5,000 rows | We change a setting |
| OD-15 / OD-16 | Shipment CSV import, and loading past shipment history | Deferred until real source data exists | New import work |
| OD-17 | Do staff need two-factor sign-in (MFA)? | No MFA: email and password | We build MFA before production |
| OD-18 | Testing the real label printer and scanner | Never tested on real hardware | A hands-on test session. Fixes only if it fails |
| OD-19 | Who tests with a screen reader and zoom? | Only the automated accessibility checks run | We name a reviewer and fix what they find |
| OD-20 | Who may approve going to production? | Production deployment is not allowed | We name the person and write the release steps |
| OD-21 | ShipStation account details (nine questions) | The integration is switched off | Provider work starts. Not needed for UAT |
| OD-22 | Returns: workflow and policy | Not built. Returns always report 0 | We build returns: new screens and data |
| OD-34 | Which email provider for production? (OD-34 is answered, but no provider has been chosen yet) | Test capture only. Nothing reaches a customer | We connect the provider. This blocks production registration and emails |
| OD-37 | Can you supply the approved terms and privacy text? (OD-37 is answered, but the text has not been supplied) | Placeholder versions. Production registration is refused | We load the text and its version numbers |

Hosting, retention and the email provider only matter for production. None of them blocks UAT.
