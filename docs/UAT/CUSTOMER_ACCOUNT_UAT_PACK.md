# Customer Account UAT pack

> **⚠ NOT EXECUTED.** Every **Evidence obtained**, **Result**, **Defect**, **Tester**,
> **Date** and sign-off field below is blank and must stay blank until somebody performs
> the step. **No human has executed any case in this pack.** Claude did not fill in any of
> them and must not.
>
> **Two kinds of field, and the difference matters.** **Evidence to capture** is written
> in advance: it tells the tester what to collect, and it is part of the case definition,
> not a record of anything. **Evidence obtained** is what the tester actually captured,
> and it starts blank. A prewritten instruction must never be read, counted or reported as
> evidence that a case was executed.
>
> **What changed at Phase 12: the screens exist.** Every case that used to say "open the
> approval queue" or "open My shipments" against nothing now names a screen a tester can
> open. The pack is executable end to end in UAT, with the exceptions below — and
> "executable" is the only thing that changed. No result was recorded.
>
> | Group | Executable today? |
> |---|---|
> | `CA-REG-*` | **Yes**, against the Customer Account at `/account/register`. Mail is read from the development capture — `docs/OPERATIONS.md` §15 is the procedure |
> | `CA-APR-*` | **Yes**, against the Staff Portal at `/customer-accounts` |
> | `CA-SHP-*` | **Yes**, against `/account/shipments` |
> | `CA-PRF-*` | **Yes**, since the owner authorised the screens: **Hồ sơ của tôi** / My profile (fix pack 2, DEC-0123) and **Thông báo** / Notifications (Phase 13F, OD-72). See the banner above those cases |
> | `CA-SEC-*`, `CA-XP-*` | **Yes** |
>
> **Do not mark a case Pass on the strength of an API call.** Every case here describes
> what a person sees; execute it that way.

**Every case uses synthetic data.** Reuse the `example.com` identities from
`docs/UAT/UAT_CASES.md` and append your initials and the date. **Never substitute a real
customer.**

**How to fill a case in:** collect what **Evidence to capture** names, record what you
actually captured in **Evidence obtained**, enter `Pass`, `Fail` or `Blocked` in
**Result**, and put the defect id in **Defect** if it failed.

**Terminology.** *Customer Account* is this new authenticated surface. *Staff Portal* is the
internal CRM. *Public Tracking* is the existing unauthenticated page. Do not call the
Customer Account "the portal".

---

## Blocked by an open owner decision

| Blocked by | What is blocked |
|---|---|
| **OD-34** — production email provider | Production execution of every `CA-REG-*` and `CA-REC-*` case. Local execution uses the development capture |
| **OD-37** — approved terms and privacy text | Production execution of registration. Local execution uses placeholder versions, **clearly marked as placeholders** |
| **OD-19** — accessibility reviewer | `REVIEW_customer_account_copy.md` and the accessibility review |
| **OD-22** — return workflow | Any case about a linked return **record**. Return *statuses* are in scope |
| **OD-01** — retention | Any case about canonical deletion. None is proposed |

---

## Prerequisites for the whole pack

| | |
|---|---|
| Environment | UAT, seeded. Since the 2026-10-14 fix pack the seed itself supplies what this pack needs: the test people P1–P5 from `UAT_CASES.md`; P1 with an in-transit, a cancelled and a cancelled-and-rebooked shipment; one customer with 28 shipments for paging; and **non-demo** shipments for `STCA-000001`, which is what a linked account can actually see (demo records are excluded). Since UAT round 3 one of those is the late-evening booking `CA-SHP-10` needs, booking reference `UAT-CA-SHP-10` |
| Staff accounts | One Operations, one Admin |
| Mail | Development capture only. **No real address is ever entered** |
| Language | **Vietnamese first**, with an English switch at the top of every screen; a signed-in customer's saved language applies at sign-in (OD-71, which replaced the English-only release of OD-39). The Vietnamese wording has not been reviewed by a native speaker (`19_OWNER_QUESTIONS.md` question #6) |
| How to start it | `docs/UAT/ENVIRONMENT.md` **section 3a**. The backend must be started with `ACCOUNT_EMAIL_TRANSPORT=capture`; the default transport produces no message and registration will look as though it worked |
| Customer accounts in the seed | **Two, and not for this pack.** Since Phase 17 the seed links A1 (`trang.air@example.com`) and A2 (`emily.air@example.com`) for `AIR_UAT_PACK.md`; they appear in **Customer accounts** as already approved. This pack still creates its own: `CA-REG-01` creates the first one and `CA-APR-*` approves it, so run the pack in order on a fresh reset and never use A1 or A2 for it |
| Account features of RC-UAT-21 | The customer's own password change, the Admin's change of a customer's sign-in email (customers cannot change it, RC-UAT-25), Admin reinstatement of a deactivated account and the quote's GST/HST line (DEC-0231, DEC-0232; built on Ben's direction of 2026-10-24, OD-110) are tested in `AIR_UAT_PACK.md`, `UAT-BLD-08` to `-14`, on the seeded A1 and A2 accounts (`UAT-BLD-10` withdrawn in RC-UAT-25). This pack's 60 cases and their count are unchanged; since RC-UAT-21 a deactivation is no longer final unless it was for a privacy request (B-5), which no case here relies on |

---

# Registration and verification — `CA-REG-*`

### CA-REG-01 — Register a new account

| | |
|---|---|
| **Role** | Customer (not signed in) |
| **Prerequisites** | An address never used before, in `example.com` |
| **Data** | P1 details |
| **Steps** | 1. Open the Customer Account. 2. Leave the **Address** section empty, fill everything else, and press **Create account**. 3. Fill the address (country, line 1, city, province or state) and leave **Postal code** empty, then look at the billing section. 4. Type `12345` in **Postal code** and press **Create account**; change the country to United States, type `9810` in **ZIP code** and press it again; change the country back to Canada and type `l4w1v2` (lower case, no space). 5. Untick "Billing address is the same as the address above", type `98101` in the billing **Postal code**, and press **Create account**; then clear it and tick the box again. 6. Type a different password in **Confirm password** and press **Create account**. 7. Correct it and submit. 8. Read the response. 9. Open the mail capture. 10. As Operations, open the application. |
| **Expected** | The first section is headed **Address** (not "Shipping address") and comes **before** billing; its Country (already on Canada), Address line 1, City and Province or state are marked "(required)", and Postal code, Address line 2 and the driver fields "(optional)"; the last driver field reads "Notes for driver (buzz code, contact concierge, security,...)". "Billing address is the same as the address above" is **ticked when the page opens** and the billing fields are hidden. Step 2: an error beside each empty required part ("Enter the street address (address line 1).", "Enter the city.", "Enter the province or state."), each listed and linked in the error summary, **no billing error and no postal code error**, and nothing is sent (no message in the capture). Step 3: the box is still ticked and the billing fields hidden; the empty postal code is not an error. Step 4: "Enter the postal code as A1A 1A1, or leave it blank." beside Postal code and in the summary; for the United States "Enter the ZIP code as 12345 or 12345-6789, or leave it blank." beside ZIP code; nothing sent either time; `l4w1v2` is accepted (DEC-0165). Step 5: **empty** billing fields, the same four marked "(required)" and Postal code "(optional)", an error beside each empty required one ("Enter the billing city." and so on), and "Enter the billing postal code as A1A 1A1, or leave it blank." beside the billing postal code, nothing sent; ticking hides them again. Step 6: "The two passwords do not match." beside Confirm password, listed in the error summary, and nothing is sent. Step 8: a generic "if that address can be registered…" response; exactly one verification message in the capture; **no canonical customer created or changed**. Step 10: the billing address equals the address, and both have the postal code `l4w1v2` exactly as typed (DEC-0145, DEC-0146, DEC-0150 to DEC-0152, DEC-0158, DEC-0159, DEC-0165) |
| **Privacy / permission** | The response reveals nothing about whether the address or a matching customer exists |
| **Evidence to capture** | Screenshots of steps 2 to 6 and of the response; the captured message; the application's address rows; a Staff Portal screenshot showing no new customer |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-REG-02 — Register with an address that already has an account

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | CA-REG-01 completed |
| **Data** | The same address |
| **Steps** | 1. Register again with the same address. 2. Compare the response with CA-REG-01 word for word — status, body and headers. 3. Open the capture. |
| **Expected** | **Identical** response; at most one "somebody tried to register" notice; no second account |
| **Privacy / permission** | Enumeration must be impossible from the response |
| **Evidence to capture** | Both responses side by side |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-REG-03 — Register with an address that matches an existing customer exactly

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | A canonical customer with a known `example.com` address |
| **Data** | That address |
| **Steps** | 1. Register. 2. Read the response. 3. In the Staff Portal, open the approval queue. |
| **Expected** | Generic response; a **pending** identity and a **pending proposal**; **no automatic link and no merge**; the canonical customer is untouched |
| **Privacy / permission** | The customer is told nothing about the match |
| **Evidence to capture** | Queue screenshot; customer record before and after |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-REG-04 — Terms acknowledgement is required and recorded

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | — |
| **Data** | A fresh address |
| **Steps** | 1. Attempt to register without acknowledging terms. 2. Acknowledge and register. 3. Ask staff to show the stored acknowledgement. |
| **Expected** | Refused without acknowledgement; the stored record carries version, language and timestamp; **the box was not pre-checked** |
| **Privacy / permission** | Acknowledgement is separate from marketing consent |
| **Evidence to capture** | Screenshot of the unchecked default; the stored record |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-REG-05 — Marketing consent is separate and unchecked

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | — |
| **Data** | A fresh address |
| **Steps** | 1. Register **without** ticking marketing consent. 2. Ask staff to show the consent history. |
| **Expected** | No marketing consent recorded; the operational preferences are unaffected; the two controls are visibly separate |
| **Privacy / permission** | No implied consent anywhere |
| **Evidence to capture** | Screenshot of the form; consent history |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-REG-06 — Verify the email address

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | CA-REG-01 |
| **Data** | The captured verification link |
| **Steps** | 1. Open the link. 2. Open it a second time. 3. Sign in. |
| **Expected** | First use verifies; **second use is refused**; sign-in works and shows "waiting for review" |
| **Privacy / permission** | A verified account still sees **no** shipment history |
| **Evidence to capture** | Both responses; the post-sign-in screen |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-REG-07 — An expired verification link is refused

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | A link older than its expiry. The operator ages the outstanding link with `scripts/expire_account_link.py <address>` (`docs/UAT/ENVIRONMENT.md` section 3b); nobody waits 24 hours |
| **Steps** | 1. Open the expired link. 2. Request a new one. 3. Open the new one. |
| **Expected** | Expired link refused with the standard generic message; the new link works; **the old one still does not** |
| **Privacy / permission** | The refusal reveals nothing about the account |
| **Evidence to capture** | Screenshots of both refusals |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-REG-08 — Registration flooding is limited

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | — |
| **Steps** | 1. Register repeatedly for one address, past the documented limit. 2. Count the captured messages. 3. In another browser, sign in to the **Staff Portal**. |
| **Expected** | The response stays generic throughout; messages stop at the limit; **staff sign-in is unaffected** |
| **Privacy / permission** | A customer-side flood cannot lock staff out |
| **Evidence to capture** | Capture contents; successful staff sign-in |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Approval and linking — `CA-APR-*`

### CA-APR-01 — Operations approves an account and links it

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A verified pending identity (CA-REG-06) |
| **Steps** | 1. Open the approval queue. 2. Read the proposed values, the current values and the normalized values. 3. Read the history disclosure preview. 4. Acknowledge it. 5. Approve and link to one customer. |
| **Expected** | Approval succeeds only after the acknowledgement; the identity becomes active; exactly one active link exists |
| **Privacy / permission** | The preview states the count, the oldest and newest dates, and whether cancelled/rebooked are included |
| **Evidence to capture** | Screenshot of the preview; the audit entry |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-APR-02 — Approval cannot be completed without acknowledging the disclosure

| | |
|---|---|
| **Role** | Operations |
| **Steps** | 1. Open a pending identity. 2. Attempt to approve without acknowledging the preview. |
| **Expected** | Refused, with a clear explanation. Nothing changes |
| **Privacy / permission** | The size of the disclosure is always seen before it is granted |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-APR-03 — A second account for the same customer is refused

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | CA-APR-01, plus a second registration naming the same customer |
| **Steps** | 1. Attempt to approve and link the second identity to the same customer. |
| **Expected** | Refused: one active identity per canonical customer in release 1 (OD-25). (The exception is a customer whose account was **deactivated**: the preview names it and approving ends its link, DEC-0140) |
| **Privacy / permission** | The refusal message to staff may name the conflict; **no customer-facing response does** |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-APR-04 — A near-duplicate registration enters the existing review

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A registration resembling P1 but not identical (use P4) |
| **Steps** | 1. Open the pending identity. 2. Read the duplicate implications. 3. Decline the link. |
| **Expected** | The **existing** duplicate review is used; **nothing is merged automatically**; declining changes no canonical data |
| **Privacy / permission** | Scores and candidates are staff-facing only |
| **Evidence to capture** | Review screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-APR-05 — Admin can approve as an override

| | |
|---|---|
| **Role** | Admin |
| **Steps** | 1. Approve a pending identity as Admin. 2. Open the audit log. |
| **Expected** | Approval succeeds; the audit entry names Admin as the actor and records the override |
| **Privacy / permission** | The payload has a reason code, no credentials |
| **Evidence to capture** | Audit entry |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-APR-06 — Rejection is neutral to the customer

| | |
|---|---|
| **Role** | Operations, then Customer |
| **Steps** | 1. Reject a pending identity with a reason code. 2. Sign in as that customer. |
| **Expected** | Neutral wording; **no reason that describes another customer record**; no shipment data |
| **Privacy / permission** | Rejection discloses nothing about the CRM |
| **Evidence to capture** | Both screens |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |


### CA-APR-07 — The disclosure preview states the right figures

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A verified pending identity, and a canonical customer with several shipments including **one cancelled** and **one rebooked**, plus one **draft** and one **demo** record |
| **Data** | P1 identity, P2 customer |
| **Steps** | 1. Open the pending identity. 2. Take a link preview against P2. 3. Compare the five figures with the shipments actually on P2. |
| **Expected** | Count matches the confirmed, non-demo shipments; oldest and newest match their booking dates; cancelled included is true; rebooked included is true. **The draft and the demo record are not counted** |
| **Privacy / permission** | The preview names no shipment, no recipient, no package and no money |
| **Evidence to capture** | Screenshot of the preview beside the Staff Portal shipment list for P2 |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-08 — A shipment that only *looks* like the applicant's is not counted

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A shipment belonging to customer P3 whose **sender email and name match the applicant exactly** |
| **Steps** | 1. Take a create-new preview for the applicant. 2. Read the disclosure count. |
| **Expected** | Zero. Ownership is the canonical shipper relationship and nothing else (OD-29) |
| **Privacy / permission** | Matching contact details grant no visibility |
| **Evidence to capture** | Preview screenshot; the P3 shipment record |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-09 — A preview that has gone stale is refused

| | |
|---|---|
| **Role** | Operations, plus a second person acting as Operations |
| **Steps** | 1. Take and acknowledge a link preview against P2. 2. Have the second person edit P2 — change the city. 3. Attempt the approval. 4. Take a fresh preview, acknowledge it, approve. |
| **Expected** | Step 3 is refused as out of date and **nothing changes**. Step 4 succeeds |
| **Privacy / permission** | The refusal names no third party |
| **Evidence to capture** | Both responses; the audit entry for the refusal |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-10 — A new shipment between preview and approval is also drift

| | |
|---|---|
| **Role** | Operations |
| **Steps** | 1. Take and acknowledge a link preview against P2. 2. Book and confirm a shipment for P2. 3. Attempt the approval. |
| **Expected** | Refused. The reviewer agreed to a disclosure of a particular size, and it grew |
| **Privacy / permission** | The size of a disclosure is always seen before it is granted |
| **Evidence to capture** | Both responses |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-11 — Creating a separate customer despite a match needs a reason

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A registration whose email exactly matches an existing customer |
| **Steps** | 1. Read the duplicate candidates. 2. Attempt create-new with no reason. 3. Retry with a reason code. |
| **Expected** | Step 2 refused, naming the missing reason and **creating nothing**. Step 3 succeeds and the override is its own audit entry |
| **Privacy / permission** | The reason is a bounded code, never free prose about the person |
| **Evidence to capture** | Both responses; the override audit entry |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-12 — Linking to a merged or archived customer is refused

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | One merged customer and one archived customer |
| **Steps** | 1. Attempt to link the applicant to the merged reference. 2. Attempt to link to the archived one. |
| **Expected** | Both refused. The merged refusal **names the surviving record** and does not link to it automatically |
| **Privacy / permission** | Staff may be told which record survived; no customer-facing response is |
| **Evidence to capture** | Both responses |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-13 — Linking changes nothing on the existing customer but its email

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A registration whose submitted name, phone, city and email all **differ** from the customer being linked |
| **Steps** | 1. Note every field on the customer. 2. Link the account to it. 3. Compare every field. 4. Open **Edit** on the customer and try to change the email. 5. As an administrator, deactivate the account (Customer accounts → the application → Account status). 6. Open **Edit** again and change the email. |
| **Expected** | Nothing on the customer changed **except the email**, which is now the account's sign-in email, as the preview said before the acknowledgement (one email per customer, DEC-0138). The other differences are recorded and applied to nothing (OD-28). Step 4: the email field is read-only and says "This is the sign-in email of the customer's account, which is active or suspended. To change it, deactivate the account first."; other fields still save. Step 6: the email saves (DEC-0142) |
| **Privacy / permission** | A registration is not an edit |
| **Evidence to capture** | Before and after screenshots of the customer record; the link audit entry |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-14 — Retrying a lost approval approves once

| | |
|---|---|
| **Role** | Operations |
| **Steps** | 1. Approve with a given idempotency key. 2. Send the identical request again with the same key. 3. Count customers, links, audit entries and captured messages. |
| **Expected** | One customer, one link, one approval audit entry, one message. The second response reports a replay |
| **Privacy / permission** | — |
| **Evidence to capture** | Both responses; the mail capture |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-15 — Marketing and the read-only manager reach none of it

| | |
|---|---|
| **Role** | Marketing, then Read-only manager |
| **Steps** | 1. As each role, attempt the queue, one application, its duplicates, a preview, an acknowledgement, both approvals and a rejection. 2. Check the database. |
| **Expected** | Every attempt refused. **No customer, link, acknowledgement or approval record is created by any of them** |
| **Privacy / permission** | Holding `duplicate:review` grants none of this |
| **Evidence to capture** | The refusals; a Staff Portal screenshot showing no new customer |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-16 — A rejected applicant cannot sign in, and is told nothing

| | |
|---|---|
| **Role** | Operations, then Customer |
| **Steps** | 1. Sign the applicant in and keep the session. 2. Reject the application. 3. Reload as the customer. 4. Attempt to sign in again. 5. Attempt the reset link from before the rejection. |
| **Expected** | The live session stops working on the next request; sign-in is refused with the **same wording as a wrong password**; the old reset link no longer works |
| **Privacy / permission** | No reason code reaches the customer, in any response or message |
| **Evidence to capture** | All four responses; the rejection notice from the capture |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

### CA-APR-17 — An approved account reports that shipment history is available

> **Rewritten in the 2026-10-14 fix pack.** This case was written in Phase 10, when no
> shipment route existed, and asserted that an approved account "reports no shipment
> history". Phase 11 built the route and Phase 12 the screen, so the old expectation
> contradicted `CA-SHP-02` and could only fail. The bot-executed run of 2026-10-14
> reported it as such. The case now tests the account-state answer that `CA-SHP-02` then
> relies on: the flag that says history is available is true exactly when the shipment
> routes would allow it, and false otherwise.

| | |
|---|---|
| **Role** | Customer, after CA-APR-01 |
| **Prerequisites** | Linked to a customer that **has** at least one non-demo shipment (the seed gives `STCA-000001` one) |
| **Steps** | 1. Sign in. 2. Read the account state (`GET /api/v1/account/me`, or the pending card if one shows). 3. Open "My shipments". 4. As staff, suspend the account (Customer accounts → the application → Account status). 5. As the customer, reload. |
| **Expected** | Step 2: `status` is `active`, `linked` is true and `shipment_history_available` is true; the response carries **no** customer ID, count or date. Step 3: the list opens. Step 5: the session ends on the next request and sign-in is refused with the same wording as a wrong password |
| **Privacy / permission** | `shipment_history_available` is answered by the same rule the shipment routes apply, so the account state can never promise a list the routes refuse |
| **Evidence to capture** | The account-state response; the list; the refusal after suspension |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
| **Tester** | |
| **Date** | |

---

# Shipment visibility — `CA-SHP-*`

### CA-SHP-01 — A pending account sees no shipment history

| | |
|---|---|
| **Role** | Customer, `pending_approval` |
| **Steps** | 1. Sign in. 2. Look for shipments. 3. Request the shipments URL directly. |
| **Expected** | No list, no link, and a direct request is refused |
| **Privacy / permission** | Approval is the gate, not the menu |
| **Evidence to capture** | Screenshot; the direct request's response |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-02 — An approved account sees its own shipments

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | CA-APR-01, linked to a customer with several shipments |
| **Steps** | 1. Open "My shipments". 2. Compare with the Staff Portal list for that customer. |
| **Expected** | Every shipment of that customer appears, and nothing else; the count matches the approval preview |
| **Privacy / permission** | Only the documented list fields appear |
| **Evidence to capture** | Both lists side by side |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-03 — Another customer's shipment is not reachable

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | A reference belonging to a **different** customer |
| **Steps** | 1. Request that reference in the authenticated detail view. 2. Request a reference that does not exist at all. 3. Compare the two responses. |
| **Expected** | **Identical** refusals. Possession of a reference grants nothing |
| **Privacy / permission** | The core ownership boundary (OD-29) |
| **Evidence to capture** | Both responses |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-04 — Cancelled and rebooked shipments stay visible with safe states

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | The linked customer has one cancelled and one rebooked shipment |
| **Steps** | 1. Open the list. 2. Open each of the two. |
| **Expected** | Both appear, clearly marked; the cancelled one shows its cancellation; the rebooked one is marked without disclosing the replacement's reference |
| **Privacy / permission** | Nothing vanishes silently |
| **Evidence to capture** | Screenshots |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-05 — The authenticated detail carries exactly the documented fields

| | |
|---|---|
| **Role** | Customer, active |
| **Steps** | 1. Open a shipment that Operations booked with a booking reference (for example `PO-BAKERY-4471`), then one booked without. 2. Compare every visible field against `SHIPMENT_ALLOWLISTS.md` §4. 3. Compare with the Public Tracking page for the same shipment. |
| **Expected** | The 24 values Public Tracking shows, plus **Booking reference** as the first fact under "Where it is": the reference typed at booking, or "Not recorded" for the shipment without one (DEC-0163). Nothing more. Public Tracking for the same shipment does **not** show the booking reference. **No financial value anywhere** |
| **Privacy / permission** | OD-31, OD-32 |
| **Evidence to capture** | Annotated screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-06 — Public Tracking is unchanged

| | |
|---|---|
| **Role** | Anyone, signed out |
| **Steps** | 1. Track the same reference publicly. 2. Compare with `UAT-XX-01`. |
| **Expected** | Identical behaviour to the existing pack. The Customer Account has not altered Public Tracking |
| **Privacy / permission** | The 24-field contract did not move; it never shows a booking reference (DEC-0163 widens the Customer Account detail only) |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

## Added by Phase 11 — `CA-SHP-07` … `CA-SHP-18`

> **Executable from Phase 12.** These were written against routes with no screen; the
> screens exist now, at `/account/shipments` and `/account/shipments/<id>`, and every step
> below can be performed by a person.
>
> Every **Result**, **Defect**, **Tester**, **Date** and **Evidence** field is blank and
> stays blank.

### CA-SHP-07 — An approved account with no shipments sees an empty list, not an error

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | Linked to a canonical customer that has **no** qualifying shipments |
| **Steps** | 1. Open "My shipments". 2. Read what the screen says. |
| **Expected** | A plain sentence saying there is nothing to show. No error, no retry prompt, and nothing suggesting shipments might exist elsewhere |
| **Privacy / permission** | An empty answer is a legitimate answer, and must not hint at another record |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-08 — Drafts and demo records never appear

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | The linked customer has one draft booking and one demo record, plus at least one confirmed shipment |
| **Steps** | 1. Open "My shipments". 2. Compare with the Staff Portal list for that customer. 3. Ask staff for the draft's internal identifier and request it directly. |
| **Expected** | Neither the draft nor the demo record is listed, and a direct request for either is refused with the same message as an unknown reference |
| **Privacy / permission** | A draft is internal work in progress (OD-29) |
| **Evidence to capture** | Both lists; the direct request's response |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-09 — Filtering by status group

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | The linked customer has shipments in at least three states, including one delivered and one cancelled |
| **Steps** | 1. Filter to "in progress". 2. Filter to "delivered". 3. Filter to "cancelled". 4. Filter to "needs attention". 5. Clear the filter. |
| **Expected** | Each filter shows only its own shipments; the four sets together are the whole list with nothing missing and nothing counted twice. The keyword search has its own case, `CA-SHP-20` (DEC-0162) |
| **Privacy / permission** | The count shown is always of this customer's own rows |
| **Evidence to capture** | Screenshot of each filter with its count |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-10 — Filtering by date range, including the boundary days

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | A shipment booked late in the evening, Toronto time. The seed supplies it: booking reference `UAT-CA-SHP-10` on `STCA-000001`, booked at **23:30 Toronto time ten days before the last reset** and therefore stored on the next UTC day. Link the account to `STCA-000001` at approval; `uat_env.py --check` confirms the shipment exists (`docs/UAT/ENVIRONMENT.md` section 3b) |
| **Steps** | 1. Filter from that shipment's date to that same date. 2. Filter to the day before. 3. Filter to the day after. 4. Ask for a range wider than 400 days. |
| **Expected** | Step 1 includes it; steps 2 and 3 exclude it; step 4 is refused with a clear message naming the limit. The evening booking falls on its **local** day, not the next UTC day |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot of each range |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-11 — Dates are shown in the organization's timezone

| | |
|---|---|
| **Role** | Customer, active |
| **Steps** | 1. Note a shipment's booked date on the Customer Account. 2. Compare with the same shipment in the Staff Portal. |
| **Expected** | The same date, in the configured office timezone, on both surfaces |
| **Privacy / permission** | — |
| **Evidence to capture** | Both screens side by side |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-12 — Paging through a long history loses nothing and repeats nothing

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | The linked customer has more shipments than one page holds |
| **Steps** | 1. Page to the end, writing down every reference. 2. Compare the collected references with the Staff Portal list. 3. Note the total the screen reports. |
| **Expected** | Every shipment appears exactly once across the pages; the total matches the Staff Portal count for that customer |
| **Privacy / permission** | The total counts this customer's rows only |
| **Evidence to capture** | The collected list; the Staff Portal list |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-13 — A malformed or oversized reference answers like an unknown one

| | |
|---|---|
| **Role** | Customer, active |
| **Steps** | 1. Request a reference with the wrong shape. 2. Request one that is far too long. 3. Request a package reference. 4. Request a well-formed reference that does not exist. 5. Compare all four. |
| **Expected** | Four identical refusals — same message, same shape. Nothing says which kind of wrong it was |
| **Privacy / permission** | One failure shape is the whole point (T-03, T-17) |
| **Evidence to capture** | All four responses |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-14 — Suspension stops shipment history on the next request

| | |
|---|---|
| **Role** | Customer, active, then Operations |
| **Steps** | 1. As the customer, open a shipment. 2. Have Operations suspend the account. 3. Without signing out, refresh the page. |
| **Expected** | The refresh is refused. The customer is **not** left holding a page of shipment data that keeps working |
| **Privacy / permission** | Authorization is re-read on every request; no grant is cached |
| **Evidence to capture** | Screenshot before and after |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-15 — Archiving the linked customer stops shipment history immediately

| | |
|---|---|
| **Role** | Customer, active, then Operations |
| **Steps** | 1. As the customer, open "My shipments". 2. Have Operations archive the linked customer. 3. Refresh. 4. Have Operations unarchive it. 5. Refresh again. |
| **Expected** | Step 3 is refused with the generic message; step 5 restores access. The refusal never says the customer record was archived |
| **Privacy / permission** | Archive state is a `FIELD_MATRIX.md` §3.4 never-field |
| **Evidence to capture** | Screenshots of all three states |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-16 — A shipment booked today appears without signing out

| | |
|---|---|
| **Role** | Customer, active, and Operations |
| **Steps** | 1. As the customer, note the current list. 2. Have Operations book and confirm a new shipment for that customer. 3. Refresh the customer's list. |
| **Expected** | The new shipment appears, with no sign-out and no wait |
| **Privacy / permission** | — |
| **Evidence to capture** | Before and after |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-17 — No money, no recipient details, no internal notes anywhere

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | A shipment carrying a selling amount, a shipping cost, a declared value, a recipient name, phone, email and full address, an internal note, and an internal-only event |
| **Steps** | 1. Open the list. 2. Open that shipment's detail. 3. Read every value on both screens, including the timeline. 4. View the page source or the raw response. |
| **Expected** | No amount, no currency, no recipient name, phone, email, street or postal code, no internal note, no internal event text, no staff name, and no customer record number — including in the underlying response, not merely on the screen |
| **Privacy / permission** | OD-32 and `FIELD_MATRIX.md` §3.4 |
| **Evidence to capture** | Both screens; the raw response |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-18 — The shipment screens offer nothing to change

| | |
|---|---|
| **Role** | Customer, active |
| **Steps** | 1. Open the list and the detail. 2. Look for any control that cancels, edits, rebooks, reschedules, claims a shipment, or contacts a recipient. |
| **Expected** | There are none. The surface is read-only; a customer cannot book, cancel or alter anything |
| **Privacy / permission** | Public booking, customer-created shipments and customer cancellation are all out of scope |
| **Evidence to capture** | Screenshots of both screens |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Profile and consent — `CA-PRF-*`

> **Executable since the screens were authorised and built.** At Phase 12 these four
> cases were out of scope: the owner's instruction then excluded customer profile editing
> and consent-management screens. Fix pack 2 built **Hồ sơ của tôi** / My profile with
> marketing consent (DEC-0123 to DEC-0128), and Phase 13F built **Thông báo** /
> Notifications for milestone email choices (OD-72). Run them like any other case. The
> milestone choices themselves are tested in `AIR_UAT_PACK.md` (`UAT-VIA-03`,
> `UAT-MLS-03`).


### CA-PRF-01 — Preferred language applies immediately

| | |
|---|---|
| **Role** | Customer, active |
| **Steps** | 1. Change preferred language. 2. Ask staff to look at the customer record. |
| **Expected** | Applied at once, no approval queue entry, and audited |
| **Privacy / permission** | One of only two direct fields |
| **Evidence to capture** | Staff view of the record |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-PRF-02 — A name or address change becomes a proposal

| | |
|---|---|
| **Role** | Customer, then Operations |
| **Steps** | 1. Submit a new legal name and a new pickup address. 2. Check the canonical record. 3. Approve one field and decline the other. 4. Check again. 5. Reload the review. 6. As an administrator, open Settings → Audit access and find "Updated customer STCA-… from an approved change request". 7. Change the approved field on the customer record as staff, and reload the review. |
| **Expected** | Nothing canonical changes until approval; per-field decisions are honoured; the customer sees each proposal's state. Step 5: the approved field shows **Applied** and is **not** marked "Changed since" (DEC-0147). Step 6: Details lists the approved field names (not "contact") and, under **Changes**, each one as "field: old → new" (DEC-0148). Step 7: the field is marked "Changed since" |
| **Privacy / permission** | The approver sees proposed, current and normalized values. The audit values are ones the administrator can already read on the record |
| **Evidence to capture** | Before/after records; approval screenshot; the review after approval; the audit row |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-PRF-03 — Internal fields are invisible

| | |
|---|---|
| **Role** | Customer, active |
| **Prerequisites** | The linked customer has tags, internal notes, an interaction, an assigned staff member and financial values |
| **Steps** | 1. Read every Customer Account screen. 2. Read the raw API responses. |
| **Expected** | **None** of the "Never" fields in `FIELD_MATRIX.md` §3.4 appears anywhere |
| **Privacy / permission** | Asserted against a record where each field is populated |
| **Evidence to capture** | Raw responses |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-PRF-04 — A customer cannot lift a suppression

| | |
|---|---|
| **Role** | Operations, then Customer |
| **Steps** | 1. Suppress the customer's email channel in the Staff Portal. 2. As the customer, grant marketing consent. 3. Ask staff to check the suppression and the audience eligibility. 4. As the customer, withdraw marketing consent. 5. As an administrator, read the customer's Consent tab and Settings → Audit access. |
| **Expected** | The suppression stands; the address remains excluded; the customer-facing response says nothing about the suppression. Step 5: the customer's grant and withdrawal show `customer_account:CA-…` in the consent history's **By** column, and the "Customer recorded marketing consent" audit rows name the same actor, not "system" (DEC-0149) |
| **Privacy / permission** | OD-27, OD-38 |
| **Evidence to capture** | Staff view before and after; the consent history and the two audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Sessions, recovery and separation — `CA-SEC-*`

### CA-SEC-01 — Password reset is single-use and kills sessions

| | |
|---|---|
| **Role** | Customer |
| **Steps** | 1. Sign in on two browsers. 2. Request a reset. 3. Open the link and type two different passwords. 4. Complete it in one browser. 5. Reuse the link. 6. Use the other browser. |
| **Expected** | Step 3: "The two passwords do not match." beside **New password again**, and the link still works afterwards (DEC-0146). Reset works once; reuse refused; **both previous sessions are dead** |
| **Privacy / permission** | A reset for an unknown address gives the same response |
| **Evidence to capture** | Screenshots of each step |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SEC-02 — Suspension takes effect on the next request

| | |
|---|---|
| **Role** | Operations, then Customer |
| **Steps** | 1. With the customer signed in, suspend the account. 2. In the customer's browser, click any link. |
| **Expected** | The very next request fails; no waiting for a new sign-in; the refusal is the standard generic text |
| **Privacy / permission** | No cached grant exists anywhere |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SEC-03 — The two surfaces do not share a session

| | |
|---|---|
| **Role** | Operations and Customer, same browser |
| **Steps** | 1. Sign in to the Staff Portal. 2. In another tab, open the Customer Account. 3. Then sign in to the Customer Account and open a Staff Portal page. 4. Inspect the cookies. |
| **Expected** | Neither session authenticates the other surface; the cookie names are different; the staff session is unaffected throughout |
| **Privacy / permission** | The separation invariant, seen by a human |
| **Evidence to capture** | Cookie list; both screens |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SEC-04 — Sign-out is server-side

| | |
|---|---|
| **Role** | Customer |
| **Steps** | 1. Sign in. 2. Sign out. 3. Press Back. 4. Re-send the previous request from the browser's history or developer tools. 5. As an administrator, open Settings → Audit access and find "Customer signed in" and "Customer signed out". |
| **Expected** | No shipment data after sign-out; the replayed request is refused; nothing readable from cache. Step 5: both rows name the actor `customer_account:CA-…` (the account's reference), not "system" (DEC-0153) |
| **Privacy / permission** | `no-store` on authenticated responses. The audit rows carry the account reference only, no email address |
| **Evidence to capture** | Screenshots; the two audit rows |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Added by Phase 12 — `CA-REG-09`, `CA-SHP-19`, `CA-SEC-05` … `CA-SEC-07`, `CA-XP-*`

> Eight cases for behaviour that had no screen to test before: the production-email gate as
> a customer meets it, the equivalence of unknown and unauthorised, the states a refused
> account sees, what a token leaves behind in the browser, and the three cross-cutting
> properties — phone, keyboard, language.
>
> Every **Result**, **Defect**, **Tester**, **Date** and **Evidence** field is blank.

### CA-REG-09 — Registration when accounts are not open

| | |
|---|---|
| **Role** | Customer (not signed in) |
| **Prerequisites** | An environment where registration is gated — production, or a UAT stack restarted with `ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER=true`, which applies the production no-email-provider gate outside production. `docs/UAT/ENVIRONMENT.md` section 3c has the exact commands to switch to it **and back**; restart without it before running any other `CA-REG-*` case |
| **Data** | Any unused `example.com` address |
| **Steps** | 1. Open the Customer Account and go to registration. 2. Complete the form and submit. 3. Read the screen. |
| **Expected** | A calm heading saying accounts are not open yet, the service's own sentence, and a link to public tracking. **No** setting name, provider name, transport name, version string or decision identifier anywhere on the page |
| **Privacy / permission** | A configuration gate is not explained to a stranger |
| **Evidence to capture** | Screenshot of the whole page |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SHP-19 — An unknown reference and somebody else's are the same page

| | |
|---|---|
| **Role** | Customer, active, with shipments |
| **Prerequisites** | A second customer's Solaris Shipment ID, obtained from the Staff Portal |
| **Data** | That reference, plus `SX-CAV-ABCDEFGHJKLM`, plus `not-a-reference` |
| **Steps** | 1. Open `/account/shipments/<the other customer's id>`. 2. Screenshot the page. 3. Open `/account/shipments/SX-CAV-ABCDEFGHJKLM`. 4. Screenshot. 5. Open `/account/shipments/not-a-reference`. 6. Screenshot. 7. Compare the three, word for word. 8. Put each into the list's **Search shipments** box in turn. 9. Search for the last eight characters of the other customer's ID, for one of their package IDs (the ID followed by `-01`), and for part of their booking reference (ask Operations for one). |
| **Expected** | Three **identical** pages. The search returns an empty list for every one of steps 8 and 9, with the same wording each time ("No shipments match those filters") — not a refusal, and not a hint that any of them exists (DEC-0156, DEC-0161) |
| **Privacy / permission** | T-03. A difference of one word between "not yours" and "no such thing" is the disclosure |
| **Evidence to capture** | The three screenshots side by side |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SEC-05 — Signing in tells you nothing about the account

| | |
|---|---|
| **Role** | Customer (not signed in) |
| **Prerequisites** | One active account, one rejected, one suspended, and an address with no account at all |
| **Data** | The four addresses, plus a deliberately wrong password for the active one |
| **Steps** | 1. Attempt to sign in as each in turn with a wrong password. 2. Attempt the unknown address. 3. Attempt the rejected and suspended accounts with their **correct** passwords. 4. Compare every failure page. 5. As an administrator, open Settings → Audit access and find the "Customer sign-in refused" rows. |
| **Expected** | One sentence for all of them. No page says unverified, declined, suspended, deactivated, locked, or "no such account". Step 5: one row per attempt, actor "system", with no email address in it (DEC-0155) |
| **Privacy / permission** | T-02 and T-10. The distinctions matter to the audit log and to nobody reading this screen |
| **Evidence to capture** | Screenshots of each failure |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SEC-06 — The declined and unavailable states say nothing

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | A rejected account and a suspended one |
| **Data** | — |
| **Steps** | 1. Open `/account/rejected`. 2. Open `/account/unavailable`. 3. Read both. 4. Ask staff for the rejection reason code recorded in the audit log. |
| **Expected** | The declined page states that an account cannot be set up and gives **no reason**; the unavailable page does not say whether the account is suspended or deactivated. Neither matches the reason code staff can see |
| **Privacy / permission** | `STATE_MACHINES.md` §1 transition 5: no reason that describes another record |
| **Evidence to capture** | Both screenshots, and the audit entry beside them |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-SEC-07 — A link's token does not linger in the browser

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | A verification message and a password-reset message in the capture |
| **Data** | Both links |
| **Steps** | 1. Open the verification link. 2. Look at the address bar once the outcome is on screen. 3. Press Back. 4. Open the browser's history and search for `token`. 5. Repeat for the reset link. 6. Check the page source of both landing pages. |
| **Expected** | The address bar shows the path with no query string; Back does not return to the tokenised URL; no history entry holds the token; the token is in neither page's source |
| **Privacy / permission** | A link is a live credential until redeemed. This reduces exposure; the token being single-use and short-lived is what bounds it |
| **Evidence to capture** | Screenshot of the address bar and of the history search |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-XP-01 — The Customer Account on a phone

| | |
|---|---|
| **Role** | Customer, active, with several shipments |
| **Prerequisites** | A real phone, or a browser window at 375 × 812 |
| **Data** | — |
| **Steps** | 1. Walk registration, sign-in, the pending card, the shipment list, the filters (type part of a city in **Search shipments** and press the keyboard's search key) and one shipment. On the list, read each card's **Booking reference**; on the shipment, read its **Booking reference**. 2. At each screen, scroll sideways. 3. Tap each primary control with a thumb. 4. On registration, press **Create account** with the **Address** section empty; then fill it, type `L4W 1V` in **Postal code** and press it again. 5. Use the phone's address autofill on the address, and tap the words "Billing address is the same as the address above", then press **Create account**. |
| **Expected** | No horizontal scrolling anywhere; the shipment list is cards rather than a squeezed table; primary controls are comfortably tappable; long Solaris Shipment IDs wrap instead of widening the page; the keyboard's search key runs the search, and its hint wraps rather than widening the page; each card, and the shipment's own page, shows **Booking reference** (or "Not recorded"), and a long one wraps. Step 4: an error under each required address part, readable without sideways scrolling, and none for billing or the postal code; then "Enter the postal code as A1A 1A1, or leave it blank." under Postal code, also without sideways scrolling. Step 5: autofill fills the address only; tapping the words unticks the box and shows the billing fields, and their errors also fit the screen |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshots at 375 px of each screen |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-XP-02 — The whole surface from the keyboard

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | Keyboard only. Put the mouse away |
| **Data** | — |
| **Steps** | 1. Tab from the top of each screen. 2. Use the skip link. 3. Complete registration, sign-in, a filter, and opening a shipment. 4. Submit a form with a mistake in it and find the error. 5. Sign out. |
| **Expected** | The skip link is the first stop and moves focus into the main region; every control is reachable in a sensible order with a visible focus indicator; a failed submit moves focus to the summary and each message is reachable from its field; nothing traps focus |
| **Privacy / permission** | — |
| **Evidence to capture** | A short screen recording, or a numbered list of tab stops per screen |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### CA-XP-03 — Vietnamese first, with an English switch on every screen

| | |
|---|---|
| **Role** | Customer |
| **Prerequisites** | A browser whose preferred language is Vietnamese |
| **Data** | — |
| **Steps** | 1. Open every Customer Account screen, signed out and signed in. 2. Find the language control. 3. Switch to English on one screen, move to the next, then switch back. 4. Read every message, including the failures and the captured emails, in both languages. 5. Open Public Tracking and switch it. 6. Return to the Customer Account. |
| **Expected** | Step 1: every screen opens in **Vietnamese** whatever the browser's language. Step 2: a switch (**Tiếng Việt** / **English**) at the top of every screen. Step 3: the whole screen changes and the choice holds as you move on; nothing is stored in the browser, and a signed-in customer's saved language applies at sign-in. Step 4: no screen mixes the two languages; emails follow the customer's saved language. Step 6: Public Tracking's switch does not change the Customer Account |
| **Privacy / permission** | OD-71 (2026-10-20), which replaced the English-only release of OD-39. The Vietnamese wording is not yet reviewed by a native speaker: record wording findings as S5 |
| **Evidence to capture** | Screenshots, including the browser's language setting |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Added by UAT round 11 — `CA-SHP-20`

> One case for the shipment list's keyword search, which until round 11 was a set of
> steps inside `CA-SHP-09` (DEC-0162). Every **Result**, **Defect** and **Evidence
> obtained** field is blank.

### CA-SHP-20 — Searching your shipments by keyword

| | |
|---|---|
| **Role** | Customer, active, with shipments |
| **Prerequisites** | The linked customer has at least three shipments on at least two routes, one of them with a booking reference and one without (ask Operations to type one, for example `PO-BAKERY-4471`, when booking), one with two packages of which Operations has cancelled the second, and one shipment to or from a city with accents (for example Đà Nẵng or Hồ Chí Minh). A second customer's Solaris Shipment ID, booking reference and a cancelled package ID, obtained from the Staff Portal |
| **Data** | The keywords in the steps |
| **Steps** | 1. Open **My shipments** and read each row (or card, on a phone). 2. Read the **Search shipments** box and its hint. 3. Type the last six characters of one Solaris Shipment ID, in lower case, and press **Apply filters**. 4. Search for that shipment's first package ID: its Solaris Shipment ID followed by `-01`; then for the cancelled package's ID (`-02` on the two-package shipment). 5. Search for part of the booking reference (`bakery`), and open the shipment it finds. 6. Search for part of a city, without its accents and in capitals (`DA NANG` for Đà Nẵng), then with them in lower case (`đà nẵng`). 7. Keep a keyword that matches more than one shipment and add a status, a route, then a booked from/to range. 8. Reload the page. 9. Search for the other customer's Solaris Shipment ID, its `-01` package ID, their cancelled package ID, and part of their booking reference. 10. Search for a recipient's name and street from one of your own shipments. 11. Press **Clear filters**. |
| **Expected** | Step 1: each row shows **Booking reference** with the reference typed at booking, or "Not recorded" (DEC-0160). Step 2: the hint says it searches the Solaris Shipment ID, a package ID, your booking reference, and the city it was sent from or to, and that part of a word is enough and capitals and accents do not matter. Steps 3–6: each finds the matching shipment(s) and only those; a package ID finds its one shipment, listed once (DEC-0161), and so does a cancelled package's ID (DEC-0164); the shipment opened at step 5 shows **Booking reference** `PO-BAKERY-4471` on its own page (DEC-0163); with or without accents finds the same shipments (DEC-0156, DEC-0157). Step 7: each added filter narrows the result further, never widens it. Step 8: the box and filters are refilled from the address bar. Step 9: "No shipments match those filters" each time, worded exactly as for a keyword that matches nothing. Step 10: nothing found. Step 11: everything is cleared and the whole list is back |
| **Privacy / permission** | T-03. The search only ever narrows this customer's own shipments: another customer's ID, package ID (cancelled or not) or booking reference finds nothing and is counted nowhere. It reads only the Solaris Shipment ID, package IDs, the booking reference and the two cities |
| **Evidence to capture** | Screenshots of steps 1 to 7, 9 and 10 |
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
| Cases in this pack | 60 — counted by heading: `CA-REG` 9, `CA-APR` 17, `CA-SHP` 20, `CA-PRF` 4, `CA-SEC` 7, `CA-XP` 3. `scripts/verify_uat_blank.py` checks this number. The owner confirmed 59 on 2026-10-15 (DEC-0136) and added `CA-SHP-20` on 2026-10-18 (DEC-0162); the 57 of the bot-executed run of 2026-10-14 was that run's count, and no case is withdrawn |
| Executed | |
| Passed | |
| Failed | |
| Blocked | |
| Defects raised | |
