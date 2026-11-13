# UAT summary sheet

> # ⚠ NOT EXECUTED
>
> **Every row below is blank because no case has been run.** This sheet is filled in
> during UAT, by the person performing each case, at the time they perform it.
>
> **Do not pre-fill any row. Do not sign the acceptance statement in advance.**

| Field | Value |
|---|---|
| Build / commit under test | |
| Environment | |
| UAT start date | |
| UAT end date | |
| Test lead | |

---

## Progress

| | Count |
|---|---:|
| Cases in the packs | **49** in `UAT_CASES.md`, below; **104** in `AIR_UAT_PACK.md`, below (36 from Phase 17, 17 `UAT-OWN` from RC-UAT-18, 10 `UAT-OWN` from RC-UAT-19, 8 `UAT-OWN` from RC-UAT-20, 17 `UAT-BLD` from RC-UAT-21 (`UAT-BLD-10` withdrawn in RC-UAT-25, still counted), 2 `UAT-BLD` from RC-UAT-22, 5 `UAT-BLD` from RC-UAT-23, 1 `UAT-BLD` from RC-UAT-24, 8 `UAT-BLD` from RC-UAT-25); the 60 Customer Account cases are summarised at the end of `CUSTOMER_ACCOUNT_UAT_PACK.md` |
| Executed | |
| Passed | |
| Failed | |
| Blocked | |
| Not run | |

---

## Results

`P` pass · `F` fail · `B` blocked · blank = not run

### Admin

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-AD-01 | Sign in, and the session ends as documented | | | | | |
| UAT-AD-02 | Wrong passwords pause sign-in | | | | | |
| UAT-AD-03 | Create a staff account and revoke it | | | | | |
| UAT-AD-04 | Merge two customers, with review | | | | | |
| UAT-AD-05 | Costs and profit are visible to Admin | | | | | |
| UAT-AD-06 | Integration infrastructure reads not_configured | | | | | |
| UAT-AD-07 | Audit log records a material change | | | | | |

### Operations

*Ten cases were added here by the Customer Service merge (DEC-0088): five renamed from
`UAT-CS-*`, five new for permissions Operations gained that no case exercised.
`UAT-OP-10` is a merge of the former `UAT-OP-10` and `UAT-CS-06`.
`docs/UAT/ROLE_MERGE_COVERAGE_MAP.md` maps every one.*

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-OP-01 | Book a shipment end to end | | | | | |
| UAT-OP-02 | A double-click does not create two bookings | | | | | |
| UAT-OP-03 | Editing an address does not change a confirmed shipment | | | | | |
| UAT-OP-04 | Three packages, three label pages | | | | | |
| UAT-OP-05 | Record a milestone and publish it | | | | | |
| UAT-OP-06 | Exception milestones do not publish by default | | | | | |
| UAT-OP-07 | One delivered package of three is partially delivered | | | | | |
| UAT-OP-08 | Add a manual tracking reference | | | | | |
| UAT-OP-09 | Cancel and rebook | | | | | |
| UAT-OP-10 | Revenue is visible; cost and profit are absent | | | | | |
| UAT-OP-11 | Create a customer with a Vietnamese name | | | | | |
| UAT-OP-12 | A near-duplicate is held for review, never merged | | | | | |
| UAT-OP-13 | Record consent, then a withdrawal | | | | | |
| UAT-OP-14 | Look up a shipment for a customer on the phone | | | | | |
| UAT-OP-15 | Complete a follow-up task | | | | | |
| UAT-OP-16 | Update a customer, then archive and restore one | | | | | |
| UAT-OP-17 | Tags and a referral | | | | | |
| UAT-OP-18 | Build and save a segment | | | | | |
| UAT-OP-19 | Edit a shipment's revenue | | | | | |
| UAT-OP-20 | The boundaries that did not move | | | | | |

### Marketing

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-MK-01 | Build a segment | | | | | |
| UAT-MK-02 | A suppressed customer is excluded from an audience | | | | | |
| UAT-MK-03 | Marketing cannot see costs or financial reports | | | | | |
| UAT-MK-04 | Marketing cannot bulk-export shipments | | | | | |

### Read-only manager

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-RM-01 | Everything is readable | | | | | |
| UAT-RM-02 | Nothing is editable | | | | | |
| UAT-RM-03 | Revenue visible, cost absent | | | | | |

### Cross-role

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-XX-01 | Public tracking, successful lookup | | | | | |
| UAT-XX-02 | Public tracking, unknown reference | | | | | |
| UAT-XX-03 | Import a customer list | | | | | |
| UAT-XX-04 | Import the same file twice | | | | | |
| UAT-XX-05 | An import duplicate is decided, never merged | | | | | |
| UAT-XX-06 | A bad file is refused clearly | | | | | |
| UAT-XX-07 | Export a CSV and read it | | | | | |
| UAT-XX-08 | A formula in a name cannot execute | | | | | |
| UAT-XX-09 | Reports count shipments once | | | | | |
| UAT-XX-10 | Reports refuse an impossible range | | | | | |
| UAT-XX-11 | A report is a shareable link | | | | | |
| UAT-XX-12 | Keyboard only | | | | | |
| UAT-XX-13 | Usable on a phone | | | | | |
| UAT-XX-14 | Vietnamese interface reads correctly | | | | | |
| UAT-XX-15 | Staff data is never visible to the public | | | | | |

### Air pricing, quotes and money (`AIR_UAT_PACK.md`, Phase 17)

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-WSQ-01 | Read the vendor cost and add a surcharge to an open master | | | | | |
| UAT-WSQ-02 | Confirm the rate, finalise, and print the customer quote | | | | | |
| UAT-WSQ-03 | Send a finalised quote to a customer without an account | | | | | |
| UAT-WSQ-04 | A newer version withdraws an unanswered quote | | | | | |
| UAT-WSQ-05 | Book a master and publish a master milestone | | | | | |
| UAT-WSQ-06 | Cancel a master | | | | | |
| UAT-WSQ-07 | Who may open the Workspace | | | | | |
| UAT-QAC-01 | A1 reads and accepts a quote, in Vietnamese | | | | | |
| UAT-QAC-02 | An accepted quote's invoice waits as a draft; staff send it | | | | | |
| UAT-QAC-03 | A newer price after acceptance, and an English decline | | | | | |
| UAT-QAC-04 | One customer cannot reach another's quote | | | | | |
| UAT-FIN-01 | Issue an invoice and choose GST/HST | | | | | |
| UAT-FIN-02 | Record a CAD payment, and never more than the balance | | | | | |
| UAT-FIN-03 | A payment in VND at the selling rate | | | | | |
| UAT-FIN-04 | Refunds and voids | | | | | |
| UAT-FIN-05 | Vendor bills: variance, reason and the cost split | | | | | |
| UAT-FIN-06 | Receivables, Payables and Profitability agree with the records | | | | | |
| UAT-FIN-07 | M+7: a closed month, a refused back-dated entry, reopen and close | | | | | |
| UAT-FIN-08 | Finance permissions | | | | | |
| UAT-PRC-01 | Read the pricing settings; only Admin saves | | | | | |
| UAT-PRC-02 | Changing the default markup reaches drafts, not finalised quotes | | | | | |
| UAT-PRC-03 | A per-surcharge policy overrides the default | | | | | |
| UAT-PRC-04 | Air Express has no default rate | | | | | |
| UAT-TAR-01 | The tariff browser is read-only for Operations | | | | | |
| UAT-TAR-02 | Approve the draft from the allowed vendor | | | | | |
| UAT-TAR-03 | A held email: release, then reject | | | | | |
| UAT-TAR-04 | Upload a rate email, and the same email twice | | | | | |
| UAT-TAR-05 | The approver list | | | | | |
| UAT-MLS-01 | The outbox explains every email | | | | | |
| UAT-MLS-02 | A master milestone notifies each customer in their language | | | | | |
| UAT-MLS-03 | Staff change a customer's milestone choices | | | | | |
| UAT-MLS-04 | An unpublished milestone notifies nobody | | | | | |
| UAT-VIA-01 | Vietnamese first, English on every screen | | | | | |
| UAT-VIA-02 | Shipment updates in the customer's language | | | | | |
| UAT-VIA-03 | An English customer turns a milestone back on | | | | | |
| UAT-VIA-04 | The language saved in the profile reaches the emails | | | | | |

### Owner answers of 2026-10-21 (`AIR_UAT_PACK.md`, RC-UAT-18)

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-OWN-01 | A booked master locks its items and fees | | | | | |
| UAT-OWN-02 | Only an Admin unlocks, and only with a reason | | | | | |
| UAT-OWN-03 | Edit while unlocked, then lock again | | | | | |
| UAT-OWN-04 | Finalising a member's quote relocks the master by itself | | | | | |
| UAT-OWN-05 | A new tariff expires a quote whose goods are not yet received | | | | | |
| UAT-OWN-06 | Expiry withdraws the draft invoice and spares an issued invoice | | | | | |
| UAT-OWN-07 | Re-quote after expiry | | | | | |
| UAT-OWN-08 | Accepting a quote prepares its invoice as a draft | | | | | |
| UAT-OWN-09 | Unsaved changes: save first | | | | | |
| UAT-OWN-10 | A changed total needs a reason; GST/HST is checked on the draft | | | | | |
| UAT-OWN-11 | Two people edit the same draft | | | | | |
| UAT-OWN-12 | Download the draft, then send the invoice | | | | | |
| UAT-OWN-13 | The import report lists the confirmed price steps | | | | | |
| UAT-OWN-14 | HCM meat / egg / dairy / honey at 20,000 VND/kg | | | | | |
| UAT-OWN-15 | No vendor name reaches the customer | | | | | |
| UAT-OWN-16 | Air Express: a typed rate and reason, then finalise | | | | | |
| UAT-OWN-17 | The rate-email mailbox and approver | | | | | |

### Owner answers of 2026-10-22 (`AIR_UAT_PACK.md`, RC-UAT-19)

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-OWN-18 | A Vietnam → Canada draft starts at GST/HST 0 %, zero-rated by route | | | | | |
| UAT-OWN-19 | Save and Send wait for the GST/HST check | | | | | |
| UAT-OWN-20 | Changing the rate, the mode or a line clears the check | | | | | |
| UAT-OWN-21 | GST/HST 5 %, added on top | | | | | |
| UAT-OWN-22 | The issued invoice of a Vietnam → Canada move: GST/HST 0 %, nothing included | | | | | |
| UAT-OWN-23 | A last-mile link reads "Last Mile Tracking", never a vendor's name | | | | | |
| UAT-OWN-24 | A Vietnam-side link reads "Master Tracking"; a link on the vendor's own site stays hidden | | | | | |
| UAT-OWN-25 | Costume jewellery: two empty fields for the line, and no finalising without both | | | | | |
| UAT-OWN-26 | Costume jewellery: the cost from the VND entered, the charge exactly the CAD price | | | | | |
| UAT-OWN-27 | Costume jewellery: neither value can be entered on a locked master | | | | | |

### Owner answers of 2026-10-23 (`AIR_UAT_PACK.md`, RC-UAT-20)

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-OWN-28 | Domestic drafts: NS 14 % and NB 15 % HST filled in and backed out; an unknown province waits for staff | | | | | |
| UAT-OWN-29 | Settings → GST/HST rates: only Admin edits, and the rate lists follow | | | | | |
| UAT-OWN-30 | Download PDF (draft) waits for the GST/HST check, like Send | | | | | |
| UAT-OWN-31 | A payment's received date stays the date entered | | | | | |
| UAT-OWN-32 | Costume jewellery: both values on Add fee, and the customer pays exactly the price | | | | | |
| UAT-OWN-33 | The final delivery leg offers the vendor; each leg shows its generic tracking name | | | | | |
| UAT-OWN-34 | Settings → Tariffs shows the 39 import warnings and the 3 confirmed price steps | | | | | |
| UAT-OWN-35 | The wording kept: "Tổng cộng" with the GST/HST line, and "Ghi chú từ Solaris Express" | | | | | |

### Build of 2026-10-24 (`AIR_UAT_PACK.md`, RC-UAT-21)

| Case | Title | Tester | Date | Result | Defect | Notes |
|---|---|---|---|:---:|---|---|
| UAT-BLD-01 | Import type navigation and the two new templates | | | | | |
| UAT-BLD-02 | Shipment dry run: each bad row is named, and nothing is written | | | | | |
| UAT-BLD-03 | Import only after a matching dry run | | | | | |
| UAT-BLD-04 | Duplicates are refused, and a second import needs a new dry run | | | | | |
| UAT-BLD-05 | Legacy history: a dry run with a cutoff date, then the baseline | | | | | |
| UAT-BLD-06 | Legacy records are staff-only, and stay out of every list and the customer's account | | | | | |
| UAT-BLD-07 | Void a legacy baseline, then import the same history again | | | | | |
| UAT-BLD-08 | A customer changes their password, in Vietnamese | | | | | |
| UAT-BLD-09 | Customer cannot change the sign-in email; an Admin changes it | | | | | |
| UAT-BLD-10 | Withdrawn (RC-UAT-25 item 2) | | | | | |
| UAT-BLD-11 | A staff member changes their own password | | | | | |
| UAT-BLD-12 | Admin reinstates a deactivated account | | | | | |
| UAT-BLD-13 | Reinstating after a merge returns the account to pending approval | | | | | |
| UAT-BLD-14 | The customer quote's GST/HST line follows the invoice rule (OD-109 stand-in) | | | | | |
| UAT-BLD-15 | Admin deletes an old quote version, and restores it | | | | | |
| UAT-BLD-16 | What cannot be deleted; a deleted version cannot be sent; who sees the panel | | | | | |
| UAT-BLD-17 | Settings → Retention: everything off; dry run only | | | | | |
| UAT-BLD-18 | Admin re-links an account left without a customer (B-13) | | | | | |
| UAT-BLD-19 | Admin closes an account left without a customer, and can reinstate it | | | | | |
| UAT-BLD-20 | A Nova Scotia draft shows the invoice line by line (HST 14 %) | | | | | |
| UAT-BLD-21 | Send the New Brunswick draft: stored nets, the invoice detail and the desk's PDF | | | | | |
| UAT-BLD-22 | Zero-rated international invoices: `INV-000002` and `INV-000003` | | | | | |
| UAT-BLD-23 | Manual Issue invoice at 13 %: added on top, per line, on the new layout | | | | | |
| UAT-BLD-24 | Terms follow Invoice terms; back to Due on receipt | | | | | |
| UAT-BLD-25 | The legal entity reads Solaris Express Inc. (I-10); the draft editor's wording (I-11) | | | | | |
| UAT-BLD-26 | Required fields show a red asterisk, no "(required)" words | | | | | |
| UAT-BLD-27 | Create booking: the declared value currency is a list (CAD, VND) | | | | | |
| UAT-BLD-28 | Create booking: the recipient can use a saved address | | | | | |
| UAT-BLD-29 | A link from the old self-service email change no longer works | | | | | |
| UAT-BLD-30 | The received event now reads "Received at warehouse" | | | | | |
| UAT-BLD-31 | Edit an event already published to the customer | | | | | |
| UAT-BLD-32 | Financials loads after financial info is added | | | | | |
| UAT-BLD-33 | Invoice the client right after booking | | | | | |

---

## Defects raised

| ID | Case | Severity | Summary | Status | Closed by | Date |
|---|---|---|---|---|---|---|
| | | | | | | |

**Status:** Open · Triaged · Fixed · **Retested** · Closed · Accepted · Not a defect

---

## Outstanding at sign-off

Every defect not closed, with the decision made about it. **An S1 may not appear here at
all.** An S2 may appear only with a written owner acceptance and a workaround.

| ID | Severity | Summary | Decision | Workaround | Accepted by |
|---|---|---|---|---|---|
| | | | | | |

---

## Not covered by this UAT

Carry forward; none of these is closed by UAT passing.

| Item | Why |
|---|---|
| ShipStation / carrier integration | No provider connected (DEC-0075). Deferred to the final phase |
| Physical label print and scan | Needs the real thermal printer and handheld scanner |
| Real customer data | Synthetic only |
| Load at scale | Measured separately |
| Screen-reader testing | `docs/ACCESSIBILITY.md` section 6 — still open |
| Off-site backup and disaster recovery | Not configured |
| Vietnamese copy approval | The owner accepted the wording as is (OD-85, 2026-10-21) and approved the leg names (OD-104, 2026-10-23); UAT-XX-14 and `UAT-VIA-*` still gather findings as S5 |
| Quoting a domestic shipment on screen | An air master takes only Vietnam → Canada shipments; the seed places three domestic shipments on their own master (`UAT-DOM-AWB`) for UAT only, so their drafts can be tested (`UAT-OWN-28`) |
| A vendor mailbox; a live exchange rate | Not connected in UAT (OD-87: Ben's address is the default mailbox, no live mailbox yet); every rate is a demo reading |
| Production email provider | Test capture only (OD-34) |
| Retention deletion | Built but off; UAT only dry-runs it (`UAT-BLD-17`). Periods undecided (OD-01, OD-36); enabling needs the owner's written approval |
| Returns, staff MFA, provider sync | Not started; waiting for Ben (OD-22, OD-17, OD-21; OD-110) |
