# UAT walk-through for Ben — air quotes and money (60 to 90 minutes, plus 10 to 15 for your answers of 21 October, 10 for those of 22 October, 10 to 15 for those of 23 October and 20 for the build of 24 October)

A guided route through the air features built in Phases 13 to 15, in the order a real job
flows: tariff → quote → customer answer → milestones → money → month end. Each step points
at the case in `AIR_UAT_PACK.md` that holds the full steps and expected result; this page
says what to look at and what would be wrong. Everything is test data. No email leaves the
machine.

**Before you start (10 minutes).** Follow `HOW_TO_RUN.md` §2 to §4: reset, start the
backend and the screens. The reset must end with "Every required category is present."
Keep `data\uat\account_mail\` open in Explorer: every email lands there as a file. Keep
`DEFECT_TEMPLATE.md` to hand.

**How to record as you go.** In `AIR_UAT_PACK.md`, under each case you run, fill in
**Evidence obtained** (what you saw or the screenshot name), **Result** (`Pass`, `Fail` or
`Blocked`) and **Defect**. For anything wrong or confusing, copy `DEFECT_TEMPLATE.md`, number
it `UAT-DEF-001` onward, give the case ID, the steps, what you expected and what happened,
and a severity (README.md, "Severity": anything a customer could see that they should not is
S1). Something that works but reads badly is still worth a line: S5. Skip a step you have no
time for; leave its Result blank rather than guessing.

---

## Part 1 — Tariffs (15 minutes), as Admin

Sign in as `admin@demo.example.com`. For this session the demo Admin is the tariff approver;
`ENVIRONMENT.md` §2 says how to add your own account instead.

1. **`UAT-TAR-01`** (as Operations, `ops@demo.example.com`, in a second browser): open
   Settings → Tariffs. *Look for:* one Active and one Draft version; the brackets and the
   exchange-rate history labelled demo; no approve button for Operations. *Wrong if:*
   Operations can change anything.
2. **`UAT-TAR-02`**: Settings → Tariff updates, open the draft from
   `vendor-rates.example.com`. *Look for:* exactly three prices changed, old and new side by
   side; nothing activates until you press **Approve and activate**. *Wrong if:* the change
   list shows anything you would not expect from three edited prices.
3. **`UAT-TAR-03`**: the email from the unknown sender is held. Release it, read its change,
   reject it with a reason. Because you approved step 2's draft first, this one shows
   **four** changed prices (its own one, and step 2's three, which it does not carry). *Look
   for:* a rejected draft has no way back to active.

## Part 2 — Pricing and a quote (20 minutes), as Operations

4. **`UAT-PRC-01`**: Settings → Pricing. *Look for:* CAD 18.00 Air Standard, no Air Express
   default, 2 / 3 share, 2 % default markup; Operations cannot save.
5. **`UAT-WSQ-01`**: Workspace → `UAT-AWB-OPEN`. Read the Vendor cost panel, add a fee.
   *Look for:* the fee search works without accents; cost is shown per customer.
6. **`UAT-WSQ-02`**: confirm the rate, try an override without a reason, finalise, and
   **print the customer quote**. *This is the most important check of the day:* the printed
   quote must show no cost, exchange rate, markup, margin or vendor name. Since your answer
   of 21 October (OD-84), a surcharge name that names a vendor prints as **Phụ phí** /
   **Surcharge**. Since RC-UAT-21 the total reads **Total** with "Zero-rated (0 %)" beneath
   (the tax wording stand-in, P-9, Part 9).
7. **`UAT-WSQ-03`, then `UAT-WSQ-04`** (optional if short of time): send A4's quote, then
   a newer version withdraws it, you cannot send while a draft is open, and Issue invoice
   warns that the quote was withdrawn. `UAT-AWB-BOOKED` is booked, so its items are locked
   (OD-88): as Admin press **Unlock for edits** with a reason first; finalising relocks it.

## Part 3 — The customer's side (15 minutes)

8. **`UAT-VIA-01`**: in a private window open <http://localhost:5173/account/sign-in>. *Look for:* Vietnamese
   first, an English switch on every screen. Sign in as A1, `trang.air@example.com`
   (password in `ENVIRONMENT.md` §2).
9. **`UAT-QAC-01`**: the Quotes list (Báo giá) shows the Solaris shipment ID (`SX-VCA-…`),
   not the booking reference, so first open Lô hàng của tôi and note the ID of the shipment
   with booking reference `UAT-AIR-A1-2`. Then open that waiting quote, read every figure,
   and accept. *Look for:* rate per kg, base charge, A1's own surcharge, the total
   (**Tổng cộng**) in CAD with "Thuế suất 0 (0 %)" beneath — and nothing else: no invoice,
   balance, cost or markup.
10. **`UAT-VIA-02`**: Lô hàng của tôi → `UAT-AIR-A1-1`. *Look for:* each update as a
    standard Vietnamese sentence; staff's own wording appears beneath only where it differs,
    which the seed arranged on the departure ("Chuyến bay UAT-101 …"). Open question #7: is
    that the wording you want customers to read?
11. **`UAT-QAC-02`** (back as Operations): the workspace says "Customer accepted v1 — issue
    the invoice" and "its invoice is ready as a draft"; Finance → Invoices → **Accepted, not
    invoiced** lists it with **Review draft invoice**. The acceptance prepared a draft with
    no invoice number (your answer OD-89). Open it: GST/HST starts at **0 %**, because a
    Vietnam → Canada move is zero-rated (your answer of 23 October, OD-102). Tick "I have
    checked the GST/HST on this invoice", **Save draft**, then **Send invoice**: the `INV-` number appears and an `invoice.sent.vi` file lands in the
    mail folder.

## Part 4 — Milestones and emails (10 minutes), as Operations

12. **`UAT-MLS-01`**: Settings → Customer notifications. *Look for:* A2's "in transit" not
    sent because the customer turned it off; A1's in Vietnamese, A2's in English. Open two
    of the files in `data\uat\account_mail\`.
13. **`UAT-MLS-02`**: on `UAT-AWB-TRANSIT` record *Out for delivery*, published. *Look for:*
    one email per customer, each in their language; recording an earlier step again sends
    nothing.

## Part 5 — Money and month end (20 minutes), as Operations, then Admin

14. **`UAT-FIN-03`, step 1 only**: on `INV-000004`, print receipt `RCT-000003`: a VND
    payment converted at Vietcombank's selling rate; the invoice also shows a CAD 10.00
    refund. *Look for:* the conversion arithmetic, to the cent. (Steps 2–4 need `UAT-FIN-01`
    first; leave them for the staff pass.)
15. **`UAT-FIN-05`**: `UAT-AWB-DELIVERED` → vendor bill. *Look for:* the bill in VND at the
    buy rate, its variance against the estimate, the reason, and the cost split between the
    two customers.
16. **`UAT-FIN-06`**: Finance → Receivables, Payables, Profitability. *Look for:* the open
    balances you would expect from the invoices; the closed month's frozen figures.
17. **`UAT-FIN-07`**: Month close. Try to record a payment dated in the closed month
    (refused), reopen with a reason, record it, close again. *Wrong if:* a closed month
    accepts an entry without being reopened.

## Part 6 — Your answers of 21 October (10 to 15 minutes), on a fresh reset

These check the RC-UAT-18 fix pack (OD-81 to OD-90). Do them on their own fresh reset
(`HOW_TO_RUN.md` §2) — or before Part 1 — because approving the tariff draft in Part 1 uses
up the activation that the expiry case needs. Each case is the `UAT-OWN` group of
`AIR_UAT_PACK.md`.

18. **`UAT-OWN-01`, `-02`** (Operations, then Admin): open `UAT-AWB-BOOKED`. *Look for:*
    **Items and fees locked**; Add item, Edit item and Add fee disabled; Operations is told an
    Admin can unlock. As Admin, **Unlock for edits** refuses an empty reason. *Wrong if:*
    Operations can unlock, or an item changes on a booked master without an unlock.
19. **`UAT-OWN-04`** (2 minutes): with the master unlocked, price and finalise A4's quote
    again. *Look for:* the master locks itself again.
20. **`UAT-OWN-13`**: Settings → Tariffs → **Tariff versions** → **View** on the Active
    row; the card **Import warnings (39) · TRF-…** is beneath it. *Look for:* 39 warnings,
    none about the 16 kg Express price drop you confirmed (OD-81), which are listed apart
    as **Confirmed price steps (3)**.
21. **`UAT-OWN-09`, `-12`** (Operations): Finance → Invoices → **Accepted, not invoiced** →
    A2's **Review draft invoice**. Type a PO, and see Send and Download refuse until you
    tick the GST/HST check and **Save draft** (since 22 October, OD-94); then **Download PDF (draft)** and **Send invoice**. *Look for:* the DRAFT
    watermark, the company's details and BN, no vendor name; after Send, an `INV-` number,
    a PDF without the watermark, and an `invoice.sent.en` file with number, total and due
    date only.
22. **`UAT-OWN-05`** (optional, 10 minutes more: it books three test shipments): a sent
    quote expires when you approve the tariff draft, the customer reads "Đã hết hạn", and a
    quote whose goods were received does not.

## Part 7 — Your answers of 22 October (10 minutes), on a fresh reset

These check the RC-UAT-19 fix pack (OD-91 to OD-101): cases `UAT-OWN-18` to `-27` of
`AIR_UAT_PACK.md`. Use a fresh reset, or the one for Part 6 **before** its step 21 (which
sends A2's draft). Your answers of 23 October (Part 8) changed some of what these cases
expect; the steps below already say what you should now see.

23. **`UAT-OWN-18`, `-19`** (Operations): Finance → Invoices → **Accepted, not invoiced** →
    A2's **Review draft invoice**. *Look for:* GST/HST **0 %**, "Route VN → CA:
    international, zero-rated (0 %)."; the total equals the accepted quote, with no tax;
    Save, Send and Download refuse until you tick "I have checked the GST/HST on this
    invoice". Tick it and **Save draft**: Send and Download are enabled. Change the rate to
    5 %: the tick clears; press **Undo my changes**. *Wrong if:* anything can be sent or
    downloaded without the tick.
24. **`UAT-OWN-22`**: open `INV-000002` (A1) and **Download PDF**. *Look for:* total CAD
    108.00, the tax row "Thuế suất 0 (0 %)" at CAD 0.00 (is that the Vietnamese you want?),
    and no "Giá đã bao gồm …" sentence: nothing is included at 0 %.
25. **`UAT-OWN-23`** (Operations, then signed out, then A1): on `UAT-AIR-A1-1` add a
    *Final delivery* leg with provider `Kango Logistics` (now offered on that leg) and a
    UPS external link (the case gives the values). Open public tracking and A1's shipment page. *Look for:* the
    link shown as **Theo dõi chặng cuối** / **Last Mile Tracking**; no "Kango", no "UPS".
    Do not click the link.
26. **`UAT-OWN-25`, `-26`** (Operations): on `UAT-AWB-OPEN`, A3's `Quần áo (UAT)` → **Add
    fee** → `my ky`. *Look for:* two empty fields, **Vendor cost (VND)** and **Customer
    price (CAD)**, no kg; finalising refused until both are entered (`200000` and `25.00`,
    **Save**); then the cost is 200,000 VND on A3 only and the customer pays exactly CAD
    25.00, whatever the weight (your answer of 23 October, OD-103).

## Part 8 — Your answers of 23 October (10 to 15 minutes)

These check the RC-UAT-20 fix pack (OD-102 to OD-108, and the findings you reported):
cases `UAT-OWN-28` to `-35` of `AIR_UAT_PACK.md`. Use a fresh reset, or the reset of Part 7:
then do step 27 when you first open A2's draft in Part 7's step 23, **before** you tick the
check, and the rest before Part 6's step 21 sends A2's draft. Only P-8 (Python 3.15) is still open; the small
stand-ins the developers chose are listed at the top of the pack, and none stops a case.

27. **`UAT-OWN-30`** (Operations; 1 minute): A2's draft, before you tick anything. *Look
    for:* **Download PDF (draft)** disabled like **Send invoice**, with "… tick the check and
    save before sending or downloading." (a read-only user reads that it is "not yet
    confirmed by finance staff"). *Wrong if:* a draft PDF can be downloaded before
    the GST/HST is checked.
28. **`UAT-OWN-28`** (Operations): Settings → **GST/HST rates**: ON 13, NS 14, NB / NL / PE
    15, the rest 5 % GST. Then Finance → Invoices → **Accepted, not invoiced** → the drafts of
    `UAT-AIR-DOM-NS` and `-NB` (domestic shipments the seed put on their own master for UAT
    only, since a domestic shipment cannot be quoted on screen). *Look for:* "Prices include
    HST 14 %" (NB: HST 15 %), the tax backed out of an unchanged total (total × 14 ÷ 114).
    `UAT-AIR-DOM-UNK` has no province: it asks you to **Choose a rate** before anything can be
    saved, sent or downloaded.
29. **`UAT-OWN-29`** (Admin, 2 minutes): on **GST/HST rates** set ON to 12 and save, then
    back to 13. *Look for:* only Admin can save; `12.5` is refused; the audit names you.
30. **`UAT-OWN-31`** (Operations, 2 minutes): on `INV-000003` record CAD 5.00 received
    today. *Look for:* the payments list and the receipt show **today's date**, not the day
    before (the 20 Sep → 19 Sep fault). Tomorrow's date is refused.
31. **`UAT-OWN-33`** (Operations, then A2): on `UAT-AIR-A2-1` add a *Final delivery* leg.
    *Look for:* **Kango Logistics** first in the provider list; the legs read **Last Mile
    Tracking** / **Master Tracking**; A2's page says "Last Mile Tracking" ("Theo dõi chặng
    cuối" in Vietnamese) with no vendor or carrier name.
32. **`UAT-OWN-34`** (Operations, 1 minute): Settings → Tariffs → **Tariff versions** →
    **View** on the Active row. *Look for:* **Import warnings (39)** and, apart,
    **Confirmed price steps (3)**.
33. **`UAT-OWN-35`** (as A1, 1 minute): the quote reads **Tổng cộng**, the label you chose
    to keep. Beneath it, since RC-UAT-21, "Thuế suất 0 (0 %)" instead of "Thuế, nếu có, sẽ
    được tính trên hóa đơn.": the stand-in for open question P-9 (Part 9, step 37).

## Part 9 — The build of 24 October (20 minutes), on a fresh reset

These check RC-UAT-21, the features you asked to have built now (OD-110): cases `UAT-BLD-01`
to `-17` of `AIR_UAT_PACK.md`. Every choice the developers had to make is a stand-in listed in
`docs/b2c_merge/19_OWNER_QUESTIONS.md` §0000 (A-1 to A-14, B-1 to B-20, D-1 to D-12, and P-9);
none stops a case. Use a fresh reset. Copy the two templates from
`artifacts\sample-imports\` to your Desktop first; in Excel, save them with **Save as → CSV
UTF-8**. Read the Solaris customer IDs of A1 (`trang.air`) and A3 (`khoa.air`) on
**Customers**. Do step 40 last: it changes A2's sign-in email (as Admin).

34. **`UAT-BLD-01`, `-02`** (Admin, 5 minutes): Customers → import → **Import type →
    Shipments**: **Download template**. Keep only the first sample row, with A3's ID in
    `customer_ref`; add two copies of it with new references, one with
    `package_weights_kg` `600` and `package_dimensions_cm` empty, one with `booking_date`
    `01/02/2024`, and dry run it.
    *Look for:* each bad row names its problem ("…heavier than 500 kg…", "Use YYYY-MM-DD");
    "Dry run only. Nothing has been imported."; the Shipments total unchanged.
35. **`UAT-BLD-03`, `-04`** (3 minutes): delete the bad rows, dry run again, **Import**.
    *Look for:* "No quote, invoice, email or milestone notification is created."; a batch
    `IMP-…`; the shipment in Shipments with its packages and items, and no email in the mail
    folder. Dry run the same file again: every row **Duplicates (refused)**.
36. **`UAT-BLD-05`, `-06`** (3 minutes): **Legacy history**: put A1's ID in both rows of
    the template; dry run; import. *Look for:* the two records with the **Legacy** badge on
    that page and **nowhere else**: not in Shipments, not in Finance, not in A1's Customer
    Account. Should customers see their own old shipments (A-7)?
37. **`UAT-BLD-14`** (as A2, 2 minutes): **Quotes**. *Look for:* "Prices include HST 14 %"
    on the Nova Scotia quote, "HST 15 %" on New Brunswick, "Zero-rated (0 %)" on the Vietnam
    → Canada one; in Vietnamese "Giá đã bao gồm HST 14 %" and "Thuế suất 0 (0 %)". This
    replaces "Taxes, if any, are added on the invoice." so the quote matches the invoice
    (P-9, OD-109): *is that what you want customers to read?*
38. **`UAT-BLD-15`** (Operations, then Admin, 3 minutes): on `UAT-AWB-OPEN`, finalise A3's
    quote twice (add an item in between); as Admin open **Quote history (Admin)**, delete
    v1 with a reason, tick **Show deleted versions**, restore it. *Look for:* a reason
    every time; on A1's `UAT-AIR-A1-1` no Delete, "An issued invoice uses this version."
39. **`UAT-BLD-17`** (Admin, 2 minutes): **Settings → Retention**. *Look for:* "Retention
    deletion is off.", every class disabled with no period; **Run a dry run** counts and
    changes nothing. **Do not turn retention deletion on**: that waits for your decision on
    how long records are kept (OD-01).
40. **`UAT-BLD-09`** (as A2, then Admin, 4 minutes): **Sign-in and security** shows the
    sign-in email with "Only Solaris Express can change your sign-in email." and no way to
    change it. As Admin, **Customer accounts** → A2 → **Change sign-in email** to
    `emily.new@example.com` (reason **Customer lost access to the old mailbox**). *Look for:*
    A2 is signed out everywhere and signs in with `emily.new@example.com` and the same
    password; the captured files: a notice to `emily.air`, a sign-in notice to `emily.new`, no
    confirmation link. Reset afterwards (`HOW_TO_RUN.md` §2).
41. **`UAT-BLD-13`, `-18`, `-19`** (Admin, after the reset, 10 minutes): deactivate A1's
    account, merge a copy of A1's customer into it, reinstate the account. *Look for:* it comes
    back **pending approval** with no customer, and appears under **Customer accounts →
    Accounts needing a customer**. **Re-link** it to A1's customer: read the history, tick, then
    **Re-link and activate**; A1 sees her shipments again. Then do it once more and **Close**
    it instead. *Should a re-link need a second person (B-17), and should the customer be told
    when the account is closed (B-19)?* Reset afterwards.
42. **`UAT-BLD-20`, `-21`, `-22`** (Operations, after a reset, 10 minutes): open the Nova
    Scotia draft of `UAT-AIR-DOM-NS` and read **As the invoice will show it**; send the New
    Brunswick draft and **Download PDF**; open `INV-000002`. *Look for:* each line shows its
    amount **before** tax with Tax **HST 14%** / **HST 15%** / **Zero-rated**; the summary
    **HST @ 14%**, **HST @ 15%**, **GST @ 0%**; the total is still the all-in total; on the PDF
    "Solaris Express Inc.", "Terms: Due on receipt", the E-transfer and BMO wire lines and "Thank
    you for your business! We accept payment via E-transfer to info@solarisexpress.ca"; English
    only, and Vietnamese names without accents. *Is a customer name without accents acceptable
    on the invoice (I-1)?*

## Part 10 — Your live UAT of 25 October (15 minutes), on a fresh reset

These check RC-UAT-25, the fixes for what you found on 25 October (OD-113): cases `UAT-BLD-26`
to `-33` of `AIR_UAT_PACK.md`; the stand-ins are in `19_OWNER_QUESTIONS.md` §000000.

43. **`UAT-BLD-26` to `-28`, `-30` to `-33`** (Operations, then Admin, 15 minutes):
    **Shipments → New** for A1. *Look for:* a red `*` beside each required label and no
    "(required)" (also on `/account/register`, in both languages); **Currency** is a list,
    **—**, **CAD — Canadian dollar**, **VND — Vietnamese dong**; on step 3 the **Recipient**
    card offers **Use a saved address**, with A1's address marked "(saved as sender)". Open
    `UAT-AIR-A1-2` → **Record event**: the event reads **Received at warehouse** with "We have
    received your shipment at our warehouse."; record it published, then **Edit** it (change
    the location, give a reason): the warning says no email is sent, the timeline shows
    **Edited** and **Edit history**, and no new file appears in `data\uat\account_mail`. Open
    any confirmed shipment's **Financials** tab and type Currency `CA`: refused with "Use a
    three-letter currency code such as CAD.", never a blank page; the **Quote and invoice**
    card names the next step, and **Quote & invoice** in the header opens it. *Should
    Vietnam ↔ Canada bookings default to CAD (RC25-A5), and should the recorded amounts be
    limited to CAD and VND too (RC25-C3)?*

## Finish (5 minutes)

- Fill in `UAT_SUMMARY.md` for the cases you ran (the air section) and list each
  `UAT-DEF-…` you raised.
- Note your answers, if any, to the open questions in
  `docs/b2c_merge/19_OWNER_QUESTIONS.md` (§0000 for the build of 24 October: P-9 and the
  stand-ins A-1 to A-14, B-1 to B-20, D-1 to D-12; §00000 for the invoices of RC-UAT-23,
  I-1 to I-13; §000000 for your live UAT of 25 October, RC25-A1 to A8, B1 to B13 and C1 to
  C7); each answer is a small, separate change.
- Stop both windows. To test again from the start, reset (`HOW_TO_RUN.md` §2).

The cases not on this route (`UAT-WSQ-05`, `-06`, `-07`, `UAT-QAC-03`, `-04`,
`UAT-FIN-01`, `-02`, `-04`, `-08`, `UAT-PRC-02` to `-04`, `UAT-TAR-04`, `-05`,
`UAT-MLS-03`, `-04`, `UAT-VIA-03`, `-04`, `UAT-OWN-03`, `-06` to `-08`, `-10`, `-11`,
`-14` to `-17`, `-20`, `-21`, `-24`, `-27`, `-32`, `UAT-BLD-07`, `-08`, `-10` (withdrawn) to
`-13`, `-16`, `-29`) are for the staff testers' full pass.
