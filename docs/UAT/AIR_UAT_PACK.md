# Air pricing, quotes and money — UAT pack (Phases 13A to 15, the RC-UAT-18, RC-UAT-19 and RC-UAT-20 owner answers, and the RC-UAT-21 build)

> **⚠ PREPARED, NOT EXECUTED.** Every **Evidence obtained**, **Result**, **Defect**,
> **Tester**, **Date** and sign-off field below is blank because no case has been run. Do
> not fill them in except while actually performing the step. `scripts/verify_uat_blank.py`
> checks this pack as it checks the other two.
>
> **Two kinds of field, and the difference matters.** **Evidence to capture** is written
> in advance: it tells the tester what to collect, and it is part of the case definition,
> not a record of anything. **Evidence obtained** is what the tester actually captured,
> and it starts blank like **Result** and **Defect**.

**Air only.** Every case is Air Standard or Air Express, from Hồ Chí Minh City, Vietnam to
Canada. Sea is not priced (OD-49). **Every case uses synthetic data** on `example.com`;
**never substitute a real customer**. No email reaches anybody: messages are written to
`data/uat/account_mail` (test capture). Nothing here calls the bank or the vendor.

**How to fill a case in:** as in `UAT_CASES.md`. Collect what **Evidence to capture** names,
record it in **Evidence obtained**, enter `Pass`, `Fail` or `Blocked` in **Result**, and put
the defect id (`DEFECT_TEMPLATE.md`) in **Defect**.

**Where the screens are.** `docs/STAFF_GUIDE.md`, part "Air masters, quotes and money", names
every button used below. How to start the environment: `HOW_TO_RUN.md`, then
`ENVIRONMENT.md` §3a. The owner's guided walk-through of this pack is
`UAT_SCRIPT_FOR_BEN.md`.

---

## Blocked by an open owner decision

Source: `docs/b2c_merge/19_OWNER_QUESTIONS.md` and `05_OPEN_DECISIONS.md`. **Nothing in this
pack is blocked.** The owner answered OD-81 to OD-90 on 2026-10-21 (Louis Tong, on Ben's
behalf; applied in the RC-UAT-18 fix pack, DEC-0219 to DEC-0222) and OD-91 to OD-101 on
2026-10-22 (Louis Tong, on Ben's behalf; applied in the RC-UAT-19 fix pack), and Ben answered
OD-102 to OD-108 on 2026-10-23 (P-1 to P-7 and the wording; applied in the RC-UAT-20 fix pack,
DEC-0227 to DEC-0229): those cases now test the answer. On 2026-10-24 Ben directed that every
remaining feature be built now with safe stand-ins (OD-110; the RC-UAT-21 build, DEC-0230 to
DEC-0233, record `docs/b2c_merge/25_BUILD_RC21_RECORD.md`), tested by the `UAT-BLD` group. Ben's live UAT findings of 2026-10-25 (OD-113) were fixed in
RC-UAT-25 (DEC-0240 to DEC-0247, record `docs/b2c_merge/29_BUILD_RC25_RECORD.md`), tested by
`UAT-BLD-09` (rewritten) and `UAT-BLD-26` to `-33`.
Every question still open (P-8, P-9 / OD-109, the RC-UAT-21 stand-ins A-1 to A-14, B-1 to
B-14 and D-1 to D-12, the RC-UAT-20 developer stand-ins and the older ones below) has a
stand-in in force, and the stand-in is what the case tests. Record `Pass` when the answer or stand-in behaves as written. If the owner later answers
a stand-in otherwise, the case's expected result changes with the answer; record the finding
as an observation (S5), not a failure.

### Answered on 2026-10-21 (now tested as answered)

| Question (sheet 19) | Answer under test | Cases |
|---|---|---|
| **#1 D-07** — Express zone 2 price drop at 16 kg | **OD-81**: correct; priced as printed. The three drops (HCM-AIR-CAD!F39, HN-AIR-CAD!F38, HN-AIR-CAD!G38) are listed in the import report as confirmed price steps, not warnings | `UAT-TAR-01`, `UAT-OWN-13` |
| **#2 D-09** — HCM meat / egg / dairy / honey | **OD-82**: 20,000 VND/kg for route VN-CA, on the whole carton | `UAT-OWN-14` |
| **#3 V-20** — weight basis of other per-kg surcharges | **OD-83**: as each sheet note says; a silent note keeps the current basis (the whole carton); pharma on the item's own kg (OD-70) | `UAT-PRC-03` |
| **#4** — a default Air Express rate | **OD-86**: none; every Air Express rate is typed with a reason | `UAT-PRC-04`, `UAT-OWN-16` |
| **#5** — vendor surcharge names on customer documents | **OD-84**: no vendor name on anything a customer reads. A label naming a vendor reads **Phụ phí** / **Surcharge** in the customer's language; staff screens keep the vendor's wording | `UAT-WSQ-02`, `UAT-QAC-01`, `UAT-FIN-01`, `UAT-OWN-15` |
| **#6 / OD-08 / OD-09** — native review of the Vietnamese wording | **OD-85**: accepted as is. Findings are still welcome as S5 | `UAT-VIA-*`, `UAT-MLS-*` |
| **#8** — invoice on acceptance | **OD-89**: acceptance prepares the invoice as a **draft** (no `INV-` number); staff open **Review draft invoice** and **Send invoice**. Manual **Issue invoice** is refused while a draft exists | `UAT-QAC-02`, `UAT-OWN-08` to `-12` |
| **#9** — quote expiry | **OD-89**: a quote expires only when the goods are not yet received **and** a new tariff version becomes active | `UAT-OWN-05` to `-07` |
| **#11** — the vendor rate mailbox | **OD-87**: `benjamin.le@soleiltransportation.com` for now (the default; UAT stores demo addresses instead) | `UAT-TAR-*`, `UAT-OWN-17` |
| — **edits after booking** | **OD-88**: a booked master locks its shipments' items and fees; an Admin unlocks with a reason, audited | `UAT-WSQ-04`, `-05`, `UAT-QAC-03`, `UAT-OWN-01` to `-04` |
| — **the draft invoice screen** | **OD-90**: Save, Send, Download, Edit; save before anything else; edits audited | `UAT-OWN-09` to `-12` |

### Answered on 2026-10-22 (now tested as answered)

| Question (sheet 19) | Answer under test | Cases |
|---|---|---|
| **Q-P1** — the last-mile carrier link | **OD-91**: links stay visible; no vendor name in any label or text around them. The link reads under a generic name; the stored label is never shown (the RC-UAT-18 rule that hid a link whose label named a vendor is reverted) | `UAT-OWN-15`, `-23`, `-24` |
| **Q-P2** — vendor names in milestone and tracking names | **OD-92**: generic names, **Master Tracking** (Vietnam to the vendor's warehouse in Canada) and **Last Mile Tracking** (the vendor's warehouse to Solaris or the final destination). Staff-typed milestone text still has a vendor's name replaced ("đối tác vận chuyển" / "carrier") | `UAT-OWN-23`, `-24`; `UAT-VIA-02` (observe only) |
| **F-1** — HCM row 27 costume jewellery | **OD-93**: a manual quote: staff enter the amount for the line; no kg basis | `UAT-OWN-25` to `-27`; `UAT-PRC-03` |
| **F-3** — GST/HST on the draft | **OD-94**: rates are all-in: the tax is **included in the price** (backed out of the lines); staff tick "I have checked the GST/HST on this invoice" before **Save draft** and **Send invoice**; any change to the rate, the mode or a line clears the tick; staff may change the rate and switch to **Added on top**. The 13 % starting rate was replaced by the route rule on 2026-10-23 (OD-102, below) | `UAT-QAC-02`, `UAT-OWN-08` to `-12`, `-18` to `-22` |
| **F-4** — a quote with an issued invoice when a new tariff activates | **OD-95**: does not expire; the invoice is never touched (an Admin delete of retained records is a future item, P-7) | `UAT-OWN-06` |
| **F-5** — an email when a quote expires | **OD-96**: none; the account shows the quote as expired and staff re-quote | `UAT-OWN-05` |
| **F-6** — when an unlocked master locks again | **OD-97**: **Lock again** by hand, or by itself when a member's quote is finalised | `UAT-OWN-03`, `-04`, `-27` |
| **F-7** — a booked or completed master's quotes | **OD-98**: never expire: a booked master is priced at the tariff it was booked under | `UAT-TAR-02`, `UAT-OWN-05` |
| **F-8** — an *exception* milestone | **OD-99**: does not count as "received" (an exception alone does not protect a quote) | Not exercised by a case; record an observation if met |
| **F-9** — the browser's Back button on an unsaved draft | **OD-100**: not intercepted, no warning (in-app links, reload and closing the tab are) | `UAT-OWN-09` |
| **F-10** — whole-word matching of vendor names | **OD-101**: kept as built | `UAT-OWN-15` |

### Answered on 2026-10-23 (now tested as answered)

Ben's answers to the RC-UAT-19 questions (`05_OPEN_DECISIONS.md`, "Owner answers to the
RC-UAT-19 questions"; `19_OWNER_QUESTIONS.md` §000).

| Question (sheet 19) | Answer under test | Cases |
|---|---|---|
| **P-1, P-2** — the GST/HST rate filled in on a draft, and included or added | **OD-102**: by route. **International** (one end outside Canada: VN-CA, CA-VN, CA-US, …) is zero-rated, **0 %**. **Domestic** (both ends in Canada) is **included in the price** and backed out at the **destination** province's rate: ON 13 % HST; NS 14 % HST; NB, NL, PE 15 % HST; every other province and territory 5 % GST. The rates live in **Settings → GST/HST rates** (Admin edits). Staff may still change the rate and the mode; the tick is still required | `UAT-QAC-02`, `UAT-OWN-08` to `-12`, `-18` to `-22`, `-28` to `-30` |
| **P-3** — costume jewellery: the vendor's cost or the customer's price | **OD-103**: both. Staff enter the vendor's cost in VND **and** the customer price in CAD; neither is prefilled; the quote cannot be finalised until both are entered | `UAT-OWN-25` to `-27`, `-32` |
| **P-4** — the Vietnamese leg names "Theo dõi chặng chính" / "Theo dõi chặng cuối" | **OD-104**: approved | `UAT-OWN-15`, `-23`, `-24`, `-33` |
| **P-5** — a tracking link whose web address names the vendor | **OD-105**: stays hidden (the next safe link, if any, is shown) | `UAT-OWN-24` |
| **P-6** — manual **Issue invoice** (no draft) | **OD-106**: unchanged: GST/HST added on top at the chosen rate (0, 5 or 13 %), no confirmation. Its hint now reads "Added on top at the rate you choose. (Drafts from accepted quotes fill the rate in from the route.)" | `UAT-FIN-01`, `-04` |
| **P-7** — Admin delete of retained quote records (OD-95, OD-98) | **OD-107**: later — since built on Ben's direction of 2026-10-24 (OD-110, DEC-0233) as an Admin **soft delete** with restore; see below | `UAT-BLD-15`, `-16` |
| — wording | **OD-108**: keep the customer quote's **Tổng cộng** and **Ghi chú từ Solaris Express**. The quote's tax note ("Thuế, nếu có, sẽ được tính trên hóa đơn.") is **replaced** in RC-UAT-21 by the OD-109 stand-in below, pending Ben | `UAT-OWN-35` |
| — RC-UAT-20 findings (DEC-0229) | Fixed: a payment's received date is shown as entered; **Download PDF (draft)** waits for the GST/HST check like **Send invoice**; the final delivery leg offers the vendor as provider, and each staff leg shows its generic tracking name; **Settings → Tariffs** shows each version's import warnings | `UAT-OWN-30`, `-31`, `-33`, `-34` |

### Answered on 2026-10-24 (now tested as answered)

| Question | Answer under test | Cases |
|---|---|---|
| — build direction | **OD-110** (Ben): build every remaining feature now; use safe stand-ins and record each as an open question. Built: shipment CSV import and the legacy history baseline (DEC-0230), customer and staff password change, customer email change, Admin reinstatement of a deactivated account (DEC-0231), the quote tax wording (DEC-0232), Admin soft delete of old quote versions and the retention machinery, **off** (DEC-0233). Not started, waiting for Ben: returns (OD-22), staff MFA (OD-17), production email (OD-34), provider sync (OD-21). Since RC-UAT-25 the sign-in email is changed by an Admin only (RC25-B1 to B6); B-3 (customer change), B-7 (the email-change limit), B-11 (email part), B-12 and B-14 (request notice) no longer apply | `UAT-BLD-01` to `-17` |

### Answered on 2026-10-25 (now tested as answered)

| Question | Answer under test | Cases |
|---|---|---|
| — Ben's live UAT findings | **OD-113** (Ben): required fields show a red asterisk, no "(required)" (DEC-0240); the declared value currency is a list, CAD or VND (DEC-0241); the recipient can use a saved address (DEC-0242); **the customer cannot change the sign-in email: an Admin changes it** (DEC-0243); the received event reads **Received at warehouse** (DEC-0244); a recorded timeline event, published or not, can be corrected with a reason and an edit history, never re-publishing or emailing (DEC-0245); the Financials tab no longer blanks the page (DEC-0246) and opens with a **Quote and invoice** card (DEC-0247) | `UAT-BLD-09`, `UAT-BLD-26` to `-33`; `UAT-BLD-10` withdrawn |

### Still open: a stand-in is in force (none blocks a case)

| Question | Stand-in under test | Cases |
|---|---|---|
| **P-9 / OD-109** — the customer quote's tax wording (confirmed by Ben, 2026-10-24) | The quote follows the invoice rule (DEC-0232): **domestic** "Giá đã bao gồm HST 14 %" / "Prices include HST 14 %" at the destination province's rate and label ("Giá đã bao gồm GST/HST" / "Prices include GST/HST" when the province is unknown, B-8); **international** "Thuế suất 0 (0 %)" / "Zero-rated (0 %)". The total stays **Tổng cộng** / **Total**; the RC-UAT-20 note "Thuế, nếu có, sẽ được tính trên hóa đơn." is gone from the account quote and the printed quote ("Total before tax" now reads **Total**). Amounts unchanged | `UAT-BLD-14`; also `UAT-OWN-35`, `UAT-WSQ-02` step 6, `UAT-QAC-01` step 4 |
| RC-UAT-21 stand-ins **A-1 to A-14** — shipment import and legacy history (OD-15, OD-16) | In short: one row per shipment, packages and items in `;`-separated cells (A-1); existing customers only, by Solaris customer ID or import source ID (A-2); a commit needs an unused matching dry run by the same person within 24 h, consumed by the commit (A-3); no quote, invoice, email or notification (A-4); air only, VCA by default (A-5); valid rows import, the rest are reported (A-6); legacy records staff-only and outside customer metrics (A-7); fixed milestone date columns, four final statuses (A-8); re-run matches, whole-baseline void only (A-9); Admin only (A-10); customer-import limits, 99 packages, 500 kg (A-11); formula-like identifiers refused (A-12); duplicates by `external_reference` only (A-13); optional cutoff, fixed source system (A-14). Full text: `19_OWNER_QUESTIONS.md` §0000 | `UAT-BLD-01` to `-07` |
| RC-UAT-21 stand-ins **B-1 to B-14** — password, email change, reinstatement, quote wording | In short: no email to staff on a password change (B-1); the customer's own session is rotated, every other one signed out (B-2); a confirmed email change moves the linked customer's email; an address in use elsewhere gets the same answer as success (B-3, B-12); a suspended account is reinstated as suspended (B-4); a privacy-request deactivation cannot be reinstated (B-5); reinstating to active puts the sign-in email back on the customer (B-6); rate limits 5 password changes per 15 min, 3 email-change requests per hour, no lockout (B-7); B-8 to B-10 are the quote wording (OD-109 row above); a pending-approval account may change its password and email (B-11); reinstating after a merge or archive returns the account to pending approval, with no staff re-link path yet (B-13); a password change or reset cancels a pending email change, and the current address is told of every request (B-14). Since RC-UAT-25 the sign-in email is changed by an Admin only (RC25-B1 to B6); B-3 (customer change), B-7 (the email-change limit), B-11 (email part), B-12 and B-14 (request notice) no longer apply. Full text: §0000 | `UAT-BLD-08`, `-09`, `-11` to `-14` |
| RC-UAT-23 stand-ins **I-1 to I-13** — invoices on the Solaris Invoicing layout (OD-111, DEC-0235) | In short: names without accents on the PDF (I-1); the manual Issue invoice stays added on top (I-2); draft lines print Qty 1 (I-3); invoices issued before are untouched (I-4); one tax row (I-5); Terms "Due on receipt" at 0 days (I-6); the cent nudge moves the net (I-12) | `UAT-BLD-20` to `-24` |
| RC-UAT-22 stand-ins **B-15 to B-20** — re-link or close an account left without a customer (B-13, DEC-0234) | In short: the original approval date is kept (B-15); a customer already holding any link is refused (B-16); the history is previewed and acknowledged by the one Admin (B-17); the ordinary "approved" email on re-link (B-18); nothing sent on close (B-19); a closed account can be reinstated (B-20) | `UAT-BLD-18`, `-19` |
| RC-UAT-21 stand-ins **D-1 to D-12** — quote soft delete and retention (OD-01, OD-36, OD-107) | In short: drafts, versions on an issued or live draft invoice, open offers and accepted-not-invoiced versions cannot be deleted (D-1); soft delete only, restore allowed (D-2, D-4); minimum age 0 days (D-3); the latest finalised-unsent version may be deleted and then cannot be sent until restored (D-5); eight record classes, financial records never (D-6); no legal hold (D-7); stored `.eml` files untouched (D-8); no dry-run report class (D-9); the switch needs the typed phrase only, no second approver (D-10); no scheduler (D-11); a deleted quote reads as "not found" to the customer (D-12). **Retention is off and stays off in UAT**: testers dry-run only. Full text: §0000 | `UAT-BLD-15` to `-17` |
| RC-UAT-25 stand-ins **RC25-A1 to A8** — asterisks, the currency list, the saved recipient (DEC-0240 to DEC-0242) | In short: the star is visual only, the control carries `aria-required` (A1); "Optional" / "Không bắt buộc" under the control in the Customer Account (A2); one colour token, no dark theme (A3); CAD and VND only (A4); no currency default (A5); a code stored before the list is kept (A6); every non-billing saved address, recipient ones first, sender ones marked "(saved as sender)" (A7); a recipient typed by hand is not saved to the address book (A8). Full text: `19_OWNER_QUESTIONS.md` §000000 | `UAT-BLD-26` to `-28` |
| RC-UAT-25 stand-ins **RC25-B1 to B13** — Admin-only sign-in email, "Received at warehouse", editing a published event (DEC-0243 to DEC-0245) | In short: old self-service links refused, pending requests closed (B1); an Admin may move pending-approval, active and suspended accounts (B2), Admin only (B3), no link to the new address (B4), every session ends (B5), three reason codes and a staff-only note (B6); "…at our facility." kept on events already published (B7); a published sentence changes only to a standard update (B8); an edit never publishes (B9) and never emails (B10); `tracking:write` edits (B11); removed packages' rows voided (B12); no "edited" marker for the customer (B13). Full text: §000000 | `UAT-BLD-09`, `-29` to `-31` |
| RC-UAT-25 stand-ins **RC25-C1 to C7** — the Financials tab (DEC-0246, DEC-0247) | In short: the exact currency Ben typed on shipment 71 is unknown, any non-three-letter code reproduces it (C1); a bad stored code is not rewritten, it shows with a warning (C2); any three letters for the recorded amounts (C3); the quote's vendor cost follows `tariff:read`, the manual shipping cost stays Admin only (C4); Issue invoice from the shipment page is the manual path (C5); a shipment in no master links to the Workspace (C6); **Quote & invoice** is a secondary header button (C7). Full text: §000000 | `UAT-BLD-32`, `-33` |
| **#7** — the account's standard update sentences | The standard sentence in the customer's language, staff's published text beneath | `UAT-VIA-02` |
| **#10** — sending while a newer draft is open | Refused: finalise the draft first | `UAT-WSQ-04` |
| **#12** — reminder emails to approvers or customers | None; approvers see a count on Settings | `UAT-TAR-02` |
| **P-8** — Python 3.15 on tester PCs | 64-bit Python 3.11 to 3.14 supported (3.12.10 recommended, 3.14 tested); 3.15 refused with a clear message (`HOW_TO_RUN.md` §1) | None (environment) |
| RC-UAT-20 stand-in R-1 — a domestic shipment whose destination province is unknown | No rate is filled in ("Choose a rate"); **Save draft** needs a rate and the tick; Send and Download are refused until then | `UAT-OWN-28` (`UAT-AIR-DOM-UNK`) |
| RC-UAT-20 stand-in R-2 — where the province comes from | The delivery (recipient) address: the **postal code first** (its first letter: B = NS, E = NB, …), then the province text (a code in capitals, or a full English or French name: "NS", "Nova Scotia", "Nouvelle-Écosse"). If the two disagree, or the text names two provinces, the province is **unknown** (R-1). The origin province never counts | `UAT-OWN-28` (the seeded NS and NB shipments carry a matching postal code and province; `UAT-AIR-DOM-UNK` has neither); disagreements and names are covered by the automated suite |
| RC-UAT-20 stand-in R-4 — the form of a rate | Whole percents, 0 to 30, labelled GST or HST | `UAT-OWN-29` |
| RC-UAT-20 stand-in R-5 — when a rate change applies | To drafts created afterwards; an existing draft keeps its rate | `UAT-OWN-29` |
| RC-UAT-20 stand-in R-7 — costume jewellery markup | None: the customer pays exactly the CAD price entered | `UAT-OWN-26`, `-32` |
| RC-UAT-20 stand-in R-9 — a payment date sent with a time zone offset | The offset is ignored: the calendar date as written is kept; "not in the future" is judged by the date in Toronto (or the staff member's zone when it is ahead) | `UAT-OWN-31` (the screen sends a plain date); automated suite |
| Developer stand-in — a draft created before 2026-10-22 | Read as **Added on top** at its saved rate, unconfirmed (no such draft exists on a fresh reset) | Not exercised by a case |
| Developer stand-in — row 27 on a tariff imported before the fix | Keeps its old per-kg reading until re-imported; the UAT reset re-imports the workbook, so a fresh reset has the new reading | `UAT-OWN-25` |
| **OD-02 / OD-03** — final permissions for Operations and Marketing | Operations holds the tariff permission and sees vendor cost in the Workspace, Payables and Profitability; Marketing sees no cost | `UAT-WSQ-07`, `UAT-FIN-08` |
| **OD-34** — production email provider | Test capture only | Every case that reads an email |

---

## The seeded air dataset

Built by `scripts/uat_env.py --reset` (`scripts/uat_seed_phase13.py`), on top of P1–P5 and
the rest of the base seed, which it does not touch. `uat_env.py --check` lists each item as a
coverage category. Identifiers in brackets are what a fresh reset produces; search by name,
email or booking reference if they differ.

### People

| Ref | Name | Email | Language | Customer Account |
|---|---|---|---|---|
| **A1** | Phạm Thị Thu Trang | `trang.air@example.com` | Vietnamese | **Yes**, linked (`CA-000001`) |
| **A2** | Emily Carter | `emily.air@example.com` | English | **Yes**, linked (`CA-000002`); has turned **In transit** emails off |
| **A3** | Võ Minh Khoa | `khoa.air@example.com` | Vietnamese | No |
| **A4** | Đỗ Ngọc Lan | `lan.air@example.com` | Vietnamese | No |

The Customer Account password for A1 and A2 is in `ENVIRONMENT.md` §2, beside the staff
password. A1's and A2's shipments are not demo records, because the Customer Account shows
no demo shipment.

### Air masters (Workspace)

| Vendor reference | State | Customers (booking reference) | What is already done |
|---|---|---|---|
| **`UAT-AWB-OPEN`** | Open | A3 (`UAT-AIR-A3-1`), A4 (`UAT-AIR-A4-1`) | Items on both; a watch surcharge on A3's; draft quotes priced, rate **not** confirmed |
| **`UAT-AWB-BOOKED`** | Booked | A1 (`UAT-AIR-A1-2`), A4 (`UAT-AIR-A4-2`) | A1's quote v1 finalised and **sent, waiting for the customer**; A4's v1 finalised, **not sent** |
| **`UAT-AWB-TRANSIT`** | Booked | A1 (`UAT-AIR-A1-1`), A2 (`UAT-AIR-A2-1`) | Received at warehouse, departed and in transit published (the departure with staff's own wording, "Chuyến bay UAT-101 …"); both customers **accepted** in their account, which prepared a **draft invoice** for each (OD-89); A1's draft was filled in at **GST/HST 0 %** (Vietnam → Canada is international, zero-rated by route, OD-102), its GST/HST confirmed, and **sent** (that is `INV-000002`, unpaid; the seed sends it without an email); A2 **accepted, not invoiced**: its draft waits for **Review draft invoice**, at the rate its route filled in (**0 %, zero-rated, not confirmed**) |
| **`UAT-AWB-DELIVERED`** | Completed | A3 (`UAT-AIR-A3-2`), A4 (`UAT-AIR-A4-3`) | Dated in the **current month** whatever the day of the reset; every milestone to delivered; A3 invoiced at 0 % and **part-paid CAD 50.00**; A4 invoiced at **5 %**, **paid in VND** at the selling rate, then **CAD 10.00 refunded**; vendor bill `UAT-BILL-DELIVERED` in VND **above the estimate**, approved with a variance reason, marked paid |
| **`UAT-DOM-AWB`** (UAT only) | Booked | A2 (`UAT-AIR-DOM-NS`, `UAT-AIR-DOM-NB`, `UAT-AIR-DOM-UNK`) | Three **domestic** Canada → Canada shipments from Toronto: to Halifax, NS, B3H 1A1; to Moncton, NB, E1C 4M3; and to Halifax with **no province and no postal code**. Each quoted, sent, **accepted** by A2 in the account, and left as an **unsent draft invoice**: NS at **14 %** HST and NB at **15 %** HST, included in the price; UNK with **no rate** (staff must choose). Their prices mean nothing, only the tax does |
| **`UAT-AWB-CLOSED`** | Completed | A3 (`UAT-AIR-A3-3`) | Everything dated in the **last month past M+7** (on 2026-10-21 that is September 2026): invoiced, paid in full, billed at the estimate (`UAT-BILL-CLOSED`), and the month **closed** |

Invoices on a fresh reset: `INV-000001` (A3, closed month, paid), `INV-000002` (A1, GST/HST
0 %, zero-rated by route — OD-102; it was 13 % included in RC-UAT-19 — CAD 108.00, unpaid),
`INV-000003` (A3, part-paid), `INV-000004` (A4, 5 % added on top, VND payment and a refund).
`uat_env.py --check` therefore lists **2** invoice tax choices (0 and 5 %), not 3.
Receipts: `RCT-000001` (closed month), `RCT-000002` (A3's CAD 50.00), `RCT-000003` (A4's VND
payment). Draft invoices: **four** live drafts, all A2's — `UAT-AIR-A2-1` (0 %) and the three
`UAT-AIR-DOM-*` (no `INV-` number until each is sent); A1's `UAT-AIR-A1-1` draft is already
sent. Quotes accepted in the Customer Account: **5** (A1's `UAT-AIR-A1-1`, A2's `UAT-AIR-A2-1`
and the three domestic ones; 2 before RC-UAT-20), of which **4** are accepted, not invoiced.

Since RC-UAT-18 (OD-88) the items and fee lines of every shipment on a **booked** or
**completed** master are locked: `UAT-AWB-BOOKED`, `-TRANSIT`, `-DELIVERED` and `-CLOSED`
show **Items and fees locked**. A case that adds an item or a fee on one of them says to
have an Admin **Unlock for edits** first. Re-pricing, confirming the rate and finalising are
not locked.

Since RC-UAT-19: no shipment of the air dataset has a transport leg or a carrier link
(`UAT-OWN-23` and `-24` add them), and none carries the costume jewellery surcharge (HCM air row
27; `UAT-OWN-25` to `-27` add it). The reset re-imports the workbook, so row 27 reads as a
manual amount on a fresh reset.

Since RC-UAT-20: **domestic shipments cannot be quoted on screen.** A quote needs an air
master, and a master takes only confirmed Vietnam → Canada shipments ("Confirmed Vietnam →
Canada shipments only."). So the seed, **for UAT only**, places three domestic shipments on
their own master, `UAT-DOM-AWB`, to give the GST/HST-by-province cases real drafts
(`UAT-OWN-28`); do not try to add a domestic shipment to a master yourself. Every other seeded
shipment is Vietnam → Canada, zero-rated (0 %). `uat_env.py --check` lists the three domestic
drafts as categories (14 % NS, 15 % NB, one awaiting a rate). The GST/HST rate table (**Settings → GST/HST rates**) is seeded by the migration with the owner's
rates, "As set up (owner, 2026-10-23)".

Since RC-UAT-21: **nothing new is seeded.** No shipment has been imported, no legacy baseline
exists, no account is deactivated and no quote version is deleted or superseded on a fresh
reset; the `UAT-BLD` cases create what they need, step by step. The import templates are in
`artifacts\sample-imports\` (also on each import page). Retention deletion is **off**, every
record class disabled with no period.

If a reset fails part-way, run `--reset` again: a half-built database is not repaired by a
second run.

### Settings and tariffs

| Item | Seeded value |
|---|---|
| Settings → Pricing | Air Standard **CAD 18.00/kg**; Air Express **empty**; share 2 / 3; default surcharge markup **2 %**, saved by the demo Admin |
| Exchange rates | Two demo Vietcombank readings, labelled demo (source `demo://fixture`): one in the closed month, one at reset time. A reading counts as live for a day: `uat_env.py --refresh-fx` adds a new one |
| Active tariff | The sanitized Kango workbook of 2026-10-12. Its import report: **39** warnings and **3** owner-confirmed price steps (OD-81), no "price falls with weight" warning. Since RC-UAT-20 both are shown on **Settings → Tariffs → Tariff versions → View** (the active version), in the card **Import warnings (39) · TRF-…** (`UAT-OWN-34`) |
| GST/HST rates | ON 13 % HST; NS 14 % HST; NB, NL, PE 15 % HST; AB, BC, MB, QC, SK, NT, NU, YT 5 % GST (OD-102). Operations and the read-only manager see them; only Admin saves |
| Approvers | `admin@demo.example.com` only (in production the default is Ben, OD-76) |
| Senders imported without review | `vendor-rates.example.com` |
| Intake mailbox shown | `tariffs@demo.example.com` (a test address; the production default is never stored in UAT) |
| Rate emails | From `rates@vendor-rates.example.com`: imported as a **draft** with **three prices changed**, awaiting the approver. From `rates@unknown-forwarder.example.com`: **Held: unknown sender** (one price changed). Copies of both `.eml` files are in `data/uat/tariff_intake/samples/` |

### Emails already captured (`data/uat/account_mail`)

Two verification and two approval messages (A1, A2); six quote-sent messages (A2's three
domestic quotes in English since RC-UAT-20, and A1 twice in
Vietnamese, A2 once in English); milestone emails for TRANSIT and DELIVERED in each
customer's language. A2's "in transit" was **not** sent: it is in the outbox as skipped,
"customer turned it off". The base seed's own published milestones (P1 and two demo
customers) are in the capture too. **No invoice email** is captured at reset: the seed sends
A1's draft without one. From RC-UAT-18 on, **Send invoice** on a draft writes an
`invoice.sent.vi` or `invoice.sent.en` file (invoice number, total and due date only).

---

# Workspace pricing and quotes — `UAT-WSQ-*`

### UAT-WSQ-01 — Read the vendor cost and add a surcharge to an open master

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset; signed in as `ops@demo.example.com` |
| **Data** | `UAT-AWB-OPEN`; A4's shipment `UAT-AIR-A4-1` |
| **Steps** | 1. Open **Workspace** and the master `UAT-AWB-OPEN`. 2. Read the **Vendor cost** panel: base freight, piece fee, surcharges, total in VND, the Vietcombank rates used, and the cost by customer. 3. On A4's card, under the coffee item, **Add fee**: search `nuoc hoa` without accents, then pick any surcharge the form offers and give it what it asks for. 4. Re-read the Vendor cost panel and A4's **Quote** panel. |
| **Expected** | Step 2: the rates are labelled as a demo reading; the cost is split by customer. Step 3: the search finds `nước hoa` without its accents; the form asks only for what that fee needs. Step 4: the new surcharge appears in the vendor cost; A4's quote says it is out of date until re-priced. A **manual quote** fee shows the file's minimum, flagged — except costume jewellery (HCM row 27), which asks for the vendor's amount for the line instead (OD-93, `UAT-OWN-25`) |
| **Privacy / permission** | Vendor cost is internal: Operations and Admin see it (tariff permission); no customer document carries it |
| **Evidence to capture** | Screenshots of the Vendor cost panel before and after, and of the Add fee form |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-WSQ-02 — Confirm the rate, finalise, and print the customer quote

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | `UAT-WSQ-01` done or not; a fresh reset is fine |
| **Data** | A3's shipment `UAT-AIR-A3-1` on `UAT-AWB-OPEN` |
| **Steps** | 1. In A3's **Quote** panel press **Re-price**. 2. **Confirm selling rate** with the box empty. 3. Type `19.50` and confirm again without a reason, then with the reason `UAT override test`. 4. Type the box empty again and confirm, to return to CAD 18.00. 5. **Finalise quote**. 6. **Print customer quote v1**. |
| **Expected** | Step 2: CAD 18.00/kg is confirmed with no reason asked. Step 3: without a reason it is refused with "A rate other than the default needs a reason"; with one it is accepted. Step 5: finalised; if a surcharge bills below its cost, finalising asks for a reason. Step 6: the printed quote shows Solaris Express's details, the customer's charges (the watch surcharge under its rule name; a rule name that names a vendor would read **Phụ phí** / **Surcharge**, OD-84) and the **Total** in CAD with "Zero-rated (0 %)" beneath (Vietnam → Canada is international; since RC-UAT-21 the printed quote follows the invoice rule, OD-109 stand-in, `UAT-BLD-14`; it no longer reads "Total before tax"); **no cost, exchange rate, markup, margin or vendor name** |
| **Privacy / permission** | The override and its reason are audited; the printed quote is customer-safe |
| **Evidence to capture** | Screenshot of the refusal at step 3; the printed quote (PDF or screenshot) |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-WSQ-03 — Send a finalised quote to a customer without an account

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | A4's shipment `UAT-AIR-A4-2` on `UAT-AWB-BOOKED` (finalised v1, not sent) |
| **Steps** | 1. Open `UAT-AWB-BOOKED`, A4's **Quote** panel. 2. **Send to customer**. 3. List the newest files in `data/uat/account_mail` and open the `quote.sent.vi-lan.air…` file. |
| **Expected** | The panel shows **Sent — waiting for the customer**. One Vietnamese email for `lan.air@example.com` is captured, with a link to the Customer Account and **no amount** in it. A4 has no account, so nobody can answer it yet; that is expected |
| **Privacy / permission** | The email carries no figure (OD-77); nothing leaves the machine |
| **Evidence to capture** | Screenshot of the panel; the captured file's subject and body |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-WSQ-04 — A newer version withdraws an unanswered quote; no sending with a draft open

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | `UAT-WSQ-03` done (A4's v1 sent). `UAT-AWB-BOOKED` is booked, so its items are locked (OD-88): as Admin, **Unlock for edits** on it with the reason `Add an item (UAT)` first (`UAT-OWN-02`) |
| **Data** | `UAT-AIR-A4-2` |
| **Steps** | 1. On A4's card add an item (`Áo dài (UAT)`, 1 piece, 0.6 kg). 2. **Re-price**, so v2 opens as a draft. 3. Try **Send to customer**. 4. Confirm the rate and **Finalise quote** (v2). 5. Read the status of v1, and the master's lock badge. 6. **Send to customer** for v2. 7. **Withdraw** v2 without a reason, then with `Wrong weight (UAT)`. 8. Read the **Issue invoice** area of the panel (do not press it). |
| **Expected** | Step 1: accepted while the master is unlocked (without the unlock, **Add item** is disabled with "Locked: this master is booked, so items and fees cannot change."). Step 3: refused — finalise the draft first (question #10). Step 5: v1 shows **Withdrawn**, automatically; the master shows **Items and fees locked** again by itself (finalising relocks it, F-6). Step 6: v2 is sent; a new captured email. Step 7: a reason is required; after it, **Withdrawn**. The customer would only ever read that the quote is no longer valid, never the reason. Step 8: a warning that quote v2 was sent and is now **Withdrawn**; issuing is still allowed (stand-in) and the audit log would note it. A4 has no account, so no draft invoice exists and **Issue invoice** is the control shown |
| **Privacy / permission** | Staff reasons are internal |
| **Evidence to capture** | Screenshots of the refusal (step 3), v1 withdrawn (step 5), v2 withdrawn (step 7) |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-WSQ-05 — Book a master and publish a master milestone

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | `UAT-WSQ-02` done (A3's quote finalised). Finalise A4's quote on `UAT-AWB-OPEN` the same way |
| **Data** | `UAT-AWB-OPEN` |
| **Steps** | 1. **Edit master**: actual weight 12 kg, vendor reference already set. 2. **Book with vendor**. 3. **Milestones and closing → Record a milestone**: *Received at warehouse*, the standard update, published. 4. Read the result list. 5. Record the same milestone again. 6. Open **Settings → Customer notifications**. |
| **Expected** | Step 2: the master is **Booked**; its members, weights, service and origin are frozen (only the vendor reference can still be corrected) and the chargeable weight is shown. Since RC-UAT-18 the items and fee lines of its shipments are **locked** too (OD-88): the header shows **Items and fees locked**, and **Add item**, **Edit item**, **Add fee** and **Remove** are disabled with "Locked: this master is booked, so items and fees cannot change." (an Admin can unlock, `UAT-OWN-02`). Re-pricing and finalising are still allowed. Step 4: each of the two shipments is **Updated**. Step 5: each is **Already had it**. Step 6: one "received" email per shipment, in Vietnamese (A3, A4), **Sent** (if one shows queued, run the notification worker `--once`, `HOW_TO_RUN.md` §5) |
| **Privacy / permission** | A milestone reaches each customer once, whatever the repeat |
| **Evidence to capture** | Screenshots of the booked master and the milestone result list; the two captured emails' file names |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-WSQ-06 — Cancel a master

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed Vietnam → Canada shipment that is on no master. If **Add a customer's shipment** finds none, book one first as in `UAT-OP-01` (route Vietnam → Canada) |
| **Data** | That shipment |
| **Steps** | 1. **Workspace → New master**: Air Standard, HCM. 2. Add the shipment. 3. **Cancel master** without a reason, then with `UAT cancel test`. 4. Open the shipment. 5. Try to add the shipment to `UAT-AWB-OPEN` (if still open) or to a new master. |
| **Expected** | Step 3: a reason is required; then the master is **Cancelled** and the confirmation lists any quote already sent or accepted (none here). Step 4: the shipment is released and stays confirmed. Step 5: it can be added again |
| **Privacy / permission** | Cancelling a master never cancels a customer's booking |
| **Evidence to capture** | Screenshots of the cancelled master and the released shipment |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-WSQ-07 — Who may open the Workspace

| | |
|---|---|
| **Role** | Marketing, then Read-only manager, then Admin |
| **Prerequisites** | Three browsers or private windows |
| **Data** | `marketing@demo.example.com`, `manager@demo.example.com`, `admin@demo.example.com` |
| **Steps** | 1. As Marketing, look for **Workspace** in the navigation, then type `/workspace` in the address bar. 2. The same as the read-only manager. 3. As Admin, open `UAT-AWB-BOOKED`. |
| **Expected** | Steps 1–2: no navigation entry, and the address is refused; no vendor cost, exchange rate or markup is visible anywhere to these roles (OD-02 / OD-03 stand-in). Step 3: Admin sees everything Operations sees |
| **Privacy / permission** | The tariff permission gates every cost figure |
| **Evidence to capture** | Screenshots of the refusals |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Quote acceptance in the Customer Account — `UAT-QAC-*`

### UAT-QAC-01 — A1 reads and accepts a quote, in Vietnamese

| | |
|---|---|
| **Role** | Customer (A1), signed in at `/account/sign-in` |
| **Prerequisites** | Fresh reset |
| **Data** | `trang.air@example.com`; the quote for `UAT-AIR-A1-2` |
| **Steps** | 1. Sign in. Open **Lô hàng của tôi** (My shipments) and note the Solaris ID (`SX-VCA-…`) of the shipment whose booking reference is `UAT-AIR-A1-2`. 2. Open **Báo giá** (Quotes): the list shows each quote's Solaris shipment ID, not the booking reference. 3. Open the waiting quote with that ID. 4. Read every figure. 5. Accept it; answer the confirmation. 6. Try to accept or decline it again. |
| **Expected** | Step 2: one waiting quote, and the one A1 accepted earlier for `UAT-AIR-A1-1`. Step 4: rate per kg, base charge, the surcharge A1 pays (the watch; a surcharge whose name names a vendor would read **Phụ phí**, OD-84), and the total, **Tổng cộng**, in CAD, with "Thuế suất 0 (0 %)" beneath (international, zero-rated; OD-109 stand-in since RC-UAT-21, `UAT-BLD-14`); no expiry date (a quote expires only on a new tariff before the goods are received, OD-89, `UAT-OWN-05`). **No** invoice, payment, balance, cost, exchange rate, markup or vendor name. Step 5: the quote shows **accepted**; staff now find a draft invoice prepared for it (`UAT-OWN-08`), which A1 does not see. Step 6: no accept or decline control remains; the quote reads as answered. Answering twice is refused by the server too |
| **Privacy / permission** | OD-77 narrows OD-32: a sent quote is the only money a customer sees |
| **Evidence to capture** | Screenshots of the quote and of the answered state |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-QAC-02 — An accepted quote's invoice waits as a draft; staff send it

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | `UAT-QAC-01` done; `UAT-OWN-12` not run (A2's seeded draft still unsent) |
| **Data** | `UAT-AWB-BOOKED` (A1); `UAT-AWB-TRANSIT` (A2, accepted, not invoiced) |
| **Steps** | 1. Open `UAT-AWB-BOOKED`, A1's Quote panel and the invoice area beneath it. 2. Open **Finance → Invoices**, **Accepted, not invoiced**. 3. On A1's row press **Review draft invoice**; read the page; leave **GST/HST** at **0 %**, as the route filled it in; look at **Send invoice** and **Download PDF (draft)**; tick **I have checked the GST/HST on this invoice**, **Save draft**, then **Send invoice**. 4. Re-read the list. 5. List the newest files in `data/uat/account_mail` and open the `invoice.sent.vi-trang.air…` file. |
| **Expected** | Step 1: **Accepted** and "Customer accepted v1 — issue the invoice"; in place of **Issue invoice**: "The customer accepted this quote; its invoice is ready as a draft." and **Review draft invoice** (OD-89; manual **Issue invoice** is refused while a draft exists). Step 2: A1's `UAT-AIR-A1-2`, A2's `UAT-AIR-A2-1` and A2's three `UAT-AIR-DOM-*` are listed, each with **Review draft invoice**; no `INV-` number was issued by itself. Step 3: the draft says "No invoice number yet: it is assigned when you send the invoice."; "Route VN → CA: international, zero-rated (0 %)."; GST/HST offers 0, 5, 13, 14 and 15 % and **Included in the price** / **Added on top**, starting at **0 %** with "GST/HST 0 % (zero-rated): no tax, total …" (OD-102); revenue lines only; before the tick, **Send invoice** and **Download PDF (draft)** are disabled with "The GST/HST of the saved draft is not confirmed: tick the check and save before sending or downloading." After Send: "Invoice INV-… issued." and the status **Sent**. Step 4: A1's row is gone; A2's four stay. Step 5: a Vietnamese email naming the invoice number, the total and the due date; **no line, no amount per line, no vendor name** |
| **Privacy / permission** | Acceptance prepares a draft and nothing else; only staff issue the numbered invoice |
| **Evidence to capture** | Screenshots of the prompt, the list before and after, the draft, and the new invoice; the captured file's name and body |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-QAC-03 — A newer price after acceptance, and an English decline

| | |
|---|---|
| **Role** | Operations, then Customer (A2) |
| **Prerequisites** | Fresh reset, or `UAT-QAC-02` done without touching A2. `UAT-AWB-TRANSIT` is booked, so its items are locked (OD-88): as Admin, **Unlock for edits** on it with the reason `Add an item (UAT)` first |
| **Data** | `UAT-AIR-A2-1` on `UAT-AWB-TRANSIT`; `emily.air@example.com` |
| **Steps** | 1. As Operations add an item to A2's shipment (`Tea (UAT)`, 2 boxes, 1 kg), **Re-price**, confirm the rate and **Finalise quote** (v2). 2. Read A2's Quote panel and the invoice area beneath it. 3. **Send to customer**. 4. As A2, sign in, open **Quotes** and the new quote, and **Decline** it with the reason `Too expensive (UAT)`. 5. As Operations, re-read the panel. |
| **Expected** | Step 1: finalising v2 locks the master again by itself (**Items and fees locked**). Step 2: the panel says the customer accepted an earlier price and to agree the price with them first; the draft invoice prepared from the accepted v1 stays, at the accepted price (stand-in), still reached by **Review draft invoice**. Step 3: sent; an English email is captured for `emily.air`. Step 4: the screens are in English (A2's saved language); the decline is confirmed. Step 5: **Declined**, with A2's reason |
| **Privacy / permission** | The customer's reason reaches staff; staff reasons never reach the customer |
| **Evidence to capture** | Screenshots of steps 2, 4 and 5 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-QAC-04 — One customer cannot reach another's quote

| | |
|---|---|
| **Role** | Customer (A2) |
| **Prerequisites** | The address of one of A1's quotes, read from A1's own session (`/account/quotes/<id>`) |
| **Data** | A1's quote id |
| **Steps** | 1. As A2, open `/account/quotes/<A1's id>`. 2. Try the accept and decline buttons if anything renders. 3. Read A2's **Lô hàng của tôi** / My shipments. |
| **Expected** | Step 1: not found, worded exactly as for an id that does not exist. Step 3: only A2's own shipments (`UAT-AIR-A2-1` and the three `UAT-AIR-DOM-*`) |
| **Privacy / permission** | T-03: ownership is checked on every account route |
| **Evidence to capture** | Screenshot of the not-found page |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Finance — `UAT-FIN-*`

### UAT-FIN-01 — Issue an invoice and choose GST/HST

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | A4's `UAT-AIR-A4-2` on `UAT-AWB-BOOKED` (finalised) |
| **Steps** | 1. **Issue invoice**, read the GST/HST choices and pick **0 %**. 2. Open the invoice. 3. Try **Issue invoice** again for the same shipment. 4. **Print** the invoice. 5. Open `INV-000002` (A1, 0 %, sent from a draft) and `INV-000004` (A4, 5 % added) and compare the tax lines. |
| **Expected** | Step 1: choices 0, 5 and 13 %; the hint reads "Added on top at the rate you choose. (Drafts from accepted quotes fill the rate in from the route.)" (manual **Issue invoice** is unchanged: tax added on top, no confirmation; OD-106). A4 has no account and never accepted, so there is no draft and **Issue invoice** is shown (with a draft, it would be **Review draft invoice** instead, OD-89). Step 2: revenue lines only, billed to the customer, due date from **Invoice terms**. Step 3: refused — one live invoice per shipment. Step 4: no cost, exchange rate, markup or vendor name (a line naming a vendor prints as **Surcharge** on the English invoice, OD-84, DEC-0235). Step 5: `INV-000004`: 5 % of the subtotal added on top, rounded to the cent. `INV-000002`: sent from a draft at **0 %** (Vietnam → Canada is zero-rated, OD-102): each line's Tax reads **Zero-rated** and the summary row "GST @ 0%" at CAD 0.00, subtotal = total = the lines, and no "Prices include …" sentence (`UAT-OWN-22`, DEC-0235). The new invoice of step 1, at 0 %, prints the same zero-rated row |
| **Privacy / permission** | The invoice is customer-facing |
| **Evidence to capture** | The printed invoice; screenshots of step 3 and step 5 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-FIN-02 — Record a CAD payment, and never more than the balance

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | `INV-000003` (A3, CAD 90.00, CAD 50.00 paid) |
| **Steps** | 1. Open the invoice and read the balance. 2. **Record payment**: CAD 41.00, e-transfer. 3. Record CAD 40.00. 4. **Print receipt**. |
| **Expected** | Step 1: balance CAD 40.00. Step 2: refused — a payment cannot exceed the balance; nothing is kept as credit (OD-68). Step 3: recorded; the invoice is **Paid**; a new `RCT-` receipt. Step 4: the receipt shows the amount and method, nothing internal |
| **Privacy / permission** | Payments are audited |
| **Evidence to capture** | Screenshots of the refusal and the paid invoice; the receipt |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-FIN-03 — A payment in VND at the selling rate

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | `UAT-FIN-01` done (A4's new invoice); an exchange rate recorded today (`uat_env.py --refresh-fx` if the reset was yesterday or earlier) |
| **Data** | A4's new invoice; `INV-000004` |
| **Steps** | 1. Open `INV-000004`, then **Print receipt** `RCT-000003` to read the VND amount, the selling rate and the CAD it became. 2. On the new invoice, **Record payment** in VND, about half the total at that rate. 3. Read the conversion. 4. Record a second VND payment for the rest. |
| **Expected** | Step 1: the rate is Vietcombank's **selling** rate (third column) on the invoice date, labelled as a demo reading. Step 3: CAD = VND ÷ rate, to the cent; the first VND payment fixes the rate for this invoice. Step 4: the same rate is used; a VND amount that covers the balance converts to the balance exactly |
| **Privacy / permission** | OD-66: the sell rate for customer payments |
| **Evidence to capture** | Screenshots of each conversion |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-FIN-04 — Refunds and voids

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | `INV-000004` (refund already recorded), `INV-000003` (money held), `INV-000002` (no money) |
| **Steps** | 1. Open `INV-000004` and read the refund of CAD 10.00 and its reason. 2. Try to refund more than the rest of that payment. 3. On `INV-000003`, **Void invoice**. 4. On `INV-000002`, **Void invoice** without a reason, then with `Wrong tax (UAT)`. 5. Issue a new invoice for `UAT-AIR-A1-1` at 0 %. |
| **Expected** | Step 2: refused, naming the most that can be refunded. Step 3: refused — refund the payments first. Step 4: a reason is required; then **Void**; its number is never reused. After step 4, A1's `UAT-AIR-A1-1` is back under **Accepted, not invoiced** (an accepted quote with no live invoice), with no **Review draft invoice** button: its draft was already sent, and voiding does not prepare a new one. Step 5: manual **Issue invoice** is allowed (no live draft); a new `INV-` number, and the row goes again |
| **Privacy / permission** | Admin and Operations may both refund and void (OD-69); both are audited |
| **Evidence to capture** | Screenshots of each refusal and of the void and the reissue |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-FIN-05 — Vendor bills: variance, reason and the cost split

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Fresh reset; an exchange rate recorded today (`uat_env.py --refresh-fx` if the reset was on an earlier day: a VND bill is converted at the bill date's rate) |
| **Data** | `UAT-AWB-DELIVERED` (bill `UAT-BILL-DELIVERED`); `UAT-AWB-BOOKED` (no bill) |
| **Steps** | 1. On `UAT-AWB-DELIVERED`, open the vendor bill: currency, the buy rate frozen on it, total in CAD, expected cost, variance and reason, and the split by shipment. 2. On `UAT-AWB-BOOKED`, **Enter bill (start from the estimate)** in VND, raise one line by 200,000 VND, and save. 3. **Approve and split the cost** without a reason, then with `Vendor surcharge (UAT)`. 4. **Mark paid**. 5. Try **Enter bill** again on the same master. |
| **Expected** | Step 1: VND converted at the **buy** rate (first column) on the bill date (OD-73); the variance is positive and its reason shown; the cost split across A3 and A4. Step 3: refused without a reason; with it, approved and split across A1 and A4. Step 4: **Paid**. Step 5: refused — void the bill to enter another |
| **Privacy / permission** | Vendor bills are Payables, visible only with the tariff permission |
| **Evidence to capture** | Screenshots of step 1, the refusal at step 3, and the split |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-FIN-06 — Receivables, Payables and Profitability agree with the records

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | The four seeded invoices and two bills |
| **Steps** | 1. **Finance → Receivables**: find A1's CAD 108.00 (`INV-000002`, GST/HST 0 % since RC-UAT-20; the same total at 13 % included in RC-UAT-19; it read CAD 122.04 when the tax was added on top), A3's CAD 40.00 and A4's CAD 10.00 open. 2. **Payables**: both bills, paid. 3. **Profitability** for the closed month and for the current month. |
| **Expected** | Step 1: each open balance appears once, in CAD, in its age bucket. Step 2: **no open payables** (both bills are paid); read each master's **Vendor bill** panel for the totals. Step 3: the closed month shows the frozen figures (revenue CAD 90.00 and cost CAD 84.70 on a fresh reset); the current month shows the DELIVERED and TRANSIT figures (the seed dates DELIVERED in the current month, so this holds whatever the day of the reset); Profitability is called a management figure by hand-in month, not an accounting statement |
| **Privacy / permission** | Payables and Profitability show cost: tariff permission only |
| **Evidence to capture** | Screenshots of the three tabs |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-FIN-07 — M+7: a closed month, a refused back-dated entry, reopen and close

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Fresh reset; `UAT-FIN-02` not run (`INV-000003` still part-paid) |
| **Data** | The closed month (Finance → Month close); `INV-000003` |
| **Steps** | 1. **Finance → Month close**: read the closed month and the open ones. 2. On `INV-000003` record CAD 5.00 with a received date inside the closed month. 3. As Operations, **Reopen month** without a reason, then with `Late receipt (UAT)`. 4. Record the same payment again. 5. As Admin, **Close month** again. 6. Read Profitability for that month. |
| **Expected** | Step 1: the month is **Closed**; a month locks seven days after it ends. Step 2: refused — closed (M+7), reopen it, do not re-date the payment. Step 3: a reason is required; then **Reopened** (Operations may reopen, OD-69). Step 4: accepted. Step 5: **Closed**, version 2. Step 6: the new frozen figures |
| **Privacy / permission** | Close and reopen are audited with the reason |
| **Evidence to capture** | Screenshots of each state and the refusal |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-FIN-08 — Finance permissions

| | |
|---|---|
| **Role** | Marketing, Read-only manager, Operations, Admin |
| **Prerequisites** | Four sessions |
| **Data** | — |
| **Steps** | 1. As each role, open **Finance** and list the tabs. 2. As Operations, open **Invoice terms** (Month close tab) and try to save 21 days. 3. As Admin, save 21 days, then put it back. |
| **Expected** | Step 1: Payables and Profitability only for Operations and Admin; Marketing and the read-only manager see no cost anywhere. Step 2: Operations cannot save. Step 3: Admin can; new invoices take the new due date |
| **Privacy / permission** | OD-02 / OD-03 stand-in |
| **Evidence to capture** | Screenshots of each role's Finance tabs |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Pricing settings and markup — `UAT-PRC-*`

### UAT-PRC-01 — Read the pricing settings; only Admin saves

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Fresh reset |
| **Data** | Settings → Pricing |
| **Steps** | 1. As Operations, open **Settings → Pricing** and read every value. 2. Look for a save button. 3. As Admin, open the same page. |
| **Expected** | Step 1: Air Standard CAD 18.00, Air Express empty, share 2 / 3, **Default surcharge markup** 2 %, and the surcharge policies list. Step 2: Operations cannot save. Step 3: Admin can |
| **Privacy / permission** | Saving pricing settings is Admin only |
| **Evidence to capture** | Screenshots from both roles |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-PRC-02 — Changing the default markup reaches drafts, not finalised quotes

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset |
| **Data** | A3's draft on `UAT-AWB-OPEN` (watch surcharge); A1's finalised quote on `UAT-AWB-BOOKED` |
| **Steps** | 1. Note the watch surcharge on A3's quote after **Re-price**. 2. As Admin, set the default markup to 5 % and save. 3. **Re-price** A3's quote. 4. Re-read A1's finalised quote on `UAT-AWB-BOOKED`. 5. Set the markup back to 2 %. 6. Find both changes in Settings → Audit access. |
| **Expected** | Step 3: the watch surcharge rises by the difference (2 % → 5 % of its cost). Step 4: A1's finalised figures are unchanged. Step 6: two audit rows naming the Admin |
| **Privacy / permission** | Changes apply to future quotes only |
| **Evidence to capture** | The surcharge line before and after; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-PRC-03 — A per-surcharge policy overrides the default

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset |
| **Data** | The watch surcharge's rule in **Surcharge policies (air)** |
| **Steps** | 1. Set the watch rule to **Pass through (no markup)** and save. 2. **Re-price** A3's quote on `UAT-AWB-OPEN`. 3. Set it to **Fixed amount** CAD 3.00, re-price. 4. Read the **Weight basis override** control and leave it unset. 5. Set the rule back to **Default**. |
| **Expected** | Step 2: the watch surcharge bills at cost. Step 3: cost + CAD 3.00. Step 4: the per-kg rules are on the whole carton unless overridden, as the sheet notes say (OD-83); pharma stays on the item's own kg (OD-70); costume jewellery (HCM row 27) has no kg basis at all: staff enter the amount for the line (OD-93, `UAT-OWN-25`). Step 5: back to 2 % |
| **Privacy / permission** | Policies are audited |
| **Evidence to capture** | The surcharge line after each change |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-PRC-04 — Air Express has no default rate

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed Vietnam → Canada shipment on no master (see `UAT-WSQ-06`) |
| **Data** | A new Air Express master from HCM |
| **Steps** | 1. **New master**: Air Express, HCM; add the shipment; enter the weight. 2. **Price quote**. 3. **Confirm selling rate** with the box empty. 4. Type `24.00` without a reason, then with `Express rate agreed (UAT)`. |
| **Expected** | Step 3: refused — this service has no default rate; enter the rate. Step 4: refused without a reason (every Air Express rate is an override, OD-86); accepted with it |
| **Privacy / permission** | The reason is audited |
| **Evidence to capture** | Screenshots of both refusals |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Tariffs: browser, rate emails and approval — `UAT-TAR-*`

### UAT-TAR-01 — The tariff browser is read-only for Operations

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | Settings → Tariffs |
| **Steps** | 1. Open **Settings → Tariffs**. 2. In **Tariff versions**, press **View** on the active version: read the card **Import warnings (…) · TRF-…**, then the air products and rate brackets, accessorial charges and beyond-area rates beneath it. 3. Find the Air Express zone 2 brackets around 16 kg. 4. Read the exchange-rate history. 5. Look for import, approve or activate controls. |
| **Expected** | Step 1: one **Active** version and one **Draft** (from the rate email). Step 2: **Import warnings (39)**; none of them is a price falling with weight; the three confirmed price steps are listed apart (`UAT-OWN-34`). Step 3: the printed bracket price, as imported, with nothing flagged: the owner confirmed the 16 kg drop (OD-81; `UAT-OWN-13`). Step 4: the demo readings, labelled. Step 5: none for Operations |
| **Privacy / permission** | Operations reads the tariff; only an approver changes it |
| **Evidence to capture** | Screenshots of steps 2 to 4 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-TAR-02 — Approve the draft from the allowed vendor

| | |
|---|---|
| **Role** | Admin (`admin@demo.example.com`, the UAT approver) |
| **Prerequisites** | Fresh reset |
| **Data** | The draft "Kango Canada air rates, three prices updated (UAT)" |
| **Steps** | 1. Read the count on **Settings** and on **Tariff updates**. 2. Open the draft's changes against the active version. 3. **Approve and activate**. 4. Re-open **Settings → Tariffs**. 5. Re-read A1's finalised quote on `UAT-AWB-BOOKED` and the vendor cost of `UAT-AWB-BOOKED`. |
| **Expected** | Step 1: a count of waiting items (one draft, one held email; no reminder email, question #12). Step 2: exactly **three** rate brackets changed, each with its old and new price; nothing added or removed. Step 3: the draft becomes **Active**, the old one **Superseded**. Activating also expires every finalised quote whose goods are not yet received and whose master is not booked (OD-89, `UAT-OWN-05`): on a fresh reset there is none; if `UAT-WSQ-02` finalised A3's quote on the still-open `UAT-AWB-OPEN` first, that quote now shows "Expired: re-quote on the new rate", which is correct. Step 5: unchanged and not expired — a booked master keeps the tariff it was booked under (stand-in) |
| **Privacy / permission** | Only a designated approver with the tariff-manage permission activates (OD-76) |
| **Evidence to capture** | Screenshots of the count, the change list and the result |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-TAR-03 — A held email: release, then reject

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Fresh reset (or after `UAT-TAR-02`) |
| **Data** | The email from `rates@unknown-forwarder.example.com` |
| **Steps** | 1. In **Tariff updates**, read the **Held: unknown sender** row. 2. **Release** it. 3. Open the draft it became and read its changes. 4. **Reject** without a reason, then with `Not from the vendor (UAT)`. 5. Look for an activate control on the rejected draft. |
| **Expected** | Step 1: held, not imported. Step 3: one bracket changed against the version the seed activated (four if `UAT-TAR-02` ran first: this workbook does not carry that draft's three changes). Step 4: a reason is required; then **Rejected by approver**. Step 5: none; a rejected draft can never be activated |
| **Privacy / permission** | Release, approve and reject are approver-only and audited |
| **Evidence to capture** | Screenshots of each state |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-TAR-04 — Upload a rate email, and the same email twice

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | The two files in `data/uat/tariff_intake/samples/`; best run before `UAT-TAR-03` |
| **Data** | `uat-rates-allowed.eml`; any small non-email file |
| **Steps** | 1. **Upload a rate email**: `uat-rates-allowed.eml`. 2. Upload a file that is not an email. 3. Copy `uat-rates-unknown-sender.eml` into `data/uat/tariff_intake/` and run the tariff intake worker `--once` (`HOW_TO_RUN.md` §5). 4. Read the list. |
| **Expected** | Step 1: answered with the first row — the same email is never processed twice. Step 2: refused with a clear reason. Step 3: the file moves to `processed/` (to `failed/` instead if `UAT-TAR-03` has already released and rejected that email); no second row. Step 4: no new draft from either |
| **Privacy / permission** | Only headers and the workbook are read; the email's text is never stored (OD-76) |
| **Evidence to capture** | Screenshots of steps 1, 2 and 4; the folder listing after step 3 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-TAR-05 — The approver list

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Fresh reset |
| **Data** | `ops@demo.example.com`; a second test address such as `approver2@demo.example.com` |
| **Steps** | 1. As Operations, look for **Tariff updates** and for Approve / Reject on the draft. 2. As Admin, open **Approvers** and add `approver2@demo.example.com`; save. 3. Remove it again; try to remove the last approver. |
| **Expected** | Step 1: Operations cannot approve, reject or release. Step 2: saved and audited. Step 3: the last approver cannot be removed ("at least one approver is required") |
| **Privacy / permission** | `ENVIRONMENT.md` §2 says how the owner adds himself in UAT |
| **Evidence to capture** | Screenshots of each step |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Milestone emails and customer choices — `UAT-MLS-*`

### UAT-MLS-01 — The outbox explains every email

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | Settings → Customer notifications |
| **Steps** | 1. Open the outbox. 2. Find A2's "in transit" row on `UAT-AIR-A2-1`. 3. Find A1's rows. 4. Open the matching files in `data/uat/account_mail`. |
| **Expected** | Step 2: not sent, reason "customer turned it off". Step 3: received and in transit, **Sent**, in Vietnamese. Step 4: A1's files are Vietnamese, A2's "received" is English; each names the shipment and the standard sentence |
| **Privacy / permission** | A customer's choice is honoured; a suppressed address is never emailed |
| **Evidence to capture** | Screenshot of the outbox; two captured files |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-MLS-02 — A master milestone notifies each customer in their language

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | `UAT-AWB-TRANSIT` |
| **Steps** | 1. **Record a milestone**: *Out for delivery*, standard update, published. 2. Open the outbox; if a row is queued, run the notification worker `--once`. 3. Open the two new captured files. 4. Record *In transit* again, published (a step behind). |
| **Expected** | Step 2: one "out for delivery" email each for A1 (Vietnamese) and A2 (English). A2 turned off only "in transit", so A2 gets this one. Step 4: no new email — nothing behind the furthest step reached |
| **Privacy / permission** | One email per shipment and milestone |
| **Evidence to capture** | The outbox; the two files |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-MLS-03 — Staff change a customer's milestone choices

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | A4 (`lan.air@example.com`) |
| **Steps** | 1. Open A4's customer record, **Milestone emails**. 2. Turn **Delivered** off; save. 3. As Admin, open **Settings → Audit access** and find the change. 4. As Marketing, open A4's record and look for the same control. |
| **Expected** | Step 2: saved; all others stay on. Step 3: an audit row naming Operations as the actor. Step 4: Marketing cannot change it (tracking permission) |
| **Privacy / permission** | Changes by staff are audited as staff, not as the customer |
| **Evidence to capture** | Screenshots of steps 2 to 4 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-MLS-04 — An unpublished milestone notifies nobody

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | `UAT-AWB-BOOKED` (no milestone yet) |
| **Steps** | 1. **Record a milestone**: *Received at warehouse*, **not** published (untick it). 2. Open the outbox. 3. Record it again, published. 4. Open the outbox. |
| **Expected** | Step 1: each shipment **Updated**. Step 2: nothing queued for A1 or A4. Step 3: each shipment **Updated** again, not "Already had it": a published milestone is a repeat only of a published one. Step 4: one "received" email each, Vietnamese; recording it published a third time adds nothing |
| **Privacy / permission** | A customer is never told about a step the tracking page does not show |
| **Evidence to capture** | The outbox after steps 1 and 3 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# The Customer Account, Vietnamese first — `UAT-VIA-*`

### UAT-VIA-01 — Vietnamese first, English on every screen

| | |
|---|---|
| **Role** | Customer (not signed in, then A1) |
| **Prerequisites** | A browser whose own language is English |
| **Data** | `/account/sign-in`; `trang.air@example.com` |
| **Steps** | 1. Open `/account/sign-in`. 2. Switch to **English** at the top, then back to **Tiếng Việt**. 3. Sign in as A1. 4. Open each screen from the navigation: **Lô hàng của tôi**, **Báo giá**, **Thông báo**, **Hồ sơ của tôi**. 5. Switch to English on one of them. 6. Sign out and in again. |
| **Expected** | Step 1: Vietnamese, whatever the browser's language (OD-71). Steps 2 and 5: the switch is on every screen and changes the whole screen. Step 6: A1's saved language (Vietnamese) applies at sign-in; nothing about the choice is stored in the browser |
| **Privacy / permission** | OD-71. The owner accepted the Vietnamese wording as is (OD-85); record wording findings as S5 |
| **Evidence to capture** | Screenshots of each screen in Vietnamese and one in English |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-VIA-02 — Shipment updates in the customer's language

| | |
|---|---|
| **Role** | Customer (A1) |
| **Prerequisites** | Fresh reset |
| **Data** | `UAT-AIR-A1-1` |
| **Steps** | 1. Open **Lô hàng của tôi** and the shipment with booking reference `UAT-AIR-A1-1`. 2. Read each update. 3. Switch to English and read them again. 4. Open **Thông báo**. |
| **Expected** | Step 2: received, departed and in transit, each as the standard sentence in Vietnamese (question #7). Staff's published wording appears beneath only when it differs from the standard sentence: the departure carries the seeded staff wording "Chuyến bay UAT-101 …", so it shows there; the other two show the standard sentence alone. Step 3: the standard sentences in English. Step 4: the four milestone choices, all on, and what was sent for A1's shipments |
| **Privacy / permission** | No internal detail, cost or other customer's data |
| **Evidence to capture** | Screenshots of steps 2 to 4 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-VIA-03 — An English customer turns a milestone back on

| | |
|---|---|
| **Role** | Customer (A2), then Operations |
| **Prerequisites** | Fresh reset |
| **Data** | `emily.air@example.com` |
| **Steps** | 1. Sign in as A2. 2. Open **Notifications** and read the choices. 3. Turn **In transit** back on. 4. As Operations, open A2's customer record, **Milestone emails**; as Admin, open **Settings → Audit access**. |
| **Expected** | Step 1: English, A2's saved language. Step 2: "In transit" is off, the other three on. Step 3: saved, with the confirmation sentence. Step 4: the choice matches; the audit row's actor reads **system** and its details say the change was made in the account, naming `CA-000002` (on a fresh reset); no member of staff is named |
| **Privacy / permission** | The customer changes only their own choices |
| **Evidence to capture** | Screenshots of steps 2 to 4 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-VIA-04 — The language saved in the profile reaches the emails

| | |
|---|---|
| **Role** | Customer (A1), then Operations |
| **Prerequisites** | Fresh reset |
| **Data** | `trang.air@example.com`; `UAT-AWB-BOOKED` |
| **Steps** | 1. As A1, open **Hồ sơ của tôi** and change the preferred language to English. 2. As Operations, read A1's customer record. 3. Record *In transit*, published, on `UAT-AWB-BOOKED`. 4. Open A1's new captured email (`notify.in_transit.en-trang.air…`). 5. As A1, set the language back to Vietnamese. |
| **Expected** | Step 1: applied at once, no approval queue entry. Step 2: the record shows English. Step 4: the email is in English. Step 5: applied at once |
| **Privacy / permission** | Preferred language is one of the two fields a customer changes directly |
| **Evidence to capture** | Screenshots of steps 1 and 2; the captured file name |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Owner answers of 2026-10-21 (RC-UAT-18) — `UAT-OWN-*`

The owner's answers OD-81 to OD-90 (DEC-0219 to DEC-0222): a booked master locks its items and
fees (`-01` to `-04`), quotes expire on a new tariff before the goods are received (`-05` to
`-07`), acceptance prepares the invoice as a draft (`-08` to `-12`), and the tariff and
vendor-name answers (`-13` to `-17`).

**Order.** `UAT-OWN-05` to `-07` need the seeded tariff draft **unapproved** and
`UAT-AWB-OPEN` **still open**: run them on a fresh reset, before `UAT-TAR-02` and
`UAT-WSQ-05`. `UAT-OWN-05` builds one extra master, `UAT-AWB-OWN`, that `-06`, `-07` and `-15`
reuse. The other cases need only a fresh reset unless they say otherwise.

### UAT-OWN-01 — A booked master locks its items and fees

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset; signed in as `ops@demo.example.com` |
| **Data** | `UAT-AWB-BOOKED` (booked by the seed; A1's `UAT-AIR-A1-2` with `Đồng hồ (UAT)`, A4's `UAT-AIR-A4-2` with `Bánh kẹo (UAT)`) |
| **Steps** | 1. Open **Workspace** and `UAT-AWB-BOOKED`; read the header and the banner beneath it. 2. On A4's card look at **Add item**, **Edit item**, **Add fee** and the fee's **Remove**. 3. Look for **Unlock for edits**. 4. Look at A4's quote controls (do not press them: a new draft would stop `UAT-WSQ-03` sending v1). 5. Open `UAT-AWB-OPEN` and read the same controls. |
| **Expected** | Step 1: badge **Items and fees locked**; banner "Items and fees are locked — This master is booked, so the items and fees of its shipments cannot be added, changed or removed. An Admin can unlock it for edits." Step 2: each control disabled, with "Locked: this master is booked, so items and fees cannot change." Step 3: no such button for Operations. Step 4: **Re-price** is still enabled — re-pricing, confirming the rate and finalising are not locked. Step 5: an open master has no lock; the controls work. The server refuses an item or fee change on a locked master too (409, `master_locked`; covered by the automated suite) |
| **Privacy / permission** | OD-88. Unlocking is Admin only (`master:unlock`) |
| **Evidence to capture** | Screenshots of the header and banner, and of one disabled control with its message |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-02 — Only an Admin unlocks, and only with a reason

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Fresh reset (or after `UAT-OWN-01`) |
| **Data** | `UAT-AWB-BOOKED`; `ops@demo.example.com`, `admin@demo.example.com` |
| **Steps** | 1. As Operations, open `UAT-AWB-BOOKED` and read the lock banner. 2. As Admin, open the same master and press **Unlock for edits**. 3. In the dialog leave **Reason** empty and look at the confirm button. 4. Type `Add a forgotten item (UAT)` and press **Unlock for edits**. 5. Read the banner and the badge. 6. **Settings → Audit access**: find the unlock. |
| **Expected** | Step 1: "An Admin can unlock it for edits."; no unlock button. Step 3: the dialog explains that the master relocks by itself when a member's quote is finalised; the confirm button is disabled while the reason is empty. Step 5: badge **Unlocked for edits**; banner "Unlocked for edits — Reason: Add a forgotten item (UAT) · since …", with **Lock again**. Step 6: one `master.unlocked` row naming the Admin and the reason |
| **Privacy / permission** | The reason is staff-only and audited |
| **Evidence to capture** | Screenshots of steps 1, 3 and 5; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-03 — Edit while unlocked, then lock again

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | `UAT-OWN-02` done (`UAT-AWB-BOOKED` unlocked) |
| **Data** | A4's item `Bánh kẹo (UAT)` on `UAT-AWB-BOOKED` |
| **Steps** | 1. As Operations, **Edit item** on A4's `Bánh kẹo (UAT)`: quantity 5 → 6; **Save item**. 2. Press **Lock again**. 3. Try **Edit item** again. 4. **Settings → Audit access** (as Admin): read the item change and the relock. |
| **Expected** | Step 1: saved; A4's quote says it is out of date until re-priced. Step 2: allowed for Operations; the badge returns to **Items and fees locked**. Step 3: disabled again. Step 4: the item's audit row carries the unlock it was made under; a `master.relocked` row, not automatic, naming Operations (relock timing is follow-up F-6) |
| **Privacy / permission** | Changes made while unlocked are traceable to the unlock |
| **Evidence to capture** | Screenshots of the saved item and of the relocked master; the two audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-04 — Finalising a member's quote relocks the master by itself

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset, or `UAT-OWN-03` done. If `UAT-WSQ-04` has run, A4's quote is already at v2 and this makes the next version; that is fine |
| **Data** | `UAT-AWB-BOOKED`; A4's `UAT-AIR-A4-2` |
| **Steps** | 1. As Admin, **Unlock for edits** with the reason `Add a fee (UAT)`. 2. As Operations, on A4's `Bánh kẹo (UAT)` **Add fee**: pick any surcharge the form offers and give it what it asks for. 3. Price A4's quote again (the button reads **Price quote** while no draft is open), **Confirm selling rate** (box empty), **Finalise quote**. 4. Read the badge. 5. **Settings → Audit access** (as Admin). |
| **Expected** | Step 2: the fee is added. Step 3: the new version is finalised. Step 4: **Items and fees locked**, without anyone pressing Lock again. Step 5: `master.relocked` marked automatic, its reason "quote vN finalised for SX-…" |
| **Privacy / permission** | OD-88; stand-in F-6 (relock on finalise) |
| **Evidence to capture** | Screenshots of the badge before and after step 3; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-05 — A new tariff expires a quote whose goods are not yet received

| | |
|---|---|
| **Role** | Operations, Admin, then Customer (A1) |
| **Prerequisites** | **Fresh reset**; `UAT-TAR-02` and `UAT-WSQ-05` not run (the tariff draft "Kango Canada air rates, three prices updated (UAT)" still waits; `UAT-AWB-OPEN` is still open). The seed has no A1, A2 or A4 shipment on an open master, so steps 1 to 6 create them; they also prepare `UAT-OWN-06` |
| **Data** | Three new shipments; a new master `UAT-AWB-OWN`; A3's `UAT-AIR-A3-1` on `UAT-AWB-OPEN` |
| **Steps** | 1. As Operations, **Shipments → New** three times, route Vietnam → Canada, any Canadian recipient address, one package of 3 kg, **Confirm**: for A1 Phạm Thị Thu Trang, A2 Emily Carter and A4 Đỗ Ngọc Lan. Note each Solaris ID (`SX-VCA-…`). 2. **Workspace → New master**: Air Standard, HCM, vendor reference `UAT-AWB-OWN`; **Add a customer's shipment** for each of the three; **Edit master**: actual weight 9 kg. 3. On each card **Add item** (`Áo thun (UAT)`, 2 pieces, 3 kg), then **Price quote**, **Confirm selling rate** (box empty) and **Finalise quote**. 4. **Send to customer** for A1's and A2's quotes. 5. As A2 (`emily.air@example.com`) open **Quotes** and **Accept** the new quote; as Operations open A2's **Review draft invoice** and keep that tab open. 6. As Operations, on A4's card **Issue invoice** at GST/HST 0 %. 7. On `UAT-AWB-OPEN`, A3's quote: **Re-price**, **Confirm selling rate**, **Finalise quote**; then **Milestones and closing → Record a milestone**: *Received at warehouse*, published. 8. As Admin, **Settings → Tariff updates**: open the draft and **Approve and activate**. 9. As Operations, re-open `UAT-AWB-OWN`, A1's Quote panel and the invoice area. 10. Re-open `UAT-AWB-OPEN`, A3's Quote panel. 11. As A1 (`trang.air@example.com`), open **Báo giá** and the quote for A1's new shipment. 12. List the newest files in `data/uat/account_mail`. 13. As Admin, **Settings → Audit access**: find `quote.expired`. |
| **Expected** | Step 9: banner **Expired: re-quote on the new rate** — "Quote v1 expired when tariff TRF-… became active before the goods were received …", with **Re-quote on the new rate**; the sent quote reads **Expired**; the invoice area says "This quote expired; re-quote it before invoicing." Step 10: A3's finalised quote is unchanged, no expiry banner (its goods were received). Step 11: status **Đã hết hạn**, with "Báo giá này đã hết hạn vì giá cước thay đổi trước khi chúng tôi nhận hàng của bạn. Solaris Express sẽ gửi bạn báo giá mới."; no accept or decline control. Step 12: no email about the expiry (follow-up F-5). Step 13: `quote.expired` rows for A1's and A2's new shipments only; none for A3, A4 or any booked or completed master (stand-in: their quotes never expire) |
| **Privacy / permission** | OD-89. The customer reads the neutral sentence; no tariff, cost or reason detail |
| **Evidence to capture** | Screenshots of steps 9, 10 and 11; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-06 — Expiry withdraws the draft invoice and spares an issued invoice

| | |
|---|---|
| **Role** | Operations, then Customer (A2) |
| **Prerequisites** | `UAT-OWN-05` done (its steps 5 and 6 prepared this case before the activation) |
| **Data** | A2's and A4's new shipments on `UAT-AWB-OWN`; the draft tab kept open at step 5 of `UAT-OWN-05` |
| **Steps** | 1. Reload the draft tab for A2's shipment. 2. Open **Finance → Invoices**, **Accepted, not invoiced**. 3. On `UAT-AWB-OWN`, read A2's and A4's Quote panels and invoice areas. 4. Open A4's invoice. 5. As A2, open **Quotes** and the accepted quote. |
| **Expected** | Step 1: status **Withdrawn**; banner **This draft was withdrawn** with "quote v1 expired: tariff TRF-… became active before the goods were received"; no Send. Step 2: A2's new shipment is not listed (an expired offer is not waiting for an invoice). Step 3: A2's quote shows **Expired: re-quote on the new rate**; A4's quote has no expiry banner, and its invoice line shows the `INV-` number (follow-up F-4: an issued invoice and its quote are never touched). Step 4: the invoice is unchanged (status, lines, total). Step 5: **Expired**, with "This quote has expired because the rates changed before your goods were received. Solaris Express will send you a new quote." (A2 reads English) |
| **Privacy / permission** | Nothing about the withdrawn draft reaches the customer |
| **Evidence to capture** | Screenshots of steps 1, 3 and 5 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-07 — Re-quote after expiry

| | |
|---|---|
| **Role** | Operations, then Customer (A1) |
| **Prerequisites** | `UAT-OWN-05` done |
| **Data** | A1's new shipment on `UAT-AWB-OWN` |
| **Steps** | 1. On A1's Quote panel press **Re-quote on the new rate**. 2. **Confirm selling rate** (box empty), **Finalise quote**, **Send to customer**. 3. As A1, open **Báo giá**. 4. Open the new quote; do not answer it yet if `UAT-OWN-15` follows. |
| **Expected** | Step 1: a draft v2 opens, priced on the newly active tariff; the expiry banner goes. Step 2: v2 finalised and sent; a new `quote.sent.vi` file for `trang.air`. Step 3: the expired v1 and the waiting v2. Step 4: accept and decline are offered for v2 |
| **Privacy / permission** | The customer reads only the new figures |
| **Evidence to capture** | Screenshots of the v2 panel and of A1's quote list |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-08 — Accepting a quote prepares its invoice as a draft

| | |
|---|---|
| **Role** | Customer (A1), then Operations |
| **Prerequisites** | Fresh reset; `UAT-QAC-01` done (A1 accepted the quote for `UAT-AIR-A1-2`). Do not run `UAT-QAC-02` first: it sends this draft |
| **Data** | `UAT-AIR-A1-2` on `UAT-AWB-BOOKED` |
| **Steps** | 1. As Operations open `UAT-AWB-BOOKED`, A1's card, and read the invoice area. 2. **Finance → Invoices**, **Accepted, not invoiced**. 3. Press **Review draft invoice** on A1's row and read every field. 4. As Admin, **Settings → Audit access**: find the draft's creation. |
| **Expected** | Step 1: "The customer accepted this quote; its invoice is ready as a draft." and **Review draft invoice**; no **Issue invoice** button (manual issue is refused while a draft exists, `invoice_draft_exists`). Step 2: A1's row with **Review draft invoice**. Step 3: title "Draft invoice · …", "from accepted quote v1", status **Draft**; "No invoice number yet: it is assigned when you send the invoice."; **Bill to (name)** Phạm Thị Thu Trang; **GST/HST** **0 %**, "Route VN → CA: international, zero-rated (0 %)." (OD-102, `UAT-OWN-18`), the check "I have checked the GST/HST on this invoice" unticked (OD-94); the lines are the accepted quote's revenue lines (no cost, no vendor name) and they add up to **Accepted quote (before tax)**; at 0 % the saved **Subtotal** equals the total and the GST/HST is 0.00; revision 1. Step 4: `invoice.draft_created`, its actor the customer's account (`customer_account:CA-000001` on a fresh reset), not a member of staff |
| **Privacy / permission** | OD-89: no `INV-` number exists until staff send it |
| **Evidence to capture** | Screenshots of steps 1 and 3; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-09 — Unsaved changes: save first

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset (A2's seeded draft for `UAT-AIR-A2-1` is unsent) |
| **Data** | **Finance → Invoices → Accepted, not invoiced**, A2's row, **Review draft invoice** |
| **Steps** | 1. Open A2's draft. 2. Type `PO-UAT-0001` in **Customer reference / PO** (do not save). 3. Look at **Download PDF (draft)** and **Send invoice**. 4. Click the **Finance** link at the top of the page; cancel the question. 5. Reload the browser tab; cancel the browser's question. 6. Tick **I have checked the GST/HST on this invoice** (0 %, as the route filled it in) and **Save draft**. 7. Look at the two buttons again. 8. Change the reference again, then press the browser's **Back** button. |
| **Expected** | Step 3: both disabled, with "Save your changes first. Send and Download use the saved draft."; **Undo my changes** appears. Step 4: "You have unsaved changes to this draft invoice. Leave without saving?"; cancelling keeps the page and the typing. Step 5: the browser's own leave-page warning. Step 6: before the tick, **Save draft** is disabled with "Tick “I have checked the GST/HST on this invoice” before saving. …" (OD-94); after it, "Draft saved."; revision 2, GST/HST checked for this revision. Step 7: both enabled. Step 8: **not** intercepted — the page is left without a question (developer stand-in; the server's revision check still guards any later save) |
| **Privacy / permission** | OD-90: save before anything else |
| **Evidence to capture** | Screenshots of steps 3, 4 and 6 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-10 — A changed total needs a reason; GST/HST is checked on the draft

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Fresh reset, or `UAT-OWN-09` done |
| **Data** | A2's draft for `UAT-AIR-A2-1` |
| **Steps** | 1. Raise one line's **Amount (CAD), line** by 5.00, tick **I have checked the GST/HST on this invoice** (changing the line cleared it) and **Save draft** with **Why the total differs from the accepted quote** empty. 2. Type `Extra packing (UAT)` there, tick the check if it is clear, and **Save draft**. 3. Open **GST/HST** and **GST/HST is**, and read the choices; leave them at 0 % and **Included in the price**. 4. As Admin, **Settings → Audit access**: find the edits. 5. Set the amount back, clear the reason, tick the check, **Save draft**. |
| **Expected** | Step 1: refused, naming the reason field: "The total differs from the accepted quote (CAD …); say why."; nothing saved (a field error is reported before the GST/HST check). Step 2: saved; the saved figures show the new total (GST/HST 0.00 at 0 %) beside **Accepted quote (before tax)**. Step 3: 0, 5, 13, 14 and 15 % (and any other rate in **Settings → GST/HST rates**, `UAT-OWN-29`); **Included in the price** and **Added on top** (staff may change both, OD-94, OD-102; `UAT-OWN-20`). Step 4: `invoice.draft_edited` rows, each with what changed, from and to, and the revision, and an `invoice.draft_tax_confirmed` row for each confirmed save. Step 5: saved without a reason (the total matches again) |
| **Privacy / permission** | Edits are audited with a diff (OD-90) |
| **Evidence to capture** | Screenshots of the refusal and the saved draft; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-11 — Two people edit the same draft

| | |
|---|---|
| **Role** | Operations (two tabs) |
| **Prerequisites** | Fresh reset, or after `UAT-OWN-10` |
| **Data** | A2's draft for `UAT-AIR-A2-1`, open in tab 1 and tab 2 |
| **Steps** | 1. In tab 1 put `Tab one (UAT)` in **Notes printed on the invoice**; tick **I have checked the GST/HST on this invoice** if it is clear (Save needs it, OD-94; a notes-only change keeps it as it was); **Save draft**. 2. In tab 2 (not reloaded) put `Tab two (UAT)` in the notes; tick the check if it is clear; **Save draft**. 3. In tab 2 press **Reload the draft**. 4. Repeat steps 1 and 2, but in tab 2 save nothing and press **Send invoice** instead (tab 2 was opened before tab 1's save). |
| **Expected** | Step 2: banner **Someone else changed this draft** — "It was saved again after you opened it, so nothing was saved, sent or downloaded. …"; tab 1's notes stand. Step 3: tab 2 shows tab 1's saved text and revision. Step 4: the same banner; nothing is sent and no `INV-` number is used |
| **Privacy / permission** | The server's revision check backs the screen |
| **Evidence to capture** | Screenshots of the banner and the reloaded draft |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-12 — Download the draft, then send the invoice

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset, or after `UAT-OWN-11`; `UAT-QAC-02` step 4 expects A2's row to remain, so run `UAT-QAC-02` first if both are run |
| **Data** | A2's draft for `UAT-AIR-A2-1` (Emily Carter, English) |
| **Steps** | 1. If the page does not say "GST/HST checked for this revision by …" (on a fresh reset it does not), tick **I have checked the GST/HST on this invoice** and **Save draft**. 2. **Download PDF (draft)** and open it. 3. **Send invoice**. 4. Read the page, then open the invoice through the **Sent as** link. 5. **Download PDF** on the invoice. 6. List the newest files in `data/uat/account_mail` and open the `invoice.sent.en-emily.air…` file. 7. Re-open **Accepted, not invoiced**. |
| **Expected** | Step 1: "Draft saved."; with nothing else changed the revision does not move; **Send invoice** and **Download PDF (draft)** are enabled only now (OD-94; Download since RC-UAT-20, `UAT-OWN-30`). Step 2: a diagonal **DRAFT** watermark; Solaris Express Inc., 2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6, solarisexpressinc@gmail.com, "GST/HST BN: 795093756RT0001", "Terms: Due on receipt", "Currency: CAD"; bill-to; the lines with Qty, Rate, Amount and Tax **Zero-rated**, the subtotal, the row **GST @ 0%** at 0.00, total and due date; the E-transfer and wire lines and the footer "Thank you for your business! We accept payment via E-transfer to info@solarisexpress.ca" (DEC-0235); **no** "Prices include …" sentence (at 0 % nothing is included); labels in English; no invoice number; **no cost and no vendor name**. Step 3: "Invoice INV-… issued."; status **Sent**. Step 4: the email status is shown; the invoice has the draft's lines, GST/HST (0 %) and bill-to; its total equals the lines. Step 5: the same layout and wording, the `INV-` number, **no watermark**. Step 6: English; invoice number, total and due date only — no line and no vendor name. Step 7: A2's `UAT-AIR-A2-1` row is gone (the three `UAT-AIR-DOM-*` rows stay) |
| **Privacy / permission** | Customer-facing documents; the email carries no line (OD-84) |
| **Evidence to capture** | Both PDFs; the captured file's name and body |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-13 — The import report lists the confirmed price steps

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | **Settings → Tariffs**, the active version "Kango 2026-10-12 (sanitized demo)" |
| **Steps** | 1. In **Tariff versions**, press **View** on the active version and read the card **Import warnings (…) · TRF-…** beneath it (full walk-through: `UAT-OWN-34`). 2. With the browser's developer tools open on the **Network** tab, view it again and open the response of `tariffs/versions/<id>`: read `report.confirmed_price_steps` and `report.anomaly_counts`. 3. Open the Air Express rate brackets for HCM zone 2 and for Hà Nội zones 2 and 3 around 16 kg. |
| **Expected** | Step 1: **Import warnings (39)**; none is about a price falling with weight; **Confirmed price steps (3)** listed apart. Step 2: `confirmed_price_steps` holds exactly three entries — HCM-AIR-CAD!F39, HN-AIR-CAD!F38 and HN-AIR-CAD!G38, each product `AIR-CAD EXPRESS`, band 16; `anomaly_counts` has no `price_falls_with_weight`. Step 3: the 16 kg price is lower than the band before it, exactly as printed, and nothing is flagged (OD-81) |
| **Privacy / permission** | Tariffs are visible with the tariff permission only |
| **Evidence to capture** | Screenshot of the report; the three JSON entries |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-14 — HCM meat / egg / dairy / honey at 20,000 VND/kg

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset; `UAT-AWB-OPEN` still open (before `UAT-WSQ-05`) |
| **Data** | `UAT-AWB-OPEN`; A4's item `Cà phê rang xay (UAT)` |
| **Steps** | 1. **Edit master**: actual weight **21 kg**. 2. On A4's item **Add fee**: search `mat ong` (or `trung`) without accents and pick the HCM meat / egg / dairy / honey surcharge (HCM air row 41). 3. Read the fee line and the **Vendor cost** panel. |
| **Expected** | Step 2: the search finds it without accents. Step 3: priced at 20,000 VND/kg on the whole carton, i.e. on the master's 21 kg: **420,000 VND** (21 × 20,000) before markup (OD-82); not flagged as unconfirmed. Because the master has more than one carton and none recorded, the whole-master weight may be marked provisional; that is the existing rule, not a defect |
| **Privacy / permission** | Vendor cost is internal |
| **Evidence to capture** | Screenshot of the fee line and the Vendor cost panel |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-15 — No vendor name reaches the customer

| | |
|---|---|
| **Role** | Admin, Operations, then Customer (A1) |
| **Prerequisites** | `UAT-OWN-07` done (A1's new shipment on the open `UAT-AWB-OWN`). No seeded surcharge names a vendor, so step 1 creates one: on your own machine, outside the repository, copy `backend/tests/fixtures/kango_canada_rates_2026-10-12_sanitized.xlsx`, open sheet **PHỤ THU** only, and put `Kango ` in front of the name of the HCM watch surcharge (the one `UAT-WSQ-01` shows on A3's watch); save the copy |
| **Data** | The edited copy; A1's new shipment; `trang.air@example.com` |
| **Steps** | 1. As Admin, **Settings → Tariffs → Import a workbook by hand**: the copy, effective today, label `Vendor name test (UAT)`; **Import as draft**; then **Settings → Tariff updates**: **Approve and activate** it. 2. As Operations, on A1's card **Add item** (`Đồng hồ (UAT)`, 1 piece, 0.3 kg) and **Add fee**: search `dong ho`, pick the watch surcharge. 3. **Re-quote on the new rate** (or **Price quote**), **Confirm selling rate**, **Finalise quote**, **Print customer quote**, **Send to customer**. 4. As A1, open **Báo giá** and the new quote; **Accept** it. 5. As Operations, **Review draft invoice**: read the lines; **Add a line** `Phụ thu Kango (UAT)` at CAD 0.00, tick **I have checked the GST/HST on this invoice** (adding a line cleared it), **Save draft**, **Download PDF (draft)**, **Send invoice**. 6. Open the invoice: **Download PDF** and **Print**; **Record payment** of the full total in CAD; **Print receipt**. 7. Open the newest `quote.sent.vi` and `invoice.sent.vi` files for `trang.air`. 8. Open the public tracking page for that shipment's Solaris ID. 9. As Operations, re-read A1's Quote panel and the **Vendor cost** panel. |
| **Expected** | Step 1: activating expires A1's unanswered v2 from `UAT-OWN-07` (goods not received; correct, OD-89). Step 3: the printed quote shows the watch surcharge as **Phụ phí**. Step 4: the account quote shows **Phụ phí**, never "Kango". Step 5: the draft's lines were written neutral at creation (**Phụ phí**); the added line prints as **Phụ phí** in the PDF. Step 6: invoice document, both PDFs and the receipt carry no "Kango" and no vendor name. Step 7: neither email carries a line or a vendor name. Step 8: no tariff text; a carrier link, if any, is shown under its generic name, **Theo dõi chặng chính** / **Theo dõi chặng cuối** (Master Tracking / Last Mile Tracking), never under a carrier's or vendor's name, even when staff labelled it with the vendor's name (OD-91, OD-92; `UAT-OWN-23`); a staff-typed carrier name naming a vendor in other text would read "Carrier". Step 9: staff screens keep the vendor's wording ("Kango …"), as decided |
| **Privacy / permission** | OD-84: S1 if any customer-facing output names a vendor |
| **Evidence to capture** | The printed quote, both invoice PDFs and the receipt; screenshots of steps 4 and 9; the two captured files |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-16 — Air Express: a typed rate and reason, then finalise

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed Vietnam → Canada shipment on no master (book one as in `UAT-OWN-05` step 1 if none) |
| **Data** | A new Air Express master from HCM |
| **Steps** | 1. **Workspace → New master**: Air Express, HCM; add the shipment; **Edit master**: actual weight 16 kg; add an item. 2. **Price quote** and read the **Vendor cost** panel's base freight and zone. 3. **Confirm selling rate** with the box empty. 4. Type `24.00` without a reason; then with `Express rate agreed (UAT)`. 5. **Finalise quote**. |
| **Expected** | Step 2: base freight from the Air Express bracket at 16 kg for the zone shown, the printed price (compare with `UAT-OWN-13` step 3). Step 3: refused — this service has no default rate (OD-86). Step 4: refused without a reason; accepted with it. Step 5: finalised |
| **Privacy / permission** | The reason is audited |
| **Evidence to capture** | Screenshots of both refusals and the finalised quote |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-17 — The rate-email mailbox and approver

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Fresh reset |
| **Data** | **Settings → Tariff updates** (mailbox and **Approvers**) |
| **Steps** | 1. Read the intake mailbox shown. 2. Open **Approvers**. 3. Read `ENVIRONMENT.md` §2, "The tariff approver in UAT". |
| **Expected** | Step 1: `tariffs@demo.example.com` (a test address). Step 2: `admin@demo.example.com` only. Step 3: in production, before anyone saves these settings, both default to `benjamin.le@soleiltransportation.com` (OD-87); the UAT seed replaces them with demo addresses, so the production default is never stored in UAT. The default itself is pinned by the automated suite |
| **Privacy / permission** | No live mailbox is connected (OD-87) |
| **Evidence to capture** | Screenshots of steps 1 and 2 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Owner answers of 2026-10-22 (RC-UAT-19) — `UAT-OWN-*`

The owner's answers OD-91 to OD-101 (Louis Tong, on Ben's behalf, 2026-10-22): GST/HST on the
draft invoice is included in the price and checked before Save and Send (`-18` to `-22`);
customers read tracking links under generic names, with no vendor name (`-23`, `-24`);
costume jewellery (HCM air row 27) is quoted per line, not per kilogram (`-25` to `-27`).
**Updated for RC-UAT-20** (Ben, 2026-10-23): the rate a draft starts at now follows the route
(OD-102: a Vietnam → Canada draft is **0 %**, zero-rated, no longer 13 %); costume jewellery
takes both the vendor's VND cost and the customer price (OD-103); the Vietnamese leg names are
approved (OD-104). The questions P-1 to P-7 are answered; see the top of this pack.

**Order.** `UAT-OWN-18` to `-20`, `-30` and `-12` all use A2's seeded draft for
`UAT-AIR-A2-1`: run `-18`, `-30` (which runs `-19` inside it), `-20`, then `-12` (which sends
it). `UAT-OWN-21` sends A1's draft for
`UAT-AIR-A1-2`, as `UAT-QAC-02` does: on one reset run one of the two. `UAT-OWN-25` and `-26`
need `UAT-AWB-OPEN` **still open** (before `UAT-WSQ-05`). The others need only a fresh reset.

### UAT-OWN-18 — A Vietnam → Canada draft starts at GST/HST 0 %, zero-rated by route

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset (A2's seeded draft for `UAT-AIR-A2-1` is unsent; the route filled its rate in at creation); signed in as `ops@demo.example.com` |
| **Data** | **Finance → Invoices → Accepted, not invoiced**, A2's row, **Review draft invoice** |
| **Steps** | 1. Open A2's draft. 2. Read the **GST/HST** section: the rate, **GST/HST is**, the route line, the hint and the summary sentence. 3. Read **Accepted quote (before tax)** and the saved figures. 4. Look at the check **I have checked the GST/HST on this invoice**, at **Save draft**, **Send invoice** and **Download PDF (draft)**. 5. Open the **GST/HST** list and read the rates offered; close it without choosing. |
| **Expected** | Step 2: **0 %**; **Included in the price**; "Route VN → CA: international, zero-rated (0 %)."; hint "Filled in from the route: 0 % when one end is outside Canada; for a domestic shipment, the destination province's rate, included in the price. Check it on every invoice."; "GST/HST 0 % (zero-rated): no tax, total …" and no "Prices include" sentence (OD-102). Step 3: the total equals **Accepted quote (before tax)**; subtotal = total; GST/HST 0.00. Step 4: the check is **unticked**; **Send invoice** and **Download PDF (draft)** are disabled with "The GST/HST of the saved draft is not confirmed: tick the check and save before sending or downloading."; **Save draft** says "Tick “I have checked the GST/HST on this invoice” before saving. Changing the rate, the mode or a line clears it." Step 5: 0, 5, 13, 14 and 15 % |
| **Privacy / permission** | Staff screen; the customer sees nothing of the draft (OD-89) |
| **Evidence to capture** | Screenshot of the GST/HST section, the saved figures and the rate list |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-19 — Save and Send wait for the GST/HST check

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | `UAT-OWN-18` (and steps 1 and 2 of `-30`, which calls this case at its step 3) done, or a fresh reset; A2's draft not yet confirmed |
| **Data** | A2's draft for `UAT-AIR-A2-1` |
| **Steps** | 1. Note the revision. 2. Tick **I have checked the GST/HST on this invoice**, change nothing else, and **Save draft**. 3. Read the revision, the line beneath the check and **Send invoice** (do not press it). 4. As Admin, **Settings → Audit access**: find the confirmation. |
| **Expected** | Step 2: "Draft saved." Step 3: the revision has **not** moved (nothing else changed, so only the confirmation of the current revision is recorded); "GST/HST checked for this revision by …" naming the Operations user; **Send invoice** and **Download PDF (draft)** are enabled. Step 4: one `invoice.draft_tax_confirmed` row with the revision, mode **included**, rate 0 and the subtotal, GST/HST and total; no `invoice.draft_edited` row for this save. The server refuses a save or a send without the confirmation too (422 `tax_unconfirmed`; covered by the automated suite) |
| **Privacy / permission** | The confirmation is audited with the staff member's name (OD-94) |
| **Evidence to capture** | Screenshots before and after the save; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-20 — Changing the rate, the mode or a line clears the check

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | `UAT-OWN-19` done (A2's draft saved and confirmed) |
| **Data** | A2's draft for `UAT-AIR-A2-1` |
| **Steps** | 1. Set **GST/HST** to **5 %**; read the check, the summary and **Save draft**. 2. Set it back to **0 %**; read the summary. 3. Set it to **13 %** and **GST/HST is** to **Added on top**; read the summary. 4. **Undo my changes**. 5. Raise one line's amount by 1.00; read the check. **Undo my changes**. 6. Type `Checked (UAT)` in **Notes printed on the invoice** only; read the check; **Save draft**. 7. Set **GST/HST** to **5 %** (included), tick the check, **Save draft**; then set it back to **0 %**, tick, **Save draft**. 8. As Admin, **Settings → Audit access**: read the `invoice.draft_edited` rows. |
| **Expected** | Steps 1, 3 and 5: the check **clears** at each change; **Save draft** asks for the tick again; **Send invoice** and **Download PDF (draft)** are disabled while anything is unsaved. Step 1: "Tax included in the price: subtotal before tax …, GST @ 5% …, total …" (RC-UAT-24, I-11), the total unchanged and GST/HST = total × 5 ÷ 105; "Preview of the form; the saved figures are below." Step 2: "GST/HST 0 % (zero-rated): no tax, total …"; subtotal = total. Step 3: "GST/HST 13 % added on top: subtotal …, GST/HST …, total …": subtotal = the lines, GST/HST = 13 % of it, total = subtotal + GST/HST (the total rises). Step 6: a notes-only change keeps the check as it was (ticked); saved as a new revision, confirmed for that revision. Step 7: each save is a new revision, confirmed; **Send invoice** enabled after the last one, at 0 %, as the route filled it in. Step 8: the rate changes are named (`tax_rate_percent` from and to) with a GST/HST snapshot (mode and rate) on each row |
| **Privacy / permission** | OD-94: staff may change the rate and the mode; every change needs a fresh check |
| **Evidence to capture** | Screenshots of the summary at steps 1, 2 and 3 and of the cleared check; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-21 — GST/HST 5 %, added on top

| | |
|---|---|
| **Role** | Customer (A1), then Operations |
| **Prerequisites** | Fresh reset; `UAT-QAC-01` done (A1 accepted the quote for `UAT-AIR-A1-2`, which prepared a draft). Run this **instead of** `UAT-QAC-02` step 3 on the same reset: both send this draft |
| **Data** | A1's draft for `UAT-AIR-A1-2` (Phạm Thị Thu Trang, Vietnamese) |
| **Steps** | 1. **Finance → Invoices → Accepted, not invoiced**, A1's row, **Review draft invoice** (it starts at 0 %, zero-rated by route, OD-102). 2. Set **GST/HST is** to **Added on top** and **GST/HST** to **5 %**; read the summary. 3. Tick **I have checked the GST/HST on this invoice**, **Save draft**, **Download PDF (draft)**. 4. **Send invoice**. 5. Open the invoice; **Download PDF**. 6. Open the newest `invoice.sent.vi-trang.air…` file. |
| **Expected** | Step 2: "GST/HST 5 % added on top: subtotal …, GST/HST …, total …"; the subtotal equals **Accepted quote (before tax)**, GST/HST is 5 % of it to the cent, total = subtotal + GST/HST. Step 3: saved and confirmed; the draft PDF shows each line before tax with Tax **GST**, the subtotal, the row **GST @ 5%** and the total, and **no** "include" sentence (DEC-0235). Step 4: "Invoice INV-… issued." Step 5: the invoice's subtotal is the lines, tax 5 % on top, the same total as the draft; Vietnamese labels; no watermark; no "include" sentence. Step 6: invoice number, total and due date only |
| **Privacy / permission** | Customer-facing documents: no cost and no vendor name |
| **Evidence to capture** | Both PDFs; screenshot of the summary at step 2 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-22 — The issued invoice of a Vietnam → Canada move: GST/HST 0 %, nothing included

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Fresh reset (`INV-000002` unpaid, not voided: `UAT-FIN-04` not run) |
| **Data** | `INV-000002` (A1, `UAT-AIR-A1-1`, Vietnamese; sent by the seed from a draft the route filled in at 0 % and staff confirmed); `INV-000004` for comparison |
| **Steps** | 1. **Finance → Invoices**, open `INV-000002`: read the subtotal, GST/HST and total. 2. **Download PDF** and **Print**. 3. Open `INV-000004` and **Download PDF**. 4. As Admin, **Settings → Audit access**: find `invoice.draft_created`, `invoice.draft_tax_confirmed` and `invoice.draft_sent` for `UAT-AIR-A1-1`. |
| **Expected** | Step 1: total **CAD 108.00** = the lines; GST/HST 0 %, **CAD 0.00**; subtotal **CAD 108.00**; the tax status reads GST/HST 0 % (OD-102; in RC-UAT-19 the same invoice read 13 % included, GST/HST 12.42). Step 2: each line's Tax reads **Zero-rated** and the summary row **GST @ 0%**; the PDF and the printed document carry **no** "Prices include …" sentence (at 0 % nothing is included); English labels, the bill-to without accents (DEC-0235, stand-in I-1); no cost, exchange rate or vendor name. Step 3: `INV-000004` was issued by hand at 5 % added on top: the tax row reads **GST/HST 5 %** (a rate chosen by hand, not from the table), no "include" sentence either. Step 4: `invoice.draft_created` carries the route (international, VN to CA) and the rate 0; the other two rows carry the mode **included** and the rate 0. The "include" sentence at a domestic rate is checked on a draft in `UAT-OWN-28` |
| **Privacy / permission** | Customer-facing documents |
| **Evidence to capture** | Both PDFs; screenshot of `INV-000002`'s totals; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-23 — A last-mile link reads "Last Mile Tracking", never a vendor's name

| | |
|---|---|
| **Role** | Operations, anyone signed out, then Customer (A1) |
| **Prerequisites** | Fresh reset (`UAT-AIR-A1-1` has no transport leg). **Do not open the carrier link** and make no request to a carrier site (`ENVIRONMENT.md` §8); read it, hover it, do not click it |
| **Data** | A1's `UAT-AIR-A1-1` on `UAT-AWB-TRANSIT`; `trang.air@example.com` |
| **Steps** | 1. As Operations, open the shipment with booking reference `UAT-AIR-A1-1` and note its Solaris ID (`SX-VCA-…`). 2. **Transport legs → Add leg**: **Leg type** *Final delivery*, **Provider / carrier** `Kango Logistics` (the vendor, first in the list since RC-UAT-20, `UAT-OWN-33`), tick **This leg delivers to the final recipient**, and fill whatever else the form requires; save. 3. On that leg **Add carrier reference**: **Carrier** *UPS*, **Tracking number** `1ZUAT0000000000001`, **Tracking source** *External link only*, **Public carrier link** `https://www.ups.com/track?tracknum=1ZUAT0000000000001`; save. 4. In a private window open <http://localhost:5173/track>, enter the Solaris ID, and read the link and the note beneath it in Vietnamese, then in English. 5. As A1, open **Lô hàng của tôi** and the shipment; read the link; switch to English. 6. As Operations, re-read the shipment's **Transport legs**. |
| **Expected** | Step 4: the link is **shown** (OD-91), reading **"Theo dõi chặng cuối: mở trang theo dõi"** / **"Last Mile Tracking: open the tracking page"**, with the note that it opens the carrier's own website; hovering shows the `www.ups.com` address. Nowhere on the page: "Kango", "UPS" as a label, or the tracking number. Step 5: **"Theo dõi chặng cuối: mở trang theo dõi của hãng vận chuyển"** / **"Last Mile Tracking: open the carrier's tracking page"**; no vendor or carrier name. Step 6: staff screens keep the detail: *Final delivery*, the chip **Last Mile Tracking**, provider `Kango Logistics`, carrier UPS and the tracking number as typed. The Vietnamese names are approved (OD-104). A link stored with the vendor's name as its carrier (the screen offers only a fixed list, so only through the API) is also shown under the generic name; that is covered by the automated suite |
| **Privacy / permission** | OD-84, OD-91, OD-92: S1 if any customer-facing page names a vendor |
| **Evidence to capture** | Screenshots of the link on the public page and in the account, in both languages; the staff leg |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-24 — A Vietnam-side link reads "Master Tracking"; a link on the vendor's own site stays hidden

| | |
|---|---|
| **Role** | Operations, anyone signed out, then Customer (A1) |
| **Prerequisites** | Fresh reset (`UAT-AIR-A1-2` has no transport leg). Do not open any carrier link (`ENVIRONMENT.md` §8) |
| **Data** | A1's `UAT-AIR-A1-2` on `UAT-AWB-BOOKED`; `trang.air@example.com` |
| **Steps** | 1. As Operations, open the shipment with booking reference `UAT-AIR-A1-2`; note its Solaris ID. 2. **Transport legs → Add leg**: **Leg type** *Consolidation / linehaul*, **Provider / carrier** `Kango Logistics`; save. 3. On that leg **Add carrier reference**: **Carrier** *Other*, **Tracking number** `KGUAT0001`, **Tracking source** *External link only*, **Public carrier link** `https://tracking.kango-uat.example.com/KGUAT0001`; save. 4. Add a second reference on the same leg: **Carrier** *DHL*, **Tracking number** `UATDHL0001`, *External link only*, `https://www.dhl.com/ca-en/home/tracking.html?tracking-id=UATDHL0001`; save. 5. Open public tracking (<http://localhost:5173/track>) for the Solaris ID, in Vietnamese and English; hover the link. 6. As A1, open the shipment in **Lô hàng của tôi**; switch to English. 7. As Operations, **Retire** the DHL reference with the reason `Link test (UAT)`; reload the public page. |
| **Expected** | Step 3: staff may store the vendor's link. Steps 5 and 6: one link, **"Theo dõi chặng chính: …"** / **"Master Tracking: …"** (the same wording as in `UAT-OWN-23`, with the master name), pointing at the `www.dhl.com` address; the vendor's own link never appears (OD-105: it stays hidden), and neither does "Kango". Step 7: no carrier link at all: the vendor's link is never offered in its place. In UAT the vendor's host is also outside the allowed carrier hosts, so either rule hides it; the rule that a host naming a vendor is hidden is pinned by the automated suite |
| **Privacy / permission** | OD-91, OD-92, OD-105 |
| **Evidence to capture** | Screenshots of the public page and the account page at steps 5 to 7 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-25 — Costume jewellery: two empty fields for the line, and no finalising without both

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset; `UAT-AWB-OPEN` still open (before `UAT-WSQ-05`) |
| **Data** | `UAT-AWB-OPEN`; A3's `UAT-AIR-A3-1`, item `Quần áo (UAT)` |
| **Steps** | 1. On A3's `Quần áo (UAT)` press **Add fee**; search `my ky` (or `trang suc`) without accents and pick **Hàng mỹ ký (trang sức giả)** (HCM air row 27). 2. Read the form. 3. Leave both fields empty and add the fee. 4. Read the fee line. 5. **Re-price**, **Confirm selling rate** (box empty), **Finalise quote**. |
| **Expected** | Step 1: found without accents. Step 2: two fields, **Vendor cost (VND)** and **Customer price (CAD)**, both **empty** (nothing prefilled, no conversion offered), with "Quoted case by case. If you do not know them yet, leave them blank: the line then blocks finalising until both are entered on the line."; **no quantity, no weight, no kg** and no file minimum; the basis reads "One amount for the line, quoted case by case" (OD-93, OD-103). Step 4: "Vendor cost (VND) and customer price (CAD) needed", with the two fields and **Save**, and "Quoted case by case: enter the vendor’s cost and the price the customer pays for this line. The customer is billed exactly this price. Without both, the quote cannot be finalised." Step 5: finalising is refused, blocking: "'Hàng mỹ ký (trang sức giả)' is quoted case by case; enter the vendor's cost (VND) and the customer price (CAD) for this line." |
| **Privacy / permission** | Vendor cost is internal (tariff permission) |
| **Evidence to capture** | Screenshots of the Add fee form, the fee line and the refusal |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-26 — Costume jewellery: the cost from the VND entered, the charge exactly the CAD price

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | `UAT-OWN-25` done (the row 27 line on A3's item, with neither value) |
| **Data** | A3's row 27 fee line on `UAT-AWB-OPEN` |
| **Steps** | 1. On the fee line type `200000` in **Vendor cost (VND)** only and press **Save**. 2. **Re-price**, **Confirm selling rate** (box empty), **Finalise quote**. 3. Type `25.00` in **Customer price (CAD)** and press **Save**. 4. **Re-price**; read the line in the **Vendor cost** panel (and the buy rate it shows) and in A3's and A4's Quote panels. 5. **Edit master**: actual weight 20 kg; edit A3's `Quần áo (UAT)` to 5 kg; **Re-price** again. 6. **Confirm selling rate** (box empty), **Finalise quote**. 7. As Admin, **Settings → Audit access**: find `shipment.fee_line_amount` and `shipment.fee_line_customer_price`. |
| **Expected** | Step 1: the line reads "Customer price (CAD) needed" and shows the vendor cost 200,000. Step 2: still refused, naming only what is missing: "… enter the customer price (CAD) for this line." Step 4: cost **200,000 VND** at the buy rate shown, on A3's shipment only (no share for A4, no kilograms, no quantity); the customer charge for the line is **exactly CAD 25.00**, no conversion and **no markup** on top (OD-103; stand-in R-7). Step 5: unchanged: still 200,000 VND and CAD 25.00, whatever the weights. Step 6: finalised. Step 7: one `shipment.fee_line_amount` row, from empty to 200000, and one `shipment.fee_line_customer_price` row, from empty to 25.00, each naming the Operations user |
| **Privacy / permission** | Vendor cost is staff-only; the customer sees only the CAD price as the line's charge |
| **Evidence to capture** | Screenshots of the refusal at step 2, of the line and the Vendor cost panel at steps 4 and 5; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-27 — Costume jewellery: neither value can be entered on a locked master

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset, or after `UAT-OWN-04`. If `UAT-WSQ-03` and `-04` are run on this reset, run them first: they expect A4's quote as the seed left it |
| **Data** | `UAT-AWB-BOOKED` (booked, items and fees locked); A4's `UAT-AIR-A4-2`, item `Bánh kẹo (UAT)` |
| **Steps** | 1. As Admin, **Unlock for edits** with the reason `Costume jewellery test (UAT)`. 2. As Operations, on A4's `Bánh kẹo (UAT)` **Add fee**: **Hàng mỹ ký (trang sức giả)**, both fields empty. 3. **Lock again**. 4. Read the fee line: **Vendor cost (VND)**, **Customer price (CAD)** and **Save**. 5. As Admin, **Unlock for edits** with the reason `Enter the amount (UAT)`; as Operations type `150000` in **Vendor cost (VND)** and `20.00` in **Customer price (CAD)**, and **Save**. 6. Price A4's quote again, **Confirm selling rate**, **Finalise quote**; read the badge. |
| **Expected** | Step 2: added, "Vendor cost (VND) and customer price (CAD) needed". Step 4: the line still says both are needed; both fields and **Save** are disabled while **Items and fees locked**, with "Locked: this master is booked. An Admin can unlock it to change the amount." (OD-88); the server refuses the change too (409 `master_locked`; covered by the automated suite). Step 5: accepted while unlocked; audited `shipment.fee_line_amount` from empty to 150000 and `shipment.fee_line_customer_price` from empty to 20.00. Step 6: finalised; the line charges exactly CAD 20.00; the master locks itself again (OD-97) |
| **Privacy / permission** | OD-88: both values are a fee edit and follow the master lock |
| **Evidence to capture** | Screenshots of the disabled fields and of the saved values |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Owner answers of 2026-10-23 (RC-UAT-20) — `UAT-OWN-*`

Ben's answers OD-102 to OD-108 (2026-10-23; DEC-0227 to DEC-0229, record
`docs/b2c_merge/24_FIXPACK_RC20_RECORD.md`): GST/HST on a draft follows the route (`-28` to
`-30`; the zero-rated Vietnam → Canada start is `UAT-OWN-18`); the findings of RC-UAT-19 are
fixed: the payment date (`-31`), Download waiting for the GST/HST check (`-30`), the vendor on
the final delivery leg and the staff leg names (`-33`), the tariff warnings on Settings
(`-34`); costume jewellery takes both values (`-32`, with `-25` to `-27`); and the wording the
owner kept (`-35`; its quote tax line changed in RC-UAT-21, OD-109 stand-in). The stand-ins these answers left (R-1 to R-10 in the developer draft) are
listed at the top of this pack; none blocks a case.

**Domestic drafts come from the seed.** A domestic shipment cannot be quoted on screen (an
air master takes only Vietnam → Canada shipments), so the seed places three domestic
shipments on their own master, `UAT-DOM-AWB`, for UAT only (see "The seeded air dataset").
`UAT-OWN-28` uses their drafts.

**Order.** `UAT-OWN-30` uses A2's seeded draft for `UAT-AIR-A2-1` before anyone ticks its
GST/HST check (after `UAT-OWN-18`, before `-19`; the full order is given above the RC-UAT-19
group). `UAT-OWN-29` changes a rate and puts it back. `UAT-OWN-31` records CAD 5.00 on
`INV-000003`: run it after `UAT-FIN-02`, `-06` and `-07`, or expect their amounts for
`INV-000003` to be CAD 5.00 lower. `UAT-OWN-32` needs `UAT-AWB-OPEN` **still open** (before
`UAT-WSQ-05`). The others need only a fresh reset.

### UAT-OWN-28 — Domestic drafts: NS 14 % and NB 15 % HST filled in and backed out; an unknown province waits for staff

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset (the three domestic drafts are unsent) |
| **Data** | A2's (Emily Carter, English) domestic shipments on `UAT-DOM-AWB`, all from Toronto: `UAT-AIR-DOM-NS` (Halifax, NS, B3H 1A1), `UAT-AIR-DOM-NB` (Moncton, NB, E1C 4M3), `UAT-AIR-DOM-UNK` (Halifax, no province and no postal code); **Settings → GST/HST rates** |
| **Steps** | 1. **Settings → GST/HST rates**: read the table. 2. **Finance → Invoices → Accepted, not invoiced**: find the three `UAT-AIR-DOM-*` rows. 3. **Review draft invoice** on `UAT-AIR-DOM-NS`: read the **GST/HST** section (rate, **GST/HST is**, route line, summary) and the saved figures. 4. Work it by hand: tax = total × 14 ÷ 114, rounded half up to the cent; subtotal = total − tax. 5. Set **GST/HST** to **13 %** (do not save); read the summary; **Undo my changes**. 6. Tick **I have checked the GST/HST on this invoice**, **Save draft**, **Download PDF (draft)**; read the totals. 7. Open `UAT-AIR-DOM-NB`'s draft; repeat steps 3 and 4 with × 15 ÷ 115. 8. Open `UAT-AIR-DOM-UNK`'s draft; read the **GST/HST** section and look at **Save draft**, **Send invoice** and **Download PDF (draft)**. 9. Choose **14 %**, tick the check, **Save draft**; read the section and the buttons. 10. Back on `UAT-AIR-DOM-NS`'s draft, **Send invoice**; open the invoice through **Sent as** and **Download PDF**. |
| **Expected** | Step 1: ON 13 % HST; NS 14 % HST; NB, NL and PE 15 % HST; AB, BC, MB, QC, SK, NT, NU and YT 5 % GST; each "As set up (owner, 2026-10-23)". Step 2: three rows, each with **Review draft invoice**. Step 3: **14 %**, **Included in the price**; "Route CA → CA: domestic, delivered in NS; 14 % included in the price."; "Tax included in the price: subtotal before tax …, HST @ 14% …, total …" (RC-UAT-24, I-11); the total equals **Accepted quote (before tax)**; the check unticked (OD-102). Step 4: matches to the cent; subtotal + tax = total. Step 5: the label turns generic, "Tax included in the price: … HST ON @ 13% …" (the table's label holds only for the rate the province filled in); the total does not move; the check clears. Step 6: saved and confirmed; the draft PDF shows each line's net with Tax **HST 14%** and the summary row **HST @ 14%**, and no "Prices include" sentence (DEC-0235). Step 7: "… delivered in NB; 15 % included in the price."; "Tax included in the price: … HST @ 15% …"; matches by hand. Step 8: "Route CA → CA: domestic, destination province unknown."; the rate reads "Choose a rate", with "The destination province of this domestic shipment is unknown, so no GST/HST rate was filled in. Choose the rate, tick the check and save."; no subtotal, tax or total; nothing can be saved without a rate, and Send and Download are disabled (stand-in R-1). Step 9: saved and confirmed; the figures appear, labelled **GST/HST** (a rate staff chose, not one filled in); Send and Download enabled. Step 10: "Invoice INV-… issued."; the invoice and its PDF show the net lines with Tax **HST 14%**, the row **HST @ 14%**, total = the draft's all-in lines, subtotal + tax = total (DEC-0235) |
| **Privacy / permission** | OD-102: staff may change the rate; the tick is required for every change |
| **Evidence to capture** | Screenshots of the table, of each draft's GST/HST section and of the summary at step 5; the hand calculations; the draft PDF of step 6 and the invoice PDF of step 10 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-29 — Settings → GST/HST rates: only Admin edits, and the rate lists follow

| | |
|---|---|
| **Role** | Operations, Read-only manager, Marketing, then Admin |
| **Prerequisites** | Fresh reset |
| **Data** | **Settings → GST/HST rates**; A2's draft for `UAT-AIR-A2-1` (if it is already sent, any open draft, or skip step 5) |
| **Steps** | 1. As Operations, open **Settings → GST/HST rates**. 2. As the read-only manager (`manager@demo.example.com`), the same. 3. As Marketing (`marketing@demo.example.com`), look for the tab. 4. As Admin, on the **ON** row type `12.5` and **Save**; then `31`; then `12`, label **HST**, **Save**. 5. As Operations, reload A2's draft and open the **GST/HST** list (choose nothing). 6. As Admin, **Settings → Audit access**: find `tax_rate.update`. 7. As Admin, set **ON** back to `13` and **Save**; re-read the table. |
| **Expected** | Step 1: the table of thirteen provinces and territories with their rate and tax, "A draft invoice for a domestic shipment fills in the destination province's rate, included in the price. Shipments with one end outside Canada are zero-rated (0 %). A change applies to drafts created from then on." and "Only Admin can change these rates."; no Save. Step 2: the same, read only. Step 3: no **GST/HST rates** tab (no finance permission). Step 4: `12.5` and `31` refused with "Enter a whole percent from 0 to 30." (stand-in R-4); `12` saved; **Last change** names the Admin and the date; "Rates staff can choose on a draft invoice:" now includes 12. Step 5: the list offers 0, 5, 12, 13, 14 and 15 %; the draft's own rate is unchanged (stand-in R-5: a change applies to drafts created afterwards; the seeded NS and NB drafts keep 14 and 15 %; a new domestic draft to ON would start at 12 %, covered by the automated suite). Step 6: one `tax_rate.update` row, ON, from 13 to 12, naming the Admin. Step 7: 13 again, and a second audit row |
| **Privacy / permission** | OD-102: Admin (`settings:manage`) edits; `financial:read` sees |
| **Evidence to capture** | Screenshots of each role's view, the refusal and the saved row; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-30 — Download PDF (draft) waits for the GST/HST check, like Send

| | |
|---|---|
| **Role** | Operations, then Read-only manager |
| **Prerequisites** | Fresh reset; `UAT-OWN-18` may be done; A2's draft not yet saved with the check (before `UAT-OWN-19`, `-09` step 6 and `-12`) |
| **Data** | A2's draft for `UAT-AIR-A2-1` |
| **Steps** | 1. As Operations, open A2's draft; change nothing; look at **Download PDF (draft)** and **Send invoice** and read the message above them. 2. As the read-only manager, open the same draft (**Finance → Invoices → Accepted, not invoiced**, or paste the draft's address from the Operations session) and look at the same place. 3. As Operations, run `UAT-OWN-19` (its step 2 ticks **I have checked the GST/HST on this invoice** and saves, changing nothing else). 4. Back on the draft, press **Download PDF (draft)** and open the file. |
| **Expected** | Step 1: both disabled, with "The GST/HST of the saved draft is not confirmed: tick the check and save before sending or downloading." (DEC-0229). Step 2: **Download PDF (draft)** disabled, with the neutral "The GST/HST of this draft is not yet confirmed by finance staff, so it cannot be downloaded or sent yet." instead of the tick instruction; no **Send invoice** for this role. Step 3: "GST/HST checked for this revision by …"; both buttons enabled. Step 4: the PDF downloads, with the **DRAFT** watermark. The server refuses a download of an unconfirmed revision too (422 `tax_unconfirmed`; covered by the automated suite) |
| **Privacy / permission** | No draft document leaves the system before staff confirm its GST/HST |
| **Evidence to capture** | Screenshots of steps 1 and 2; the downloaded PDF |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-31 — A payment's received date stays the date entered

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset; the PC's clock on Toronto time. Read the order note above: this case records CAD 5.00 on `INV-000003` |
| **Data** | `INV-000003` (A3, CAD 90.00, CAD 50.00 paid, balance CAD 40.00; issued in the current month) |
| **Steps** | 1. Open `INV-000003` and **Record payment**: CAD **5.00**, **Interac e-Transfer**, reference `UAT-DATE-01`, **Received on** today's date (the form's default; note it). 2. Read the new row in **Payments and receipts**. 3. **Print receipt** for it and read **Received on**. 4. **Record payment** again: CAD 5.00 with **Received on** set to tomorrow's date. |
| **Expected** | Step 1: recorded. Steps 2 and 3: the date is **exactly the date entered**, never the day before (the fault reported in RC-UAT-19: 20 Sep entered, 19 Sep shown; DEC-0229). Step 4: refused, "A date cannot be in the future."; nothing recorded. The month the payment counts in (and the M+7 lock) follows the date entered; a date entered on a Toronto evening, and a date sent with a time-zone offset, keep their calendar day (stand-in R-9; the screen sends a plain date, the offset case is covered by the automated suite) |
| **Privacy / permission** | Payments are audited (OD-68) |
| **Evidence to capture** | Screenshots of the payments list and the receipt, with the date you entered; the refusal at step 4 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-32 — Costume jewellery: both values on Add fee, and the customer pays exactly the price

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset; `UAT-AWB-OPEN` still open (before `UAT-WSQ-05`) |
| **Data** | `UAT-AWB-OPEN`; A4's `UAT-AIR-A4-1`, item `Cà phê rang xay (UAT)` |
| **Steps** | 1. On A4's `Cà phê rang xay (UAT)` **Add fee**: **Hàng mỹ ký (trang sức giả)**; type `300000` in **Vendor cost (VND)** and leave **Customer price (CAD)** empty; add it. 2. Read the fee line. 3. Type `30.00` in **Customer price (CAD)** and **Save**. 4. **Re-price**, **Confirm selling rate** (box empty). 5. Change **Customer price (CAD)** to `32.50` and **Save**; read the Quote panel. 6. **Re-price**, **Confirm selling rate**, **Finalise quote**, **Print customer quote**. |
| **Expected** | Step 2: "Customer price (CAD) needed" (OD-103). Step 4: the line's charge is exactly **CAD 30.00**; the **Vendor cost** panel shows 300,000 VND at the buy rate; the rate is confirmed. Step 5: changing the customer price revokes the rate confirmation like any price input: the quote asks for **Confirm selling rate** again. Step 6: finalised; the printed quote shows the line at exactly **CAD 32.50** (no markup, stand-in R-7), and no VND cost, exchange rate, markup or vendor name |
| **Privacy / permission** | The VND cost is staff-only; the customer reads only the CAD price |
| **Evidence to capture** | Screenshots of steps 2, 4 and 5; the printed quote |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-33 — The final delivery leg offers the vendor; each leg shows its generic tracking name

| | |
|---|---|
| **Role** | Operations, then Customer (A2), then anyone signed out |
| **Prerequisites** | Fresh reset (`UAT-AIR-A2-1` has no transport leg). Do not open any carrier link (`ENVIRONMENT.md` §8) |
| **Data** | A2's `UAT-AIR-A2-1` on `UAT-AWB-TRANSIT`; `emily.air@example.com` |
| **Steps** | 1. As Operations, open the shipment with booking reference `UAT-AIR-A2-1`; note its Solaris ID. 2. **Transport legs → Add leg**: **Leg type** *Final delivery*; open **Provider / carrier** and read the list. 3. Pick `Kango Logistics`, tick **This leg delivers to the final recipient**, fill whatever else the form requires; save. 4. **Add leg**: **Leg type** *Consolidation / linehaul*; open **Provider / carrier**; pick `Kango Logistics`; save. 5. Read the two legs in **Transport legs**. 6. On the final delivery leg **Add carrier reference**: **Carrier** *UPS*, **Tracking number** `1ZUAT0000000000002`, **Tracking source** *External link only*, **Public carrier link** `https://www.ups.com/track?tracknum=1ZUAT0000000000002`; save. 7. As A2, open **My shipments** and the shipment; read the link; switch to Vietnamese. 8. In a private window open <http://localhost:5173/track> for the Solaris ID, in English and in Vietnamese. |
| **Expected** | Step 2: the list starts with **Kango Logistics**, then the carriers (UPS, FedEx, Purolator, Canada Post, DHL, USPS, Viettel Post, Vietnam Post, Solaris Express, Other) — the vendor is offered on the final delivery leg (DEC-0229). Step 3: saved. Step 4: the same list, vendor first. Step 5: each leg carries a chip: **Last Mile Tracking** on *Final delivery*, **Master Tracking** on *Consolidation / linehaul*; staff still read the provider `Kango Logistics`. Step 7: "Last Mile Tracking: open the carrier's tracking page" / "Theo dõi chặng cuối: mở trang theo dõi của hãng vận chuyển" (approved, OD-104); no "Kango", no "UPS" as a label. Step 8: "Last Mile Tracking: open the tracking page" / "Theo dõi chặng cuối: mở trang theo dõi"; no vendor or carrier name. The staff screens have no language switch, so the staff chip is read in English; its Vietnamese text ("Theo dõi chặng chính" / "Theo dõi chặng cuối") is the same as the customer's and is checked by the automated i18n tests |
| **Privacy / permission** | OD-84, OD-92, OD-104: S1 if any customer-facing page names the vendor |
| **Evidence to capture** | Screenshots of the provider list, the two staff legs, the account page in both languages and the public page |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-34 — Settings → Tariffs shows the 39 import warnings and the 3 confirmed price steps

| | |
|---|---|
| **Role** | Operations, then Marketing |
| **Prerequisites** | Fresh reset |
| **Data** | The active version "Kango 2026-10-12 (sanitized demo)" |
| **Steps** | 1. As Operations, open **Settings → Tariffs**. 2. In **Tariff versions**, press **View** on the **Active** row. 3. Read the card **Import warnings (…) · TRF-…** beneath: the count, **Warnings by kind** and the numbered list. 4. Press **Next warnings**, then **Previous warnings**. 5. Read **Confirmed price steps (…)** at the foot of the card. 6. As Marketing, look for **Settings → Tariffs**. |
| **Expected** | Step 3: **Import warnings (39)**; by kind: `express_zone_below_ground` 35, `trucking_pallet_fees_not_imported` 2, `duplicate_fsa` 1, `beyond_code_without_rate` 1; "Showing 1-25 of 39."; each warning names its code, sheet and cell (in English, the importer's words); none is about a price falling with weight. Step 4: "Showing 26-39 of 39.", then back. Step 5: **Confirmed price steps (3)**: HCM-AIR-CAD!F39, HN-AIR-CAD!F38 and HN-AIR-CAD!G38, each **Confirmed**; they are not counted among the 39 (OD-81, DEC-0222). Step 6: not available (no tariff permission) |
| **Privacy / permission** | Tariffs and their warnings need the tariff permission (`tariff:read`) |
| **Evidence to capture** | Screenshots of the card at steps 3 to 5 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OWN-35 — The wording kept: "Tổng cộng" with the GST/HST line, and "Ghi chú từ Solaris Express"

| | |
|---|---|
| **Role** | Customer (A1) |
| **Prerequisites** | Fresh reset |
| **Data** | `trang.air@example.com`; the quote for `UAT-AIR-A1-2`; the shipment `UAT-AIR-A1-1` (its departure update carries staff's own wording, "Chuyến bay UAT-101 …") |
| **Steps** | 1. Sign in as A1; open **Báo giá** and read the column heads. 2. Open the quote for `UAT-AIR-A1-2`; read the total row and the sentence beneath. 3. Switch to English and read them again; switch back. 4. Open **Lô hàng của tôi** and the shipment with booking reference `UAT-AIR-A1-1`; find the departure update and staff's wording beneath it. 5. Right-click staff's wording and choose **Inspect** (or use a screen reader): read the label before it. Switch to English and repeat. |
| **Expected** | Steps 1 and 2: the total reads **Tổng cộng** (OD-108, kept), and beneath it "Thuế suất 0 (0 %)": `UAT-AIR-A1-2` goes Vietnam → Canada, international, zero-rated. **Changed in RC-UAT-21** (OD-109 stand-in, pending Ben; DEC-0232): the RC-UAT-20 note "Thuế, nếu có, sẽ được tính trên hóa đơn." no longer appears; a domestic quote would read "Giá đã bao gồm HST n %" at the destination province's rate (`UAT-BLD-14`). Step 3: **Total** and "Zero-rated (0 %)"; no "Taxes, if any, are added on the invoice." Step 5: the label, hidden on screen and read aloud by a screen reader, is **Ghi chú từ Solaris Express** / **Note from Solaris Express** (OD-108) |
| **Privacy / permission** | Customer-facing wording; no cost, tax amount or vendor name (the GST/HST line names a rate only) |
| **Evidence to capture** | Screenshots of the quote in both languages and of the inspected label |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Build of 2026-10-24 (RC-UAT-21) — `UAT-BLD-*`

Ben's direction of 2026-10-24 (OD-110): build every remaining feature now, with safe
stand-ins, each recorded as an open question (`docs/b2c_merge/19_OWNER_QUESTIONS.md` §0000;
record `docs/b2c_merge/25_BUILD_RC21_RECORD.md`; DEC-0230 to DEC-0233). Shipment import and
the legacy history baseline (`-01` to `-07`, DEC-0230), the customer's and the staff member's
own password, and the Admin's change of a customer's sign-in email (`-08` to `-11`; customers
cannot change it since RC-UAT-25, DEC-0243; `-10` is withdrawn), Admin reinstatement of a
deactivated account (`-12`, `-13`, DEC-0231), the quote tax wording (`-14`, the OD-109
stand-in, DEC-0232), Admin soft delete of old quote versions (`-15`, `-16`) and the retention
settings (`-17`, DEC-0233). Each stand-in is what the case tests; none blocks a case.

**Nothing new is seeded; the cases make their own data.** The import cases start from the
templates in `artifacts\sample-imports\` (`shipment-import-template.csv`,
`legacy-history-template.csv`; the same files download from each import page). Copy them
**outside the repository** (for example to the Desktop), edit them in Notepad or in Excel
(**Save as → CSV UTF-8**, never plain "CSV", which loses the Vietnamese diacritics), and
replace the template's customer IDs with the seeded air customers' own: on **Customers**,
search `trang.air` (A1), `khoa.air` (A3) and `lan.air` (A4) and note each **Solaris
customer ID** (`STCA-…`). Dates are `YYYY-MM-DD` only.

**New passwords.** Where a case changes a password, choose a new one of at least 12
characters yourself and keep it to yourself: **never** write a password into **Evidence
obtained**, a screenshot or a defect report.

**Order.** `-01` to `-07` and `-14` to `-17` need only a fresh reset (`-15` needs
`UAT-AWB-OPEN` **still open**, before `UAT-WSQ-05`; step 6 of `-16` uses `UAT-QAC-03` if it was
run). The account cases change seeded sign-in details, so run `-08` to `-13` **last, in
order**, and reset afterwards: `-08` changes A1's password; `-09` changes A2's sign-in email
from the staff account screen (as Admin; `-10` is withdrawn); `-11` changes the Operations password; `-12` leaves A2
deactivated for good; `-13` returns A1 to pending approval. A fresh reset restores all of them
(passwords in `ENVIRONMENT.md` §2). **Retention: dry run only.** Never turn retention
deletion on during UAT: it needs the owner's written approval and the periods are undecided
(OD-01, OD-36). `-17` says exactly what to type and what not to.

### UAT-BLD-01 — Import type navigation and the two new templates

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset |
| **Data** | <http://localhost:5173/customers/import>, `/customers/import/shipments`, `/customers/import/legacy`; `artifacts\sample-imports\` |
| **Steps** | 1. As Admin open **Customers** → the import page (`/customers/import`); read the **Import type** navigation; choose **Shipments**, then **Legacy history**, then **Customers**. 2. On **Shipments** and on **Legacy history** read the title, the subtitle and **CSV format**, then press **Download template**. 3. Open each downloaded file in Notepad and compare it with the file of the same name in `artifacts\sample-imports\`. 4. As Operations open the same three addresses. |
| **Expected** | Step 1: **Import type** with **Customers**, **Shipments** and **Legacy history** on all three pages. Step 2: "Import shipments" — "Air shipments for existing customers: dry run first, then import."; "Import legacy history" — "Past shipments and their milestones, kept as read-only history for staff."; each lists its columns, the required ones marked, and the limits "… rows and … MiB per file, as for the customer import." (5,000 rows, 2 MiB; A-11). Step 3: each download is the template in `artifacts\sample-imports\`; the Vietnamese values (Trần Thị Mẫu, Quà tặng gia đình (sample), Áo dài, Cà phê, Quà Tết (sample)) keep their diacritics; dates read `YYYY-MM-DD`. Step 4: the navigation is there, but no **Download template** and no file input: "Your role cannot run an import dry run."; on **Legacy history** the **Legacy shipments** list is still shown, empty ("No legacy shipments") |
| **Privacy / permission** | Importing is Admin's alone (`import:*`, DEC-0082; stand-in A-10); reading legacy records needs `shipment:read` |
| **Evidence to capture** | Screenshots of the navigation and both new pages as Admin and as Operations; the two downloaded files |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-02 — Shipment dry run: each bad row is named, and nothing is written

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Fresh reset; A3's and A4's Solaris customer IDs noted (see the group's introduction) |
| **Data** | `bld02.csv`: a copy of `shipment-import-template.csv` with (a) `customer_ref` of `SAMPLE-SHP-0001` set to **A3's** ID and of `SAMPLE-SHP-0002` to **A4's**; (b) a new last column `transport_mode`, empty on those two rows; (c) seven rows copied from `SAMPLE-SHP-0001`, each with `package_dimensions_cm` emptied, a new `external_reference` and **one** change: `UAT-BLD-ERR-1` `transport_mode` = `ocean`; `UAT-BLD-ERR-2` `customer_ref` = `STCA-999999`; `UAT-BLD-ERR-3` `recipient_country_code` = `VN`; `UAT-BLD-ERR-4` `package_weights_kg` = `600`; `UAT-BLD-ERR-5` `recipient_name` empty; `UAT-BLD-ERR-6` `booking_date` = `01/02/2024`; `UAT-BLD-ERR-7` `external_reference` = `=UAT-BLD-ERR-7` |
| **Steps** | 1. Open **Shipments** and note the total; search `PO-SAMPLE-1`. 2. **Import type → Shipments**, **Choose a CSV file**: `bld02.csv`. 3. Read the **Dry-run report**: the notes, the counts, and each row's **Dry-run result** and **Problems**. 4. Re-read the **Shipments** total; open **Settings → Customer notifications**; list the newest files in `data\uat\account_mail`. |
| **Expected** | Step 1: `PO-SAMPLE-1` finds nothing. Step 3: "Dry run only. Nothing has been imported."; the notes "Dry run only: no shipment, package, item or import batch has been created.", "An import never creates a quote, an invoice, an email or a milestone notification." and "Only air shipments are imported. A customer is never created: every row must name an existing customer."; **Ready to import** 2 (the two sample rows) and **Cannot be imported** 7, each naming its column: ERR-1 "Only air shipments are imported in this release." (A-5); ERR-2 "No existing customer has this reference. An import never creates a customer." (A-2); ERR-3 "The route, direction or countries do not match." (a Vietnam recipient on VCA); ERR-4 "A package is heavier than 500 kg. Weights are in kilograms." (A-11); ERR-5 "A required value is missing."; ERR-6 "Not a date this import accepts. Use YYYY-MM-DD." (a slash date is never guessed); ERR-7 "Starts with a character a spreadsheet treats as a formula." (A-12). The two ready rows stay ready; the import button reads **Import 2 row(s)** (do not press it). Step 4: the total is unchanged; no new notification and no new captured file |
| **Privacy / permission** | A dry run writes no business record (DEC-0230); the report shows the file's own values to the Admin who uploaded it, nobody else |
| **Evidence to capture** | Screenshot of the whole report; `bld02.csv` |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-03 — Import only after a matching dry run

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | `UAT-BLD-02` done |
| **Data** | `bld03.csv`: `bld02.csv` without the seven `UAT-BLD-ERR-*` rows (the two sample rows: A3's draft with two packages and two items, A4's confirmed one) |
| **Steps** | 1. **Start over**; dry run `bld03.csv`; read the report. 2. Leave the page as it is; open `bld03.csv` in Notepad, change `PO-SAMPLE-1` to `PO-SAMPLE-1X`, save. 3. Back on the page press **Import 2 row(s)** and confirm. 4. **Start over**; dry run the saved file again; **Import 2 row(s)**; read the confirmation; **Import now**. 5. Read the result. 6. On **Shipments** search `PO-SAMPLE-1X` and open it; then find A4's new shipment (recipient Lê Văn Mẫu, Vancouver) and open it. 7. **Settings → Customer notifications**; the newest files in `data\uat\account_mail`; **Settings → Audit access**: the rows `shipment.import_dry_run` and `shipment.import_commit`. |
| **Expected** | Step 1: **Ready to import** 2. Step 3: "The import did not run": "This file is not the one that was dry-run. Run the dry run again and review the result before importing. Nothing has been imported." (A-3); nothing created. If the browser reports instead that it cannot read the changed file, nothing is imported either: record that wording as an observation (S5). Step 4: "Import these rows?" with "2 shipment(s) will be created. No quote, invoice, email or milestone notification is created." Step 5: "Import complete" — "Batch IMP-… is recorded with the outcome of every row."; both rows **Created**, each linked to its record. Step 6: A3's shipment is a **draft** with booking reference `PO-SAMPLE-1X`, two packages (12.5 kg 40×30×30, 8 kg 30×30×20), items Áo dài 2 pieces CAD 80 and Cà phê 3 boxes CAD 30, the internal note visible to staff only; A4's is **confirmed**, with a Solaris ID (`SX-VCA-…`), booked on 2026-10-01, one 2 kg package. Neither has a quote, an invoice or a milestone. Step 7: no new notification and no new captured file (A-4); the two audit rows carry counts and the file's digest, never a name, address or other cell value |
| **Privacy / permission** | An import creates no quote, invoice, email or notification (A-4); its audit holds no cell value |
| **Evidence to capture** | Screenshots of the refusal (step 3), the confirmation, the result and the two shipments; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-04 — Duplicates are refused, and a second import needs a new dry run

| | |
|---|---|
| **Role** | Admin, in Edge or Chrome |
| **Prerequisites** | `UAT-BLD-03` done |
| **Data** | `bld03.csv` as saved in `UAT-BLD-03`; `bld04.csv`: a copy of `bld03.csv` keeping only A3's row, then that row twice more, both with `external_reference` `UAT-BLD-DUP-1` and `booking_reference` `PO-BLD-DUP` (the original `SAMPLE-SHP-0001` row deleted) |
| **Steps** | 1. Press **F12** and open the **Network** tab. On the shipment import page (**Import another file** if the result is still shown) dry run `bld04.csv`; read the two rows. 2. **Import 1 row(s)**, **Import now**. 3. In **Network**, right-click the request whose name ends `commit` and choose **Replay XHR**; open the replayed request's **Response**. 4. On **Shipments** search `PO-BLD-DUP` and count the results. 5. **Import another file**: dry run `bld03.csv` again. |
| **Expected** | Step 1: the first row **Ready to import**; the second refused with "This reference repeats an earlier row of the same file." Step 2: one row **Created**; the repeated row not imported. Step 3: refused (409): "There is no unused matching dry run for this file (each dry run allows one import). Run the dry run again, review the report, and then import. Nothing has been imported." (A-3: a commit consumes its dry run). Step 4: exactly **one** shipment. Step 5: both rows **Duplicates (refused)**, each with "Already imported. Duplicates are refused." (A-13); **Nothing to import** |
| **Privacy / permission** | An import never creates the same shipment twice (S1 if it does: README, "Severity") |
| **Evidence to capture** | Screenshots of steps 1, 3 (the response), 4 and 5 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-05 — Legacy history: a dry run with a cutoff date, then the baseline

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Fresh reset, or after `UAT-BLD-04`; A1's Solaris customer ID noted |
| **Data** | `bld05.csv`: a copy of `legacy-history-template.csv` with `customer_ref` set to **A1's** ID on both sample rows, and four rows added for A1 (empty cells elsewhere): `UAT-OLD-LATE` booked `2025-06-01`, `delivered`, `delivered_on` `2025-06-20`; `UAT-OLD-ORDER` booked `2024-04-01`, `delivered`, `departed_on` `2024-04-10`, `arrived_on` `2024-04-05`, `delivered_on` `2024-04-12`; `UAT-OLD-CONFLICT` booked `2024-07-01`, `delivered`, `delivered_on` `2024-07-10`, `returned_on` `2024-07-12`; `UAT-OLD-SLASH` booked `01/02/2024`, `lost`. `bld05b.csv`: `bld05.csv` without the four `UAT-OLD-*` rows |
| **Steps** | 1. **Import type → Legacy history**; **Baseline cutoff date** `2024-12-31`; dry run `bld05.csv`. 2. Read the notes and every row. 3. **Start over**; cutoff `2024-12-31`; dry run `bld05b.csv`; **Import 2 row(s)**; read the confirmation; **Import now**. 4. Read the result, **Legacy baselines** and **Legacy shipments**. |
| **Expected** | Step 2: "Dry run only: no legacy record and no baseline has been created."; the notes that legacy shipments are read-only history that never notify, are never quoted, invoiced, locked or expired, and stay out of every operational queue and finance report, and that a re-run is safe. **Ready to import** 2 (the samples); `UAT-OLD-LATE` "Booked after the baseline cutoff date."; `UAT-OLD-ORDER` "Milestones must follow the journey order."; `UAT-OLD-CONFLICT` "This date contradicts the final status."; `UAT-OLD-SLASH` "Not a date this import accepts. Use YYYY-MM-DD." Step 3: "2 historical shipment(s) will be added to a new baseline. They never notify a customer and never appear in operational or finance lists. The whole baseline can be voided later." Step 4: "Import complete", batch `IMP-…`; **Legacy baselines**: one row, **Active**; **Legacy shipments**: `SAMPLE-OLD-0001` (booked 2024-03-01, **Delivered**) and `SAMPLE-OLD-0002` (2024-05-02, **Cancelled**), each with the **Legacy** badge and A1 as the customer |
| **Privacy / permission** | Legacy records go to their own tables, never to shipments (DEC-0230; A-7, A-8, A-14) |
| **Evidence to capture** | Screenshots of the dry-run report, the confirmation and both lists |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-06 — Legacy records are staff-only, and stay out of every list and the customer's account

| | |
|---|---|
| **Role** | Admin, Operations, Read-only manager, then Customer (A1) |
| **Prerequisites** | `UAT-BLD-05` done |
| **Data** | `SAMPLE-OLD-0001`, `SAMPLE-OLD-0002`; `bld05b.csv`; `trang.air@example.com` |
| **Steps** | 1. As Admin, on **Legacy shipments** search `SAMPLE-OLD`; read the note above the list; follow the customer link. 2. On A1's customer profile read the shipments and the lifetime figures. 3. Search `SAMPLE-OLD` on **Shipments**; look through the **Dashboard**, **Finance → Invoices** (and **Accepted, not invoiced**), **Receivables** and **Profitability**. 4. As Operations, then as the read-only manager, open `/customers/import/legacy`. 5. As A1, sign in to the Customer Account; open **Lô hàng của tôi** and search `SAMPLE-OLD`. 6. As Admin, **Settings → Customer notifications**. 7. Dry run `bld05b.csv` again with the same cutoff date. |
| **Expected** | Step 1: both records, **Legacy** badge, "Read-only history. Legacy shipments are staff-only and are never quoted, invoiced or notified."; nothing to edit. Step 2: neither record among A1's shipments; the lifetime figures, lifecycle status and repeat-customer share are as before the import (A-7). Step 3: found nowhere. Step 4: "Your role cannot run an import dry run."; no **Legacy baselines** and no **Void baseline**; the **Legacy shipments** list is readable. Step 5: no legacy record anywhere in A1's account (A-7). Step 6: nothing new. Step 7: both rows **Already in a baseline**; **Nothing to import** (A-9: matched, never duplicated or overwritten) |
| **Privacy / permission** | A-7: staff-only; S1 if a legacy record reaches the Customer Account |
| **Evidence to capture** | Screenshots of steps 1, 2, 4, 5 and 7 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-07 — Void a legacy baseline, then import the same history again

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | `UAT-BLD-05` done (and `-06`, which reads the live records) |
| **Data** | The baseline `IMP-…` of `UAT-BLD-05`; `bld05b.csv` |
| **Steps** | 1. **Legacy baselines** → **Void baseline**; read the dialog; type the reason `void` (four characters) and try to confirm. 2. Type `Wrong file (UAT)` and **Void baseline**. 3. Read **Legacy baselines** and **Legacy shipments**; tick **Include voided records**. 4. **Settings → Audit access**: find `legacy_history.baseline_void`. 5. Dry run `bld05b.csv` (cutoff `2024-12-31`) and import it. |
| **Expected** | Step 1: "Every legacy record this baseline created is marked voided and disappears from the lists. Nothing is deleted, and the same history can be imported again."; the hint "At least 5 characters. Recorded in the audit log."; a four-character reason is refused. Step 2: the baseline reads **Voided**. Step 3: the two records are gone from the list; with **Include voided records** they are back, flagged voided. Step 4: one row naming the Admin and the baseline, with the reason; no record content. Step 5: both rows **Ready to import** (not "Already in a baseline"); a second baseline, **Active**; the list shows the two live records again, and the voided two only with **Include voided records** (A-9) |
| **Privacy / permission** | A void is soft and audited; nothing is deleted (A-9) |
| **Evidence to capture** | Screenshots of each step; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-08 — A customer changes their password, in Vietnamese

| | |
|---|---|
| **Role** | Customer (A1) |
| **Prerequisites** | Run with the account cases, last (see the group's introduction). Two browsers (one private window) |
| **Data** | `trang.air@example.com`, password in `ENVIRONMENT.md` §2; a new password of your own (12 characters or more) |
| **Steps** | 1. Sign in as A1 in both browsers. 2. In browser 1 open **Đăng nhập và bảo mật** from the navigation. 3. Under **Đổi mật khẩu** type a wrong **Mật khẩu hiện tại** and your new password twice; submit. 4. With the right current password, type a 10-character new password twice. 5. Type two different new passwords. 6. Type `password1234` twice. 7. Type the current password as the new one, twice. 8. Type your new password twice; submit. 9. In browser 2 click any link. 10. In browser 1 sign out; sign in with the old password, then with the new one. 11. Open the newest file in `data\uat\account_mail`. 12. As Admin, **Settings → Audit access**: find `customer_account.password_changed` and `customer_account.password_change_refused`. |
| **Expected** | Step 2: **Đăng nhập và bảo mật**, "Đổi mật khẩu của bạn. Để đổi email đăng nhập, hãy liên hệ Solaris Express.", with **Đổi mật khẩu** and **Email đăng nhập của bạn**; **Email đăng nhập** reads `trang.air@example.com`, and "Chỉ Solaris Express mới có thể đổi email đăng nhập của bạn…" (RC-UAT-25, DEC-0243). Step 3: "Mật khẩu hiện tại không đúng." beside the field. Step 4: "Hãy dùng ít nhất 12 ký tự." Step 5: "Hai mật khẩu không khớp nhau." Step 6: "Hãy chọn một mật khẩu ít phổ biến hơn." Step 7: "Hãy chọn mật khẩu mới khác với mật khẩu hiện tại." Step 8: "Đã đổi mật khẩu." — "Bạn vẫn đăng nhập trên trình duyệt này; mọi phiên đăng nhập khác đã được đăng xuất." (B-2). Step 9: browser 2 is signed out. Step 10: the old password is refused with the usual sentence; the new one signs in. Wrong current passwords did not lock the account (B-7). Step 11: a Vietnamese notice whose file name contains `password_changed_here`, saying the Solaris Express password was changed; no password, no sign-in link. Step 12: the change (with the number of sessions ended) and the refusals by reason code; no password anywhere |
| **Privacy / permission** | Every other session ends; the password never appears in mail, screen or audit (DEC-0231) |
| **Evidence to capture** | Screenshots of each refusal and of step 8; the captured file's name and body; the audit rows. No password in any of them |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-09 — The customer cannot change the sign-in email; an Admin changes it

| | |
|---|---|
| **Role** | Customer (A2, English), then Admin, then Operations |
| **Prerequisites** | Run with the account cases, after `UAT-BLD-08` (see the group's introduction); two browsers (one private window). Rewritten in RC-UAT-25 (DEC-0243): customers no longer change the sign-in email |
| **Data** | `emily.air@example.com`, password in `ENVIRONMENT.md` §2; the new address `emily.new@example.com`; A1's address `trang.air@example.com` (in use) |
| **Steps** | 1. Sign in as A2 in both browsers; in browser 1 open **Sign-in and security**. 2. Switch to Tiếng Việt and read the page again; back to English. 3. As Admin open **Customer accounts** → A2's account. 4. Under **Change sign-in email** type `trang.air@example.com`, reason **Customer asked for it**, **Change sign-in email**, **Yes, change it**. 5. Type `emily.new@example.com`, reason **Customer lost access to the old mailbox**, a note; **Change sign-in email**; read the dialog; **Yes, change it**. 6. In both A2 browsers click any link. 7. Sign in with `emily.air@example.com`, then with `emily.new@example.com` (same password). 8. List the newest files in `data\uat\account_mail`. 9. As Operations open A2's account, then the customer Emily Carter. 10. As Admin, **Settings → Audit access**: `customer_account.sign_in_email_changed_by_staff`. |
| **Expected** | Step 1: **Change your password** and **Your sign-in email** (`emily.air@example.com`) with "Only Solaris Express can change your sign-in email. Contact us and we will change it for you."; no new-email field, no link button. Step 2: **Email đăng nhập của bạn**, "Chỉ Solaris Express mới có thể đổi email đăng nhập của bạn. Hãy liên hệ với chúng tôi để được đổi." Step 4: refused, "That address is already the sign-in email of another Customer Account."; nothing changes. Step 5: the dialog reads "From emily.air@example.com to emily.new@example.com…"; then "The sign-in email has been changed. The customer must sign in again with the new address."; **Login address** `emily.new@example.com`. Step 6: both signed out (RC25-B5). Step 7: the old address is refused with the usual sentence; the new one signs in. Step 8: to `emily.air`, the notice that the sign-in email changed (no address, no link); to `emily.new`, "This is now your Solaris Express sign-in email" with the sign-in link (RC25-B4); no `email_change_confirm` file. Step 9: Operations sees no **Change sign-in email** (RC25-B3); the customer's email is `emily.new@example.com`. Step 10: one row with the reason code, the number of sessions ended and keyed `address_key` values; no address, no note (RC25-B6) |
| **Privacy / permission** | Admin only (`customer_account:deactivate`); the customer surface never says whether an address is known; no address in the audit (DEC-0243) |
| **Evidence to capture** | Screenshots of steps 1, 2, 4, 5 and 9; the two captured files' names and bodies; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-10 — Withdrawn in RC-UAT-25: the customer's own email change (an address in use, cancel, a password change)

| | |
|---|---|
| **Role** | None: withdrawn in RC-UAT-25 (item 2, DEC-0243). Do not run; record `Result` as "Withdrawn" only if the sign-off sheet asks for every id |
| **Prerequisites** | None |
| **Steps** | None. Withdrawn in RC-UAT-25 (item 2): customers no longer ask for an email change, so there is no answer to compare, nothing to cancel and no pending change for a password change to cancel. |
| **Expected** | Nothing to observe. The no-enumeration rule is covered by `UAT-BLD-09` step 4 (staff sentence) and the customer's single refusal; an old link is `UAT-BLD-29` |
| **Privacy / permission** | Covered by `UAT-BLD-09` and `UAT-BLD-29` |
| **Evidence to capture** | None: the case is withdrawn |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-11 — A staff member changes their own password

| | |
|---|---|
| **Role** | Operations, then Admin |
| **Prerequisites** | Run with the account cases, last. Two browsers, both signed in as `ops@demo.example.com` |
| **Data** | The Operations password (`ENVIRONMENT.md` §2); a new one of your own (12 characters or more) |
| **Steps** | 1. In browser 1 open the account menu → **Change password** (`/my-password`). 2. Type a wrong **Current password** and the new password twice; submit. 3. With the right current password, type a 10-character new one twice. 4. Type two different new passwords. 5. Type the current password as the new one, twice. 6. Type the new password twice; **Change password**. 7. In browser 2 click any link. 8. In browser 1 sign out; sign in with the old password, then the new one. 9. List the newest files in `data\uat\account_mail`. 10. As Admin, **Settings → Audit access**: `auth.password_change` and `auth.password_change_refused`. |
| **Expected** | Step 1: "Change your password" — "You stay signed in here; every other session of yours is signed out."; "At least 12 characters." Step 2: refused beside **Current password**. Step 3: "Use at least 12 characters for a staff password." Step 4: "The two passwords do not match." Step 5: refused: the new password must differ. Step 6: "Password changed. Every other session of yours was signed out."; browser 1 stays signed in. Step 7: browser 2 is back at the sign-in page. Step 8: the old password is refused; the new one works. Step 9: nothing new: staff get no email (B-1). Step 10: the change and each refusal by reason code; no password |
| **Privacy / permission** | Every other session of that user ends; the password never appears anywhere (DEC-0231) |
| **Evidence to capture** | Screenshots of each step; the audit rows. No password in any of them |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-12 — Admin reinstates a deactivated account

| | |
|---|---|
| **Role** | Admin, Operations, Customer (A2) |
| **Prerequisites** | Run with the account cases, last; A2 signed in in one browser (with the address current after `-09`, if run) |
| **Data** | A2's account (Emily Carter, `CA-000002`) |
| **Steps** | 1. As Admin, **Customer accounts** → A2's account → **Deactivate this account**: read the hint; reason **Customer asked for it**; read the confirmation; **Yes, deactivate**. 2. In A2's browser click any link, then try to sign in. 3. As Operations, open **Customer accounts** and A2's account. 4. As Admin, **Customer accounts** → **Deactivated accounts**; open A2's. 5. In **Reinstate account**: reason **Deactivated in error**, note `UAT reinstatement test`; **Reinstate account**. 6. Read the account's status and linked customer. 7. Open the newest file in `data\uat\account_mail`. 8. As A2, reload the old browser; then sign in again and open **Quotes** and **My shipments**. 9. As Admin, **Settings → Audit access**: `customer_account.reactivate`. 10. Deactivate A2 again, reason **Privacy request**; open **Deactivated accounts** and the account. |
| **Expected** | Step 1: the hint "Admin only. Every session ends, every outstanding link stops working, and the person cannot sign in until an Admin reinstates the account (not possible after a privacy request). The record and its history are kept; nothing is deleted."; the confirmation "Only an Admin can reinstate it later, and never after a privacy request. …"; the word "permanent" appears nowhere. Step 2: signed out; sign-in refused with the usual sentence. Step 3: no **Deactivated accounts** list and no reinstate control. Step 4: "Admin only. Open an account to reinstate it."; A2 marked **Can be reinstated**. Step 5: "The account has been reinstated. The customer must sign in again." Step 6: **active**, still linked to Emily Carter. Step 7: an English notice (file name containing `reinstated`) that the account is available. Step 8: the old session stays ended; signing in works; A2's quotes and shipments are back. Step 9: one row with the reason code; the note is not in it. Step 10: A2 marked **Cannot be reinstated**; the account says "This account cannot be reinstated (deactivated on a privacy request, or an application that was declined)." and offers no reinstate control (B-5). A2 stays deactivated until the next reset |
| **Privacy / permission** | Admin only (`customer_account:deactivate`); a privacy-request deactivation is final (B-5) |
| **Evidence to capture** | Screenshots of steps 1, 3, 4, 6, 8 and 10; the captured file; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-13 — Reinstating after a merge returns the account to pending approval

| | |
|---|---|
| **Role** | Admin, then Customer (A1) |
| **Prerequisites** | Run last; a fresh reset afterwards |
| **Data** | A1's account (`CA-000001`) and customer Phạm Thị Thu Trang (with the seeded shipments); a throwaway customer created in step 2 |
| **Steps** | 1. As Admin, deactivate A1's account (reason **Customer asked for it**). 2. **Customers** → new customer: name `Phạm Thị Thu Trang (UAT merge)`, the **same phone** as A1's customer (read it on A1's profile), email `trang.merge@example.com`; save (proceed past the duplicate panel). 3. Open A1's customer, compare it with the new record and **Merge**: **Keep this record** (A1's), type the other's ID to confirm. 4. **Customer accounts → Deactivated accounts** → A1 → **Reinstate account**, reason **Deactivated in error**. 5. Read the account's status and linked customer. 6. As A1, sign in; open **Lô hàng của tôi** and **Báo giá**. 7. As Admin, **Settings → Audit access**: `customer_account.unlink` and `customer_account.reactivate`. |
| **Expected** | Step 3: the new record is merged into A1's, whose ID survives. Step 5: **pending approval**, **not active**, and no linked customer: the reinstatement ended the link because A1's customer took part in a merge after the deactivation (B-13). Linking it again is `UAT-BLD-18` (B-13, built in RC-UAT-22). Step 6: A1 signs in to a pending account, which shows no shipment and no quote (as `CA-SHP-01`). Step 7: an unlink with the reason `merged_since_deactivation`, then the reinstatement. (Archiving A1's customer instead of merging gives the same result, reason `archived_since_deactivation`.) |
| **Privacy / permission** | A reinstated account never regains a link to a customer record that changed under it (B-13) |
| **Evidence to capture** | Screenshots of steps 3, 5 and 6; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-14 — The customer quote's GST/HST line follows the invoice rule (OD-109 stand-in)

| | |
|---|---|
| **Role** | Customer (A2, then A1), then Operations |
| **Prerequisites** | Fresh reset (A2's three domestic quotes accepted; A2 reads English) |
| **Data** | A2: `UAT-AIR-DOM-NS` (to NS), `UAT-AIR-DOM-NB` (to NB), `UAT-AIR-DOM-UNK` (no province), `UAT-AIR-A2-1` (Vietnam → Canada); A1: `UAT-AIR-A1-2` |
| **Steps** | 1. As A2, open **My shipments** and note the Solaris ID of each of the four shipments; open **Quotes** and read the line under each total. 2. Open the `UAT-AIR-DOM-NS` quote and the `UAT-AIR-A2-1` quote; read the total and the line beneath. 3. Switch to Vietnamese; read the list and the `UAT-AIR-DOM-NS` quote again; switch back. 4. As A1, open **Báo giá** and the `UAT-AIR-A1-2` quote; switch to English. 5. As Operations, **Workspace** → `UAT-DOM-AWB` → A2's `UAT-AIR-DOM-NS` → **Print customer quote**; then `UAT-AWB-BOOKED` → A1's `UAT-AIR-A1-2` → **Print customer quote**. 6. Open one `quote.sent` file in `data\uat\account_mail`. 7. **Finance → Invoices → Accepted, not invoiced** → `UAT-AIR-DOM-NS`'s draft: compare its total with the quote's. |
| **Expected** | Step 1: NS "Prices include HST 14 %"; NB "Prices include HST 15 %"; UNK "Prices include GST/HST" (no rate, B-8); `UAT-AIR-A2-1` "Zero-rated (0 %)". Nowhere "Taxes, if any, are added on the invoice." Step 2: **Total** with the same line beneath; amounts as before. Step 3: **Tổng cộng**; "Giá đã bao gồm HST 14 %", "Giá đã bao gồm HST 15 %", "Giá đã bao gồm GST/HST", "Thuế suất 0 (0 %)". Step 4: **Tổng cộng** and "Thuế suất 0 (0 %)"; in English **Total** and "Zero-rated (0 %)". Step 5: each printed quote ends with **Total** (no longer "Total before tax") and "Prices include HST 14 %" or "Zero-rated (0 %)"; no "GST/HST, where it applies, is added on the invoice." Step 6: no amount and no tax wording (unchanged). Step 7: the same total, and "Prices include HST 14 %": the quote and its invoice now say the same thing. The line is read from the shipment's route when the quote is shown (B-9) |
| **Privacy / permission** | OD-109 (P-9) is pending Ben: record any wording finding as S5. The quote shows a rate, never a tax amount, cost or vendor name |
| **Evidence to capture** | Screenshots of the quote list and two quotes in each language, and both printed quotes |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-15 — Admin deletes an old quote version, and restores it

| | |
|---|---|
| **Role** | Operations (set-up), then Admin |
| **Prerequisites** | Fresh reset; `UAT-AWB-OPEN` still open (before `UAT-WSQ-05`) |
| **Data** | A3's `UAT-AIR-A3-1` on `UAT-AWB-OPEN` |
| **Steps** | 1. As Operations, make a superseded version: in A3's **Quote** panel **Re-price**, **Confirm selling rate** (box empty), **Finalise quote** (v1; skip if `UAT-WSQ-02` already did); then add an item (`Trà (UAT)`, 1 box, 0.5 kg), **Re-price**, **Confirm selling rate**, **Finalise quote** (v2). 2. As Admin, open the same card; expand **Quote history (Admin)**; read it. 3. **Delete** on v1: read the dialog; try to confirm with no reason; then reason `Old superseded version (UAT)`, **Delete the quote version**. 4. Read the history and A3's quote panel. 5. Tick **Show deleted versions**. 6. **Restore** v1: try with no reason, then `Restore test (UAT)`, **Restore the quote version**. 7. **Settings → Audit access**: `quote.soft_delete` and `quote.restore`. |
| **Expected** | Step 2: "Deleting a quote version hides it from staff lists, the Customer Account and accepted-not-invoiced. The record is kept for audit and can be restored. A reason is required for both."; v2 then v1, newest first; v1 superseded, with **Delete** (D-1; minimum age 0 days, D-3). Step 3: "The version disappears from staff quote lists, the Customer Account and accepted-not-invoiced. Nothing is erased: the record stays for audit, and an Admin can restore it."; no confirming without a reason. Step 4: v1 is gone from the history and the quote panel. Step 5: v1 with **Deleted** and "Deleted by … on …" and the reason, and **Restore**. Step 6: a reason is required; then v1 is back where it was. Step 7: two rows naming the shipment, the version and each reason (D-2, D-4) |
| **Privacy / permission** | Admin only (`quote:delete`); nothing is erased |
| **Evidence to capture** | Screenshots of steps 2 to 6; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-16 — What cannot be deleted; a deleted version cannot be sent; who sees the panel

| | |
|---|---|
| **Role** | Admin, then Operations, Marketing, Read-only manager; Customer (A2) for step 6 |
| **Prerequisites** | Fresh reset; for step 6, `UAT-QAC-03` done (A2 declined v2 of `UAT-AIR-A2-1`), otherwise skip it |
| **Data** | A1's `UAT-AIR-A1-1` (v1 on `INV-000002`), A2's `UAT-AIR-A2-1` (v1 accepted, draft invoice waiting), A1's `UAT-AIR-A1-2` (v1 sent, waiting), A4's `UAT-AIR-A4-1` (a draft on `UAT-AWB-OPEN`), A4's `UAT-AIR-A4-2` (v1 finalised, not sent) |
| **Steps** | 1. As Admin, open **Quote history (Admin)** on A1's `UAT-AIR-A1-1`. 2. On A2's `UAT-AIR-A2-1`. 3. On A1's `UAT-AIR-A1-2`. 4. On A4's `UAT-AIR-A4-1`. 5. On A4's `UAT-AIR-A4-2`: **Delete** v1 with the reason `Delete latest (UAT)`; in the quote panel press **Send to customer**; then **Show deleted versions** → **Restore** (`Restore to send (UAT)`) → **Send to customer**. 6. Delete A2's declined v2 of `UAT-AIR-A2-1` (reason `Declined (UAT)`); as A2 open **Quotes**, then the old address of that quote. 7. As Operations, Marketing and the read-only manager, open a Workspace card (where the role may) and **Settings**. |
| **Expected** | Step 1: no Delete: "An issued invoice uses this version." Step 2: "A draft invoice is being prepared from this version." Step 3: "Waiting for the customer’s answer." Step 4: "A draft quote cannot be deleted." Step 5: deleted; **Send to customer** refused: "Quote v1 was deleted by an Admin: restore it, or re-quote, before …" (D-5); after the restore it is sent, and a `quote.sent.vi` file for `lan.air` is captured. Step 6: the quote is gone from A2's list; its address shows not found, worded exactly as for a quote that never existed (D-12). Step 7: no **Quote history (Admin)** panel and no **Settings → Retention** tab for any of the three roles |
| **Privacy / permission** | D-1: a version tied to an issued or draft invoice, an open offer or an unbilled acceptance cannot be deleted; `quote:delete` is Admin's alone |
| **Evidence to capture** | Screenshots of each refusal, of step 5's refusal and send, and of step 6 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-17 — Settings → Retention: everything off; dry run only

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset. **Dry run only: do not turn retention deletion on, and do not run the worker without `--dry-run`** (owner approval required; OD-01, OD-36) |
| **Data** | **Settings → Retention**; a third PowerShell window set up as `HOW_TO_RUN.md` §5 |
| **Steps** | 1. As Admin open **Settings → Retention**; read the warning, the switch, the **Record classes** table and the line beneath it. 2. In the box under "To turn it on, type ENABLE RETENTION" type `enable retention` in **lower case** and look at **Turn retention deletion on**; then **clear the box**. Do not type the phrase in capitals and do not press the button. 3. Look at **Enable** on each row. 4. **Run a dry run**; read the report. 5. On **Ended staff sessions** type `30` in **Period (days)** and **Save**; **Run a dry run** again; read the report; then empty the period and **Save**. 6. **Settings → Audit access**: `data_retention.dry_run` and `data_retention.policy_update`. 7. In the third window run the worker as a dry run — repository: `cd backend; .venv\Scripts\python -m app.workers.retention_worker --once --dry-run`; portable package (from its folder): `powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\uat\env.ps1; .venv\Scripts\python -m app.workers.retention_worker --once --dry-run"`. 8. As Operations, open **Settings** and look for **Retention**. |
| **Expected** | Step 1: "Retention periods are not decided" — "The owner has not decided how long records are kept (OD-01, OD-36). Every record class below is disabled with no period, and nothing is ever deleted automatically. Turning retention deletion on needs the owner’s approval."; "Retention deletion is off." — "Nothing is deleted or anonymised, even if the worker is started."; eight classes (Soft-deleted quotes; Declined, withdrawn or expired quote offers; Processed milestone notifications; Used or expired account tokens; Ended Customer Account sessions; Ended staff sessions; Account registration attempts; Vendor rate emails taken in), each **Disabled**, no period, **Never run**; "Invoices, payments, vendor bills, customers, shipments and audit events are not record classes: the worker cannot reach them." (D-6). Step 2: the button stays disabled for anything but the exact phrase (D-10). Step 3: every **Enable** disabled, "Turn retention deletion on and set a period first." Step 4: "Dry run of …"; every class "No period set"; **Would run** No; nothing changed. Step 5: **Ended staff sessions** shows a count under **Would be affected**, still **Would run** No (the switch is off); the others "No period set"; after emptying, the period is gone. Step 6: the dry runs and the two policy edits, naming the Admin; counts only. Step 7: one line `{"status": "completed", "dry_run": true, "counts": {…}}`, one entry per class; nothing deleted or anonymised; no scheduler starts (D-11). Step 8: no **Retention** tab |
| **Privacy / permission** | `retention:manage` is Admin's alone; turning deletion on needs the owner's written approval, so UAT never does it |
| **Evidence to capture** | Screenshots of steps 1 to 5 and 8; the worker's output |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-18 — Admin re-links an account left without a customer (B-13)

| | |
|---|---|
| **Role** | Admin, Operations, then Customer (A1) |
| **Prerequisites** | Straight after `UAT-BLD-13` (A1's account reinstated to pending approval, no linked customer); a fresh reset afterwards |
| **Data** | A1's account (`CA-000001`); A1's customer Phạm Thị Thu Trang (the merge survivor); the merged record `Phạm Thị Thu Trang (UAT merge)` from `UAT-BLD-13` |
| **Steps** | 1. As Admin, **Customer accounts**; find **Accounts needing a customer** and read it. 2. On A1's row **Re-link**: replace the suggested customer with the merged record's old ID and **Show this customer’s history**. 3. Put back A1's customer ID (the suggestion); **Show this customer’s history**; read **What this link will open**. 4. Try **Re-link and activate** before ticking. 5. Tick "I have read the history above …", reason **The correct customer record**, note `UAT re-link`; **Re-link and activate**. 6. Read the list and A1's account. 7. Open the newest file in `data\uat\account_mail`. 8. As A1, sign in; open **Lô hàng của tôi** and **Báo giá**. 9. As Operations, open **Customer accounts**. 10. As Admin, **Settings → Audit access**: `customer_account.relink`. |
| **Expected** | Step 1: "Admin only. These accounts were approved once but are no longer linked to a customer …"; A1's row with **Last linked customer** A1's ID, **Why that link ended** "Customer merged while deactivated", **Suggested customer** A1's ID. Step 2: refused: "… was merged. Select … explicitly if that is the right record." (or "… was merged into …"), naming A1's customer. Step 3: the shipment count and dates of A1's history. Step 4: the button stays disabled. Step 5: "The account is linked and active again. The customer was emailed that it is ready." Step 6: A1 gone from the list; the account **active**, linked to Phạm Thị Thu Trang. Step 7: an `account.approved` notice. Step 8: A1's shipments and quotes are back. Step 9: no **Accounts needing a customer** section. Step 10: one row naming the customer, the previous link's end reason and the reason code; the note is not in it (B-15 to B-18) |
| **Privacy / permission** | Admin only (`customer_account:deactivate`); the history is shown and acknowledged before the link opens it; a merged-away or archived record cannot be linked |
| **Evidence to capture** | Screenshots of steps 1 to 6 and 8; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-19 — Admin closes an account left without a customer, and can reinstate it

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | After `UAT-BLD-18`; a fresh reset afterwards |
| **Data** | A1's account (`CA-000001`); a second throwaway customer created in step 2 |
| **Steps** | 1. Deactivate A1's account again (reason **Customer asked for it**). 2. Repeat steps 2 and 3 of `UAT-BLD-13` with the name `Phạm Thị Thu Trang (UAT merge 2)` and email `trang.merge2@example.com`, keeping A1's record. 3. **Deactivated accounts** → A1 → **Reinstate account** (reason **Deactivated in error**). 4. **Accounts needing a customer** → A1 → **Close**: read the dialog; try to confirm without a reason; reason **Duplicate account**; **Yes, close the account**. 5. Read A1's account; count the files in `data\uat\account_mail`. 6. **Deactivated accounts** → A1. 7. **Settings → Audit access**: `customer_account.orphan_closed`. |
| **Expected** | Step 3: A1 is back under **Accounts needing a customer**. Step 4: "The account is deactivated (reason: no customer to link). Its sessions end; nothing is emailed to the customer. An Admin can reinstate it later, which brings it back to this list."; no closing without a reason; then "The account has been closed." and A1 leaves the list. Step 5: **deactivated**, "Closed: no customer to link"; no new mail file (B-19). Step 6: **Can be reinstated** (B-20). Step 7: one row with the reason code and the previous customer |
| **Privacy / permission** | Admin only; closing is a deactivation, not a deletion: the record and its history stay |
| **Evidence to capture** | Screenshots of steps 4 to 6; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-20 — A Nova Scotia draft shows the invoice line by line (HST 14 %)

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset (the domestic drafts unsent); `UAT-OWN-28` not yet run, or reset after it |
| **Data** | A2's (Emily Carter) `UAT-AIR-DOM-NS` on `UAT-DOM-AWB` (Halifax NS B3H 1A1), its draft at 14 % included |
| **Steps** | 1. **Finance → Invoices → Accepted, not invoiced** → `UAT-AIR-DOM-NS` → **Review draft invoice**. 2. Read the lines editor (amounts) and, in the **Saved draft** card, **As the invoice will show it**. 3. For each line work by hand: net = amount ÷ 1.14 rounded half up to the cent; tax = net × 0.14 rounded half up; if net + tax ≠ amount, move the net by the cent. 4. Add a line `Fuel surcharge` **0.12**, reason `UAT per-line check`; read the tax summary; tick the check; **Save draft**. 5. Read the preview table again. 6. **Download PDF (draft)**. |
| **Expected** | Step 2: the editor shows the all-in amounts; the table has Description, Quantity (1), Rate (4 decimals), Amount before tax, Tax (**HST 14%** on every line), Tax (CAD); below it **Subtotal**, **HST @ 14%**, **Total (CAD)** = the accepted all-in total. Step 3: every figure matches to the cent; per line net + tax = amount. Step 4: saved (the server accepts the figures the screen showed). Step 5: the new line reads 0.10 before tax and 0.02 tax (0.11 + 0.02 nudged to 0.10 + 0.02); the total rises by exactly 0.12. Step 6: the PDF reads as the table: columns Description, Qty, Rate, Amount, Tax; Subtotal, "HST @ 14%", Total (CAD); no "Prices include", no Vietnamese; the **DRAFT** watermark |
| **Privacy / permission** | Revenue only; no cost, exchange rate or vendor name |
| **Evidence to capture** | Screenshots of steps 2 and 5; the hand calculations; the draft PDF |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-21 — Send the New Brunswick draft: stored nets, the invoice detail and the desk's PDF

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | A2's `UAT-AIR-DOM-NB` (Moncton NB E1C 4M3), 15 % included |
| **Steps** | 1. Open the draft; read **As the invoice will show it**. 2. Tick the check, **Save draft**, **Send invoice**. 3. Open the invoice through **Sent as**; read the lines and the summary. 4. **Download PDF**; read the header, the table, the summary, the payment lines and the footer. 5. **Print invoice**; read it. 6. **Finance → Profitability** for the month; find the shipment's revenue. |
| **Expected** | Step 1: Tax **HST 15%** per line, the row **HST @ 15%**. Step 3: columns Description, Quantity (1), Rate, Amount (before tax), Tax (**HST 15%**); **Subtotal** and **HST @ 15%** as the draft showed; the total = the draft's all-in total. Step 4: "Solaris Express Inc.", "2446 Cawthra Rd Building 1 Unit 8, Mississauga ON L5A 3K6", "solarisexpressinc@gmail.com", "GST/HST BN: 795093756RT0001"; INVOICE, the number, Issued, Due, "Terms: Due on receipt", "Currency: CAD"; Description / Qty / Rate / Amount / Tax; Subtotal, "HST @ 15%", Total (CAD); "Payment: E-transfer to info@solarisexpress.ca"; "Wire: Bank of Montreal, 2825 Eglinton Avenue West, Mississauga ON L5M 6J3 · SWIFT BOFMCAM2 · Account 1969380"; the footer "Thank you for your business! We accept payment via E-transfer to info@solarisexpress.ca"; no "Prices include", no "included" in the Tax column, no Vietnamese word or accent. Step 5: the same columns, rows, terms and payment lines. Step 6: revenue = the invoice's **Subtotal** (before tax) |
| **Privacy / permission** | The PDF and the print page are allowlisted: no cost, margin, exchange rate or vendor |
| **Evidence to capture** | Screenshots of steps 1, 3 and 5; the PDF; the profitability row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-22 — Zero-rated international invoices: `INV-000002` and `INV-000003`

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | `INV-000002` (A1, Phạm Thị Thu Trang, VN → CA, sent from a draft at 0 %); `INV-000003` (A3, 0 %, part-paid) |
| **Steps** | 1. Open `INV-000002`; read the lines and the summary. 2. **Download PDF**; read the bill-to, the Tax column and the summary. 3. The same for `INV-000003`. 4. **Finance → Receivables**: the balances. |
| **Expected** | Step 1: each line's Tax **Zero-rated**, Amount = the line, the row **GST @ 0%** at 0.00; Subtotal = Total. Step 2: English labels for this Vietnamese customer; the bill-to reads "Pham Thi Thu Trang" (no accents, stand-in I-1); "Zero-rated" per line and "GST @ 0%"; no "Thuế suất", no "Giá đã bao gồm". Step 3: the same, A3's name without accents. Step 4: balances unchanged (CAD 108.00 open for A1; A3 owes the rest after CAD 50.00) |
| **Privacy / permission** | As UAT-BLD-21 |
| **Evidence to capture** | Both PDFs; screenshots of the invoice lines |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-23 — Manual Issue invoice at 13 %: added on top, per line, on the new layout

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset; a shipment with a finalised quote, no draft and no invoice (as `UAT-FIN-01` prepares) |
| **Data** | The shipment `UAT-FIN-01` invoices |
| **Steps** | 1. **Issue invoice**, choose **13 %**. 2. Open the invoice; read Quantity, Rate, Amount and Tax per line and the summary. 3. Work each line: tax = amount × 0.13 rounded half up; Rate = amount ÷ quantity to 4 decimals. 4. **Download PDF**. |
| **Expected** | Step 1: the choices are still 0, 5 and 13 % (stand-in I-2). Step 2: Amount = each quote line (before tax), the quote's quantities and Rate to 4 decimals, Tax **HST ON**; the row **HST ON @ 13%** = the sum of the line taxes; Total = Subtotal + tax. Step 3: matches to the cent. Step 4: as UAT-BLD-21 step 4, with "HST ON" / "HST ON @ 13%" |
| **Privacy / permission** | Revenue only |
| **Evidence to capture** | A screenshot of step 2; the calculations; the PDF |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-24 — Terms follow Invoice terms; back to Due on receipt

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset; after UAT-BLD-20 (or on any confirmed open domestic draft) |
| **Data** | **Finance → Month close → Invoice terms**; A2's `UAT-AIR-DOM-NS` draft |
| **Steps** | 1. As Admin set **Invoice terms** to **15** days. 2. As Operations open the NS draft, **Download PDF (draft)**. 3. As Admin set it back to **0**; download again. |
| **Expected** | Step 2: "Terms: Net 15 days" and a due date 15 days after the issue date. Step 3: "Terms: Due on receipt", due date = issue date (stand-in I-6; one day reads "Net 1 day") |
| **Privacy / permission** | Invoice terms: Admin (`settings:manage`) |
| **Evidence to capture** | Both PDFs' headers |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-25 — The legal entity reads Solaris Express Inc. (I-10); the draft editor's wording (I-11)

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset |
| **Data** | **Settings → Brand and tracking**; the sign-in page; A2's `UAT-AIR-DOM-NS` draft |
| **Steps** | 1. Signed out, read the foot of the sign-in page (English, then Vietnamese). 2. As Admin, **Settings → Brand and tracking**: read **Legal entity**. 3. Open any shipment booked by the demo counter and read the sender's company. 4. As Operations, open the NS draft (`UAT-AIR-DOM-NS`) and read the tax sentence under the lines. |
| **Expected** | Steps 1 and 2: "Solaris Express Inc."; "Soleil Global Transportation Inc." appears nowhere (DEC-0236). Step 3: the sender's company "Solaris Express Inc."; the printed label still carries the "Solaris Express" wordmark. Step 4: "Tax included in the price: subtotal before tax …, HST @ 14% …, total …" -- the same "HST @ 14%" as the invoice's summary row (DEC-0239) |
| **Privacy / permission** | Settings: read-only legal entity |
| **Evidence to capture** | Screenshots of steps 1, 2 and 4 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

## RC-UAT-25: Ben's live UAT fixes of 2026-10-25 (`-26` to `-33`)

Ben's eight findings of 2026-10-25 (OD-113; DEC-0240 to DEC-0247; record
`docs/b2c_merge/29_BUILD_RC25_RECORD.md`; stand-ins RC25-A1 to A8, B1 to B13 and C1 to C7 in
`19_OWNER_QUESTIONS.md` §000000). Required-field asterisks (`-26`), the declared value currency
list (`-27`), saved addresses for the recipient (`-28`), the end of the customer's self-service
email change (`-29`; the Admin's change is `UAT-BLD-09`), "Received at warehouse" (`-30`),
correcting a published event (`-31`), the Financials tab (`-32`, `-33`). Each needs only a fresh
reset unless it says otherwise; `-31` follows `-30`.

### UAT-BLD-26 — Required fields show a red asterisk, no "(required)" words

| | |
|---|---|
| **Role** | Operations; then a stranger (no sign-in); then A1 in the Customer Account |
| **Prerequisites** | Fresh reset |
| **Data** | <http://localhost:5173/shipments/new>; `/account/register`, `/account/sign-in`; A1 `trang.air@example.com` (Vietnamese), A2 `emily.air@example.com` (English); passwords in `ENVIRONMENT.md` §2 |
| **Steps** | 1. As Operations, **Shipments → New**; choose A1 Phạm Thị Thu Trang, **Continue**; read the labels of step 2, then **Continue** to step 3 and read the sender and recipient labels. 2. Open a confirmed shipment (`UAT-AIR-A1-2`), **Operational timeline → Record event**; read the labels; **Cancel**. 3. Switch the staff language to Tiếng Việt and repeat step 1's reading. 4. Signed out, open `/account/register` in English, then switch to Tiếng Việt; read every label. 5. Open `/account/sign-in` in both languages. 6. Sign in as A1, open **Đăng nhập và bảo mật** (Sign-in and security); read the password form. 7. (Optional, with a screen reader such as NVDA or Narrator) tab to **Email address** on `/account/sign-in`. |
| **Expected** | Everywhere: a required field shows a red `*` right after its label and **no** "(required)", "(Required)" or "(bắt buộc)" anywhere on the page. Step 1: red `*` on **Route group**, **Contents description**, and (step 3) **Full name**, **Country** for both parties and **City** for the recipient; **Declared value**, **Currency**, **Booking reference**, **Estimated delivery**, **Company**, **Email**, **Address line 2** show no star and "optional" under the field; no grey star. Step 2: red `*` on **Event type** (and on **Public update text** when "Public update" is ticked with own wording); **Occurred at**, **Leg**, **Location**, **Country** say "optional". Step 3: the same in Vietnamese ("không bắt buộc" under optional fields). Step 4: red `*` on **Email address / Địa chỉ email**, **Password / Mật khẩu**, **Confirm password**, **Full legal name**, **Are you shipping as**, and the address's **Country**, **Address line 1**, **City**, **Province or state**; "Optional" / "Không bắt buộc" **under** Address line 2, Postal code, the driver note and the phone fields, not "(optional)" in the label. Step 5: red `*` on email and password. Step 6: red `*` on the three password fields. Step 7: the reader announces "Email address, required" (or "Địa chỉ email, bắt buộc"), not "star" (RC25-A1) |
| **Privacy / permission** | Presentation only; no permission or data change (DEC-0240) |
| **Evidence to capture** | Screenshots of booking steps 2 and 3 (EN and VI), the Record event form, `/account/register` (EN and VI), `/account/sign-in`, Sign-in and security |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-27 — Create booking: the declared value currency is a list (CAD, VND)

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset |
| **Data** | <http://localhost:5173/shipments/new>; customer A4 Đỗ Ngọc Lan |
| **Steps** | 1. **Shipments → New**; choose A4, **Continue**. 2. Open the **Currency** list and read it; leave it, then read the field after choosing **Route group** Vietnam → Canada. 3. Type **Declared value** `150`, choose **VND — Vietnamese dong**, fill **Contents description** `Quà tặng (UAT)`, **Continue**; fill a Vietnam sender (any name, country `VN`) and a Canada recipient (name, city `Toronto`, country `CA`), **Save draft**. 4. Go back to step 2 and change the currency to **—**, then to **CAD — Canadian dollar**, **Save draft**. 5. Switch to Tiếng Việt and open the list again. 6. (Admin or developer, optional) send a draft with `"declared_value_currency": "USD"` to `POST /api/v1/shipments`, e.g. via the browser devtools console with the staff CSRF cookie. |
| **Expected** | Step 2: a drop-down (not a text box) with exactly **—**, **CAD — Canadian dollar**, **VND — Vietnamese dong**; it starts on **—** and choosing the route does not fill it (RC25-A5); "optional" under it and no star. Step 3: the draft saves; **Review** shows "Declared value 150 VND". Step 4: both save; with **—** the review shows the declared value with no currency. Step 5: "Đô la Canada", "Đồng Việt Nam". Step 6: refused with 422, "Choose CAD or VND for the declared value currency.", field `declared_value_currency`; nothing is created (RC25-A4) |
| **Privacy / permission** | Booking create/edit permissions as before; the server enforces the list (a bypassed screen cannot store another code; DEC-0241) |
| **Evidence to capture** | Screenshot of the open list (EN and VI); the review step; the step 6 response if run |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-28 — Create booking: the recipient can use a saved address

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Fresh reset. A1's only saved address is the one her Customer Account registration created (a **sender** address, 101 Test Data Lane (UAT), Toronto) |
| **Data** | <http://localhost:5173/shipments/new>; A1 Phạm Thị Thu Trang (`trang.air@example.com`); for step 5, a new address on A1's **Address book** tab: role **Recipient**, label `Mẹ (UAT)`, name `Trần Thị Mẹ`, `125 Nguyễn Huệ`, `Thành phố Hồ Chí Minh`, country `VN` |
| **Steps** | 1. **Shipments → New**; choose A1, **Continue**; **Route group** Vietnam → Canada, **Contents description** `Quà tặng (UAT)`, **Continue**. 2. Read both cards: **Sender** and **Recipient**. 3. In **Recipient → Use a saved address**, choose A1's own address. 4. Choose **Enter details manually**. 5. Add the recipient address in **Data** to A1's Address book (Customers → A1 → Address book), then return to a new booking for A1 and repeat steps 1–2 with route Canada → Vietnam. 6. In **Recipient**, choose **Mẹ (UAT)**; fill a Canadian sender by hand; **Continue** through to **Review**, then **Save draft**. 7. Repeat step 1 for A3 Võ Minh Khoa (or any customer with no saved address). |
| **Expected** | Step 2: the **Recipient** card now has **Use a saved address**, with the hint "Every saved address of this customer except billing; the customer's recipient addresses come first."; it lists **Enter details manually** and A1's address marked "(saved as sender)". The sender card's list is unchanged (sender and both addresses). No billing address is offered in either (RC25-A7). Step 3: the recipient's Full name, Phone, Address line 1, City, Province / state, Postal code and Country fill from the saved address, and the snapshot note shows. Step 4: the recipient fields empty again. Step 5: the recipient list shows **Mẹ (UAT) — Trần Thị Mẹ, Thành phố Hồ Chí Minh** first, then A1's address "(saved as sender)". Step 6: the recipient fills with Trần Thị Mẹ … VN; **Review** shows that recipient; the draft saves. Editing the address book afterwards does not change the draft's recipient (snapshot). Step 7: no picker; both cards say "This customer has no saved address yet. Enter the details below." |
| **Privacy / permission** | Only the chosen customer's own addresses are listed (`address:read`); the server refuses an address of another customer ("That saved address does not belong to this customer.") (DEC-0242) |
| **Evidence to capture** | Screenshots of the recipient list in steps 2 and 5, the filled recipient card, the review |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-29 — A link from the old self-service email change no longer works

| | |
|---|---|
| **Role** | Customer (A2) |
| **Prerequisites** | A captured `email_change_confirm` file from an RC-UAT-21 to RC-UAT-24 build (keep one from a previous round), or skip the case and record "not applicable" |
| **Data** | That file's link (`…/account/confirm-email-change#token=…`); `emily.air@example.com` (or the address the link's account signs in with), password in `ENVIRONMENT.md` §2 |
| **Steps** | 1. Open the old link. 2. Sign in as A2 and open **Sign-in and security**. |
| **Expected** | Step 1: "This link no longer works" — "Sign-in emails are now changed by Solaris Express. Your sign-in email is unchanged; contact us if you need it changed."; the token is gone from the address bar. Step 2: the email is unchanged and nothing is pending (RC25-B1) |
| **Privacy / permission** | Every self-service link is refused with one sentence; the account, its sessions and its customer are untouched (DEC-0243) |
| **Evidence to capture** | Screenshots of steps 1 and 2 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-30 — The received event now reads "Received at warehouse"

| | |
|---|---|
| **Role** | Operations, then customer (A1, Vietnamese) and a stranger on public tracking |
| **Prerequisites** | Fresh reset; a confirmed shipment not yet received: A1's `UAT-AIR-A1-2` on `UAT-AWB-BOOKED` (no milestone yet) |
| **Data** | `UAT-AIR-A1-2`; `trang.air@example.com`; the shipment's public tracking link |
| **Steps** | 1. Open the shipment → **Operational timeline → Record event**; open **Event type**. 2. Choose the received event; read the standard update and its EN/VI preview; record it, published. 3. Read the timeline and the status badge; the Shipments list filter. 4. **Settings → Customer notifications** and the customer's **Milestone emails** card. 5. As A1 (Vietnamese) open the shipment in the account; read the status and the milestone-email choices. 6. Open public tracking for it, in English and in Vietnamese. 7. If a received event published with the old standard update before this build exists (none may on a fresh reset), open it. |
| **Expected** | Step 1: **Received at warehouse** (Vietnamese: **Đã nhận hàng tại kho**); the old name ("… at Solaris") appears nowhere. Step 2: "We have received your shipment at our warehouse." / "Chúng tôi đã nhận lô hàng của bạn tại kho."; it is the only standard update offered. Steps 3–6: **Received at warehouse** / **Đã nhận hàng tại kho** everywhere. Step 7: the older event keeps the sentence it was published with ("…at our facility.") (RC25-B7) |
| **Privacy / permission** | Wording only; the stored code `received_at_solaris` is unchanged (DEC-0244) |
| **Evidence to capture** | Screenshots of the event-type list, the standard update preview, the account (VI) and public tracking (EN and VI) |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-31 — Edit an event already published to the customer

| | |
|---|---|
| **Role** | Operations, then Admin, Marketing, customer (A1) |
| **Prerequisites** | `UAT-BLD-30` done (`UAT-AIR-A1-2` with its published received event); the number of files in `data\uat\account_mail` noted |
| **Data** | `UAT-AIR-A1-2`; for step 5, `UAT-AIR-A1-1` (its departure update carries staff's own wording, "Chuyến bay UAT-101 …") |
| **Steps** | 1. On the timeline click **Edit** on the received event; read the form. 2. Change **Location** to `Mississauga warehouse`; try **Save correction** without a reason. 3. Give a reason; save. 4. **Edit** again: change **Event type** to **In transit**; read **Customer-visible update** and the preview; save with a reason. 5. On `UAT-AIR-A1-1`, **Edit** the departure (recorded with own wording); try to change the wording. 6. Open **Edit history**. 7. Count the files in `data\uat\account_mail`; open **Settings → Customer notifications**. 8. As Marketing open the shipment. 9. As A1, open the shipment in the account and on public tracking. 10. As Admin, **Settings → Audit access**: `shipment.event_edit`. |
| **Expected** | Step 1: the warning "This event is already published to the customer. Your correction changes what the customer sees … No email is sent about it, and the change and your reason are kept in the edit history."; fields filled with the current values. Step 2: the button stays disabled. Step 3: the timeline shows the new location and **Edited**. Step 4: the standard update switches to "Your shipment is on its way." (EN and VI preview); saved; the status follows. Step 5: own wording cannot be rewritten: **Keep the current wording** or a standard update only (RC25-B8). Step 6: each edit with time, editor, the changed fields and the reason. Step 7: **no new file**; no new notification row (one per milestone, from the original recording; RC25-B10). Step 8: no **Edit** button; the history is readable (RC25-B11). Step 9: the corrected event, no "edited" marker (RC25-B13). Step 10: one row per edit with before and after and the reason |
| **Privacy / permission** | `tracking:write` (Admin, Operations); an edit never publishes, unpublishes or emails (DEC-0245) |
| **Evidence to capture** | Screenshots of steps 1, 4, 5 and 6; the file count before and after; the audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-32 — Financials loads after financial info is added

| | |
|---|---|
| **Role** | Admin, then Operations |
| **Prerequisites** | Fresh reset; any confirmed shipment (e.g. one `UAT-FIN-01` uses) |
| **Data** | The shipment's **Financials** tab (`/shipments/<id>?tab=financials`) |
| **Steps** | 1. Open the Financials tab. 2. In **Recorded amounts** type Currency **CA**, Selling amount **120.00**, **Save amounts**. 3. Change Currency to **CAD**, save. 4. Reload the page by its URL. 5. Open the Details tab, then **Quote & invoice** in the header. 6. Repeat steps 1 and 4 as Operations. |
| **Expected** | Step 1: the **Quote and invoice** card and **Recorded amounts** show; never a blank page. Step 2: "Use a three-letter currency code such as CAD." under Currency; nothing saved. Step 3: Selling amount "CAD 120.00". Step 4: same content after reload. Step 5: back on the Financials tab. Step 6: the same, without Shipping cost and Gross profit (Admin only, RC25-C4). On no step does "This section could not be shown" appear, and the page never goes blank (DEC-0246) |
| **Privacy / permission** | Recorded amounts: `financial:write` to edit; Shipping cost and Gross profit Admin only |
| **Evidence to capture** | Screenshots of steps 2 and 4 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-BLD-33 — Invoice the client right after booking

| | |
|---|---|
| **Role** | Operations; then Read-only manager |
| **Prerequisites** | Fresh reset. As Operations: **Shipments → New** for A4 Đỗ Ngọc Lan, route Vietnam → Canada, any Canadian recipient, one 3 kg package, **Confirm**; **Workspace → New master** (Air Standard, HCM); **Add a customer's shipment** for it; **Add item** `Áo thun (UAT)`, 2 pieces, 3 kg; nothing priced |
| **Data** | That shipment's Financials tab; for step 7, A2's `UAT-AIR-A2-1` (accepted, draft invoice waiting) |
| **Steps** | 1. Open the shipment's Financials tab. 2. Click **Price this shipment**; in the workspace **Price quote**, then back to the tab. 3. In the workspace **Confirm selling rate**, **Finalise quote**; back to the tab. 4. Choose GST/HST **0 %**, **Issue invoice**. 5. Click **Open invoice INV-…**. 6. Sign in as the Read-only manager and open the same tab. 7. As Operations open `UAT-AIR-A2-1`'s Financials tab. |
| **Expected** | Step 1: "No quote yet: price this shipment."; Issue invoice disabled with "Finalise the shipment's quote before issuing an invoice." Step 2: "Quote not finalised: finalise the quote.", v1 · Draft. Step 3: "Ready to invoice: issue the invoice."; Quoted revenue, Vendor cost and Gross profit (quote) shown. Step 4: "Invoiced." and **Open invoice INV-…** with status Issued and the balance (the manual path, added on top, RC25-C5). Step 5: the invoice page for that number. Step 6: Quoted revenue shown; no Vendor cost ("Vendor cost is not shown for your role."); Issue invoice not offered. Step 7: "The customer accepted the quote: a draft invoice is ready to review and send." with **Review draft invoice** (to the draft page). (An expired quote, e.g. after `UAT-OWN-05` step 8, shows "The quote cannot be invoiced: re-quote it." with the expiry refusal under a disabled Issue invoice.) |
| **Privacy / permission** | Vendor cost: `tariff:read` (Admin, Operations); issuing: `financial:write`; Marketing: no Financials content (DEC-0247) |
| **Evidence to capture** | Screenshots of steps 1, 3, 4, 6 and 7 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

## Sign-off

Nothing below is filled in until every case above has a result.

| | Name | Date | Signature |
|---|---|---|---|
| Tester | | | |
| Operations reviewer | | | |
| Owner acceptance | | | |

| Summary | Value |
|---|---|
| Cases in this pack | 104 — counted by heading: `UAT-WSQ` 7, `UAT-QAC` 4, `UAT-FIN` 8, `UAT-PRC` 4, `UAT-TAR` 5, `UAT-MLS` 4, `UAT-VIA` 4 (36, DEC-0218); `UAT-OWN` 35: `-01` to `-17` (RC-UAT-18, owner answers of 2026-10-21), `-18` to `-27` (RC-UAT-19, owner answers of 2026-10-22) and `-28` to `-35` (RC-UAT-20, owner answers of 2026-10-23); and `UAT-BLD` 33: `-01` to `-17` (RC-UAT-21, the build of 2026-10-24, OD-110; `-10` withdrawn in RC-UAT-25, its heading kept), `-18`, `-19` (RC-UAT-22), `-20` to `-24` (RC-UAT-23), `-25` (RC-UAT-24) and `-26` to `-33` (RC-UAT-25, Ben's live UAT of 2026-10-25, OD-113). `scripts/verify_uat_blank.py` checks this number |
| Executed | |
| Passed | |
| Failed | |
| Blocked | |
| Defects raised | |
