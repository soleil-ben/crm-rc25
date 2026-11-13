# UAT cases

> **⚠ PREPARED, NOT EXECUTED.** Every **Evidence obtained**, **Result** and **Defect**
> field below is blank because no case has been run. Do not fill them in except while
> actually performing the step.
>
> **Two kinds of field, and the difference matters.** **Evidence to capture** is written
> in advance: it tells the tester what to collect, and it is part of the case definition,
> not a record of anything. **Evidence obtained** is what the tester actually captured,
> and it starts blank like **Result** and **Defect**. A prewritten instruction must never
> be read, counted or reported as evidence that a case was executed.

**Every case uses synthetic data.** Names and addresses below are invented and use the
reserved `example.com` domain. **Never substitute a real customer.**

**How to fill a case in:** collect what **Evidence to capture** names, record what you
actually captured in **Evidence obtained**, enter `Pass`, `Fail`, or `Blocked` in
**Result**, and put the defect id in **Defect** if it failed.

---

## Blocked by an open owner decision

`docs/OWNER_DECISIONS.md` is the register. Enter `Blocked` in **Result** for these, not
`Fail` — nothing here is broken; the question has not been answered.

| Blocked by | What is blocked | Affects |
|---|---|---|
| **OD-06** — the public help URL | **Nothing is blocked.** Under the owner-authorised RC-UAT disposition the empty URL is the behaviour *under test*: confirm the optional "Contact Solaris Express" link is cleanly **omitted** — not broken, blank, placeholder, or invented — and record `Pass`. OD-06 stays open for production | Listed here so the disposition is visible, not because a case is blocked |
| **OD-17** — MFA | The security section **cannot be signed off**. Authentication and session cases can still be executed and recorded | `UAT-AD-01`, `UAT-AD-02`, and the security sign-off |
| **OD-18** — label acceptance hardware | The physical label protocol. No printer, stock or scanner has been named | `docs/UAT/REVIEW_physical_label.md` |
| **OD-19** — the accessibility reviewer | The screen-reader review. Nobody has been assigned | `docs/UAT/REVIEW_accessibility.md` |
| **OD-08 / OD-09** — Vietnamese wording | Sign-off of the staff interface wording and the 17 customer-facing templates | `REVIEW_vietnamese_ui.md`, `REVIEW_vietnamese_templates.md` |
| **`19_OWNER_QUESTIONS.md`, questions 1–12** — prices, customer wording, workflow, the vendor mailbox (Phase 17) | **Nothing in this pack is blocked.** The air features are tested in `AIR_UAT_PACK.md`, whose own table lists the stand-in each case tests | `AIR_UAT_PACK.md` |
| **OD-22** — return shipment workflow | **Nothing is blocked.** No case in this pack would create or process a return **record**, because no workflow exists to write one against, and as of RC-UAT-3 the shipment-status report no longer offers a drill-through that promised one. Recorded here so the absence is deliberate and visible rather than an oversight | None of the 49 cases below |

**Return *statuses* are not blocked.** `Return in progress` and `Returned` are ordinary
recordable events and are in scope for testing. Only return **records** — a separate
shipment flagged `is_return` — are blocked. `docs/RETURNS_REQUIREMENT_MATRIX.md` explains
the difference, and `docs/UAT/ENVIRONMENT.md` section 7 lists what a tester will see.

---

## Shared synthetic data

Use these, with your initials and the date appended so two testers do not collide — e.g.
`Nguyễn Thị Bích Hạnh JS0914`.

| Ref | Name | Email | Phone | Country | Notes |
|---|---|---|---|---|---|
| **P1** | Nguyễn Thị Bích Hạnh | `hanh.uat@example.com` | `+1 416 555 0111` | CA | Diacritics — tests encoding everywhere |
| **P2** | Trần Quốc Tuấn | `tuan.uat@example.com` | `+1 416 555 0112` | CA | Second Vietnamese name |
| **P3** | Daniel O'Sullivan | `daniel.uat@example.com` | `+1 647 555 0113` | CA | Apostrophe — tests escaping and CSV |
| **P4** | Nguyen Thi Bich Hanh | `hanh.dup@example.com` | `+1 416 555 0111` | CA | **Deliberate near-duplicate of P1**: same phone, unaccented name |
| **P5** | Lê Thị Mai Anh | `maianh.uat@example.com` | — | CA | No phone — tests the contactable rule |

---

# Admin — `UAT-AD-*`

### UAT-AD-01 — Sign in, and the session ends as documented

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | An Admin account; the UAT URL |
| **Data** | Your own account |
| **Steps** | 1. Sign in. 2. Confirm the dashboard greeting. 3. Sign out from the account menu. 4. Press the browser Back button. |
| **Expected** | Sign-in succeeds; after signing out, Back does **not** show customer data — you are asked to sign in again |
| **Privacy / permission** | A signed-out session must not be recoverable from browser history |
| **Evidence to capture** | Screenshot of the post-sign-out state |
| **Added at Phase 12** | Confirm the staff session cookie is `solaris_session` and that signing in to the Staff Portal issues **no** `solaris_account_session` cookie. Then open `/account/shipments` in the same browser: the staff session must not open it |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-AD-02 — Wrong passwords pause sign-in

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | A test account you are willing to lock briefly |
| **Data** | A deliberately wrong password |
| **Steps** | 1. Enter the wrong password 9 times. 2. Note the message. 3. Wait, then sign in correctly. |
| **Expected** | Sign-in pauses with a clear message; it does **not** say whether the email exists; correct sign-in works after the wait |
| **Privacy / permission** | The message must not reveal whether an account exists |
| **Evidence to capture** | Screenshot of the pause message |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-AD-03 — Create a staff account and revoke it

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Settings → Staff and permissions |
| **Data** | `uat.temp@example.com`, Operations role |
| **Steps** | 1. Create the account. 2. Sign in as it in a second browser. 3. As Admin, deactivate it. 4. In the second browser, reload. |
| **Expected** | The second browser loses access **immediately**, not at next sign-in |
| **Privacy / permission** | Deactivation revokes sessions in the same transaction, and is audited |
| **Evidence to capture** | Screenshot of the revoked session; the audit entry |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-AD-04 — Merge two customers, with review

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | P1 and P4 both exist |
| **Data** | P1, P4 |
| **Steps** | 1. Open P1. 2. Find the duplicate suggestion. 3. Review the comparison. 4. Merge. 5. Open the survivor's shipments. |
| **Expected** | A comparison is shown **before** anything merges; after the merge the survivor holds both histories; the merged record is excluded from customer counts |
| **Privacy / permission** | The merge is audited with actor and both records |
| **Evidence to capture** | Before/after screenshots; the audit entry |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-AD-05 — Costs and profit are visible to Admin

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | A shipment with a recorded cost and selling amount |
| **Data** | Any qualifying shipment |
| **Steps** | 1. Open the shipment's financial section. 2. Open Reports and find the financial summary. |
| **Expected** | Cost, revenue, and profit all visible; the financial report present; figures grouped by currency and never combined across currencies |
| **Privacy / permission** | Admin is the only role holding `financial_cost:read` |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-AD-06 — Integration infrastructure reads `not_configured`

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Settings → Integration infrastructure |
| **Data** | — |
| **Steps** | 1. Open the panel. 2. Read every field. |
| **Expected** | Status **`not configured`**; no provider listed; no "last synchronised" or freshness figure anywhere; nothing suggesting ShipStation is connected |
| **Privacy / permission** | **This is the correct result, not a defect.** No provider exists (DEC-0075) |
| **Evidence to capture** | Screenshot of the whole panel |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-AD-07 — Audit log records a material change

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Settings → Audit access |
| **Data** | Any change you made earlier today |
| **Steps** | 1. Make a change to a customer. 2. Open the audit log. 3. Find the entry. |
| **Expected** | Actor, action, entity and time recorded; secrets shown as `[redacted]` and personal values as `[changed]` |
| **Privacy / permission** | The audit log must not become a second copy of the data |
| **Evidence to capture** | Screenshot |
| **Added at Phase 12** | Approve a Customer Account application, then find that approval in the audit log. Confirm it records the actor, the reason code and the disclosure figures, and that it carries **no** password, token, digest or session value |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Operations — `UAT-OP-*`

### UAT-OP-01 — Book a shipment end to end

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | P1 exists |
| **Data** | P1, Canada → Vietnam, 3 packages |
| **Steps** | 1. Shipments → New. 2. Choose P1. 3. Enter addresses. 4. Add three packages with weights. 5. Confirm. |
| **Expected** | A Solaris ID is issued with the **`SX-CAV-`** prefix; the shipment is confirmed; all three packages listed |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot showing the Solaris ID |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-02 — A double-click does not create two bookings

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A draft ready to confirm |
| **Data** | Any draft |
| **Steps** | 1. Confirm, clicking the button **twice, quickly**. 2. Check the shipment list. |
| **Expected** | **Exactly one** shipment and one Solaris ID |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot of the list |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-03 — Editing an address does not change a confirmed shipment

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed shipment for P1 |
| **Data** | P1's address book entry |
| **Steps** | 1. Note the shipment's recipient address. 2. Edit that address in P1's address book. 3. Reopen the shipment. |
| **Expected** | The shipment still shows the **original** address — it is a snapshot taken at booking |
| **Privacy / permission** | — |
| **Evidence to capture** | Before/after screenshots |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-04 — Three packages, three label pages

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | The UAT-OP-01 shipment |
| **Data** | That shipment |
| **Steps** | 1. Print labels. 2. Download the PDF. 3. Open it and check page count, size, and barcodes. 4. Reprint. |
| **Expected** | **Three pages**, each 4 × 6 inches, each with a unique package barcode; the reprint has identical IDs |
| **Privacy / permission** | — |
| **Evidence to capture** | The PDF |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-05 — Record a milestone and publish it

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed shipment |
| **Data** | "In transit" |
| **Steps** | 1. Open the shipment timeline. 2. Record event. 3. Note the publish box is **already ticked**. 4. Choose a standard update. 5. Save. |
| **Expected** | The event appears; publishing is on by default for ordinary milestones; the standard wording is shown in both languages before sending |
| **Privacy / permission** | Internal detail is never published |
| **Evidence to capture** | Screenshot of the form before saving |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-06 — Exception milestones do not publish by default

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed shipment |
| **Data** | An `exception` event |
| **Steps** | 1. Record an exception event. 2. **Look at the publish box before changing anything.** |
| **Expected** | The box is **unticked**. Exception, delivery attempted, return in progress and awaiting parcel start unticked on purpose |
| **Privacy / permission** | A customer should not learn of a problem before staff have decided what to say |
| **Evidence to capture** | Screenshot of the unticked box |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-07 — One delivered package of three is *partially* delivered

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | The three-package shipment |
| **Data** | Package 1 only |
| **Steps** | 1. Record final recipient delivery for package 1 only. 2. Read the shipment status. 3. Check the public page. |
| **Expected** | **Partially delivered**, not Delivered, in both places |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshots of both |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-08 — Add a manual tracking reference

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed shipment |
| **Data** | Carrier "Canada Post", reference `UAT123456789CA` |
| **Steps** | 1. Open the tracking section. 2. Add the reference. 3. Read the available modes. |
| **Expected** | Saved and shown as **manual**; the only modes offered are manual and external link — **there is no "connected API" option** |
| **Privacy / permission** | No provider is connected (DEC-0075). Its absence is correct |
| **Evidence to capture** | Screenshot of the mode options |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-09 — Cancel and rebook

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed shipment |
| **Data** | Any confirmed shipment |
| **Steps** | 1. Cancel and rebook. 2. Note the new draft. 3. Confirm it. 4. Check the shipment count on Reports. |
| **Expected** | The cancelled original keeps its Solaris ID; a **new draft** is created, not a confirmed shipment; the pair counts as **one** shipment in reports |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot of both records and the report figure |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-10 — Revenue is visible; cost and profit are absent

*Merged from the former `UAT-CS-06` and the former `UAT-OP-10`. Both asked what a
non-Admin sees on a shipment with money on it. Before the role merge they had opposite
expected results, because Customer service held `financial:read` and Operations did not.
Operations now holds it, so there is one question and one answer.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A shipment with a recorded revenue **and** a recorded carrier cost |
| **Data** | Any qualifying shipment |
| **Steps** | 1. Open the shipment and read the financial panel. 2. Look for cost or profit anywhere on the page. 3. Open Reports and look for the financial report. 4. Open the browser network inspector and read the raw shipment response. |
| **Expected** | **Revenue is shown.** **No cost or profit figure appears anywhere** — not blank, not zero, not masked — and neither appears in the raw API response either. The financial report **is** listed, because Operations holds `financial:read` |
| **Privacy / permission** | **The key permission case for this role.** Operations holds `financial:read` and `financial:write`; it does **not** hold `financial_cost:read`. A figure you may not see is never sent to your browser (DEC-0088) |
| **Evidence to capture** | Screenshot of the shipment panel, the Reports list, and the raw response body |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-11 — Create a customer with a Vietnamese name

*Formerly `UAT-CS-01`, unchanged in substance. Operations holds `customer:create`.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Signed in as Operations |
| **Data** | **P1** |
| **Steps** | 1. Customers → Add customer. 2. Enter the name **with diacritics**. 3. Add email and phone. 4. Save. 5. Reopen the record. 6. Search for it by name. |
| **Expected** | Diacritics intact on save, on reopen, and in search results — no `?` or `Ã` |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot showing the name rendered correctly |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-12 — A near-duplicate is held for review, never merged

*Formerly `UAT-CS-02`, unchanged in substance. Operations holds `duplicate:review`; it
does **not** hold `customer:merge`, so the Admin-only boundary is still the point.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | P1 exists |
| **Data** | **P4** (same phone, unaccented name) |
| **Steps** | 1. Add customer. 2. Enter P4's details. 3. Watch for the duplicate panel. 4. Read what it offers. |
| **Expected** | A duplicate panel appears **before** saving, showing what matched; you can proceed or review; **nothing merges automatically** |
| **Privacy / permission** | Merging is still Admin-only. Reviewing is not merging |
| **Evidence to capture** | Screenshot of the duplicate panel |
| **Added at Phase 12** | Have a customer register with an address that matches an existing customer exactly. Confirm the application enters the **same** duplicate review, that nothing is merged automatically, and that the applicant is told nothing about the match |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-13 — Record consent, then a withdrawal

*Formerly `UAT-CS-03`, unchanged in substance. Operations holds `consent:read` and
`consent:write`.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | P1 exists |
| **Data** | P1, email channel |
| **Steps** | 1. Open P1 → Consent. 2. Record consent for email. 3. Record a withdrawal. 4. Read the history. |
| **Expected** | Both entries kept with timestamps — history is **append-only**, and the withdrawal does not erase the grant |
| **Privacy / permission** | Suppression is global to the channel and address, and survives merges and re-imports. Operations cannot suppress: "Suppressed" is not offered in the consent form, and the server refuses it (DEC-0133) |
| **Evidence to capture** | Screenshot of the history |
| **Added at Phase 12** | Register with a suppressed address and tick the marketing box. Confirm the verification email arrives and sign-up can be completed. After approval, confirm the approval email arrived, the suppression still stands, the opt-in did not make the address marketing-eligible, and no screen or message the customer saw mentioned the suppression (DEC-0139, UAT round 6) |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-14 — Look up a shipment for a customer on the phone

*Formerly `UAT-CS-04`, unchanged in substance.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed shipment with a Solaris ID |
| **Data** | That Solaris ID |
| **Steps** | 1. Paste the ID into the search box. 2. Open the shipment. 3. Read the timeline. 4. Copy the ID. |
| **Expected** | Search finds it; timeline readable; the copy control puts the exact ID on the clipboard |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-15 — Complete a follow-up task

*Formerly `UAT-CS-05`, unchanged in substance.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | An open follow-up |
| **Data** | Any open task |
| **Steps** | 1. Follow-ups. 2. Open one. 3. Complete it. 4. Check the dashboard count. |
| **Expected** | The task moves to completed; the dashboard due count decreases |
| **Privacy / permission** | — |
| **Evidence to capture** | Before/after screenshots of the count |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-16 — Update a customer, then archive and restore one

*New. `customer:update` and `customer:archive` were Customer service permissions that
former Operations did not hold, and **no case in the pack exercised archiving at all** —
the merge is what made the gap visible.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | P2 exists and has no shipments |
| **Data** | P2 |
| **Steps** | 1. Open P2 and change the preferred language and the category. 2. Save and reopen. 3. Archive P2. 4. Search for P2 with the default filter. 5. Include archived records in the filter. 6. Restore P2. |
| **Expected** | The edits persist. An archived customer **disappears from the default list but is not deleted** — it is still findable with the archived filter, still carries its history, and restoring it returns it to the default list unchanged |
| **Privacy / permission** | Archiving is not deletion. Nothing in this flow removes a record |
| **Evidence to capture** | Screenshots of the list before archiving, after archiving, with the archived filter, and after restoring |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-17 — Tags and a referral

*New. `tag:write` and `referral:write` came across in the merge and nothing in the
Operations pack covered either.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | P1 and P2 exist |
| **Data** | P1, P2, any existing tag |
| **Steps** | 1. Open P1 and add a tag. 2. Save and reopen. 3. Record P2 as referred by P1, with a note. 4. Open P2 and read the referral. |
| **Expected** | The tag persists and appears on the customer list; the referral is recorded on both records and names who recorded it |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshots of the tag on the list and the referral on both records |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-18 — Build and save a segment

*New. `segment:read` and `segment:write` came across in the merge. `UAT-MK-01` covers the
same feature **as Marketing**; this case exists because the Operations permission is new
and untested, not to re-test segments.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Several customers exist |
| **Data** | Any condition — e.g. preferred language is Vietnamese |
| **Steps** | 1. Segments → New. 2. Add the condition. 3. Preview the audience. 4. Save it. 5. Reopen it. |
| **Expected** | The preview count matches the list; the saved segment reopens with its definition intact |
| **Privacy / permission** | A suppressed customer is still excluded from a **marketing** audience — see `UAT-MK-02`, which is not re-tested here |
| **Evidence to capture** | Screenshot of the saved definition and its count |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-19 — Edit a shipment's revenue

*New. `financial:write` came across in the merge. `UAT-OP-10` proves Operations can
**see** revenue; this proves it can **change** it, and that cost stays out of reach while
it does.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | A confirmed shipment with a recorded cost |
| **Data** | Any qualifying shipment |
| **Steps** | 1. Open the shipment financial panel. 2. Change the charged amount. 3. Save. 4. Reopen. 5. Sign in as Admin and open the same shipment. |
| **Expected** | The revenue edit saves and persists. **The form offers no cost or profit field to edit** — the panel Operations sees has revenue only. Admin sees the new revenue, the unchanged cost, and a profit recomputed from both |
| **Privacy / permission** | Writing revenue does not grant reading cost. `financial_cost:read` is still Admin's alone |
| **Evidence to capture** | Screenshots of the Operations form and the Admin view of the same shipment |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-OP-20 — The boundaries that did not move

*New. The merge widened Operations by seventeen permissions, which makes the ones it did
**not** get worth confirming explicitly rather than assuming.*

| | |
|---|---|
| **Role** | Operations |
| **Prerequisites** | Two customers that would match as duplicates |
| **Data** | P1 and P4 |
| **Steps** | 1. Look for a way to merge P1 and P4. 2. Look for Staff management and for editable organization settings. 3. Look for a customer or shipment bulk export. 4. Look for carrier cost on any screen and in Reports. |
| **Expected** | **All absent.** Merging is Admin-only; staff management is Admin-only; bulk customer and shipment exports are Admin-only (DEC-0082); cost and profit are Admin-only. Settings are **readable**, not editable |
| **Privacy / permission** | Operations does **not** hold `customer:merge`, `staff:manage`, `settings:write`, `export:customers`, `export:shipments`, or `financial_cost:read` |
| **Evidence to capture** | Screenshots showing each control is absent rather than present-and-refusing |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Marketing — `UAT-MK-*`

### UAT-MK-01 — Build a segment

| | |
|---|---|
| **Role** | Marketing |
| **Prerequisites** | Several customers with shipment history |
| **Data** | Filter: route Canada → Vietnam |
| **Steps** | 1. Segments → new. 2. Apply the filter. 3. Save. 4. Reopen. |
| **Expected** | Members match the filter; the saved segment reopens with the same definition |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-MK-02 — A suppressed customer is excluded from a marketing audience

| | |
|---|---|
| **Role** | Marketing |
| **Prerequisites** | P1 suppressed for email (UAT-CS-03) |
| **Data** | P1 |
| **Steps** | 1. Build a segment that would include P1. 2. Export the marketing audience. 3. Search the file for P1's email. |
| **Expected** | **P1 is absent from the audience.** Suppression applies to marketing exports |
| **Privacy / permission** | **A core privacy case.** Suppression must survive merges and re-imports |
| **Evidence to capture** | The exported file |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-MK-03 — Marketing cannot see costs or financial reports

| | |
|---|---|
| **Role** | Marketing |
| **Prerequisites** | — |
| **Data** | Any shipment; the Reports page |
| **Steps** | 1. Open a shipment. 2. Open Reports and list every report shown. |
| **Expected** | No cost anywhere; **no financial report in the list** |
| **Privacy / permission** | Marketing holds neither financial permission |
| **Evidence to capture** | Screenshot of the report list |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-MK-04 — Marketing cannot bulk-export shipments

| | |
|---|---|
| **Role** | Marketing |
| **Prerequisites** | — |
| **Data** | The shipment list |
| **Steps** | 1. Open Shipments. 2. Look for an export control. 3. If one is visible, use it. |
| **Expected** | The control is absent, or the attempt is refused. Bulk export is Admin-only while the final permissions are undecided (DEC-0082) |
| **Privacy / permission** | **Permission case.** Record whichever behaviour you observe |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Read-only manager — `UAT-RM-*`

### UAT-RM-01 — Everything is readable

| | |
|---|---|
| **Role** | Read-only manager |
| **Prerequisites** | Populated data |
| **Data** | — |
| **Steps** | 1. Open the dashboard, customers, shipments, follow-ups and reports in turn. |
| **Expected** | All readable; figures present |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshots |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-RM-02 — Nothing is editable

| | |
|---|---|
| **Role** | Read-only manager |
| **Prerequisites** | — |
| **Data** | Any customer, any shipment |
| **Steps** | 1. Open a customer and try to edit. 2. Try to add a customer. 3. Open a shipment and try to record an event. 4. Try to cancel a booking. |
| **Expected** | Every attempt refused or unavailable. **Record exactly which controls are visible-but-refused versus absent** |
| **Privacy / permission** | **The defining case for this role** |
| **Evidence to capture** | Screenshot of each attempt |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-RM-03 — Revenue visible, cost absent

| | |
|---|---|
| **Role** | Read-only manager |
| **Prerequisites** | Shipments with revenue and cost |
| **Data** | The financial report |
| **Steps** | 1. Open Reports. 2. Find the financial summary. 3. Look for a cost column. |
| **Expected** | The financial report **is** present and revenue **is** shown — this role holds `financial:read`. **No cost column at all**, because it does not hold `financial_cost:read` |
| **Privacy / permission** | The two-level financial permission, tested from the middle. **Present revenue is correct here, not a defect** |
| **Evidence to capture** | Screenshot of the report |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

---

# Cross-role — `UAT-XX-*`

### UAT-XX-01 — Public tracking, successful lookup

| | |
|---|---|
| **Role** | Anyone, **signed out**, ideally on a phone |
| **Prerequisites** | A confirmed shipment with public milestones |
| **Data** | That Solaris ID |
| **Steps** | 1. Open the public tracking URL in a **private window**. 2. Enter the ID. 3. Read everything. 4. Switch to Vietnamese. |
| **Expected** | Status, route, timeline and package count shown. **No customer name, address, phone, email, note, cost, or price anywhere.** The milestone text changes language with the switch |
| **Privacy / permission** | **The most important privacy case in the pack.** Read every word on the page |
| **Evidence to capture** | Full-page screenshots in both languages |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-02 — Public tracking, unknown reference

| | |
|---|---|
| **Role** | Anyone, signed out |
| **Prerequisites** | — |
| **Data** | `SX-CAV-ABCDEFGHJKLM`, then a real cancelled shipment's ID |
| **Steps** | 1. Look up the invented reference. 2. Look up the cancelled one. 3. Compare the two pages **word for word**. |
| **Expected** | Both give the same generic failure. **Nothing distinguishes "does not exist" from "exists but cancelled"** |
| **Privacy / permission** | Deliberate: a stranger must not be able to confirm an ID exists |
| **Evidence to capture** | Screenshots of both |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-03 — Import a customer list

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Customers → Import |
| **Data** | Template with **P1, P2, P3** |
| **Steps** | 1. Download the template. 2. Fill in three rows. 3. Upload. 4. Read the preview. 5. **Note the customer count before confirming.** 6. Confirm. 7. Check the count. |
| **Expected** | The preview shows every row and states plainly that **nothing has been created yet**; the count is unchanged until you confirm; then exactly three customers appear with diacritics and the apostrophe intact |
| **Privacy / permission** | A preview writes nothing |
| **Evidence to capture** | Screenshots of the preview and the counts |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-04 — Import the same file twice

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | UAT-XX-03 completed |
| **Data** | **The same file** |
| **Steps** | 1. Upload it again. 2. Read the preview. 3. Confirm. 4. Check the customer count. |
| **Expected** | **No new customers.** The rows are recognised as already imported |
| **Privacy / permission** | Idempotency — a re-import must not duplicate history |
| **Evidence to capture** | Before/after counts |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-05 — An import duplicate is decided, never merged

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | P1 exists |
| **Data** | A file containing **P4** |
| **Steps** | 1. Upload. 2. Read the duplicate section. 3. Try to confirm without deciding. 4. Make a decision. 5. Confirm. |
| **Expected** | The row is held for a decision; you **cannot** proceed without deciding; **no automatic merge ever happens** |
| **Privacy / permission** | **`CRM.md` requires review, not blind merging** |
| **Evidence to capture** | Screenshot of the duplicate decision |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-06 — A bad file is refused clearly

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | — |
| **Data** | A `.jpg` renamed to `.csv`; then a CSV with a missing required column |
| **Steps** | 1. Upload the fake CSV. 2. Read the message. 3. Upload the incomplete CSV. 4. Read the message. |
| **Expected** | Both refused, each saying **what is wrong and what to do** — not a generic error, and no stack trace |
| **Privacy / permission** | No internal detail in a user-facing error |
| **Evidence to capture** | Screenshot of each message |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-07 — Export a CSV and read it

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | Customers with Vietnamese names |
| **Data** | The customer list |
| **Steps** | 1. Filter the list. 2. Export. 3. Open the file **in Excel**. 4. Check the diacritics and the columns. |
| **Expected** | The export matches the filter; diacritics correct in Excel; no column the role may not see |
| **Privacy / permission** | Exports are allowlisted and audited |
| **Evidence to capture** | The file, and a screenshot of it open in Excel |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-08 — A formula in a name cannot execute

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | — |
| **Data** | A customer named `=1+1` or `+SUM(A1:A9)` |
| **Steps** | 1. Create the customer. 2. Export the list. 3. Open in Excel. |
| **Expected** | The cell shows the **text**, not a calculated result. Excel must not treat it as a formula |
| **Privacy / permission** | Formula-injection protection |
| **Evidence to capture** | Screenshot of the cell in Excel |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-09 — Reports count shipments once

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | The three-package shipment from UAT-OP-01 |
| **Data** | A period containing it |
| **Steps** | 1. Open Reports for that period. 2. Find the qualifying shipment count. 3. Find the package count. 4. Compare. |
| **Expected** | The shipment counts **once** despite three packages; packages are reported separately and never folded into shipment volume |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot showing both figures |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-10 — Reports refuse an impossible range

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | — |
| **Data** | A range longer than two years; then an end date before the start |
| **Steps** | 1. Enter each range. 2. Read the message. |
| **Expected** | Refused with an explanation of the limit — **not** a generic error and not an empty report |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshot |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-11 — A report is a shareable link

| | |
|---|---|
| **Role** | Admin |
| **Prerequisites** | — |
| **Data** | Any report with filters |
| **Steps** | 1. Set a range and a route filter. 2. Copy the URL. 3. Open it in a new tab. |
| **Expected** | The same filters and the same figures |
| **Privacy / permission** | The recipient still needs their own permission |
| **Evidence to capture** | Screenshot of both tabs |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-12 — Keyboard only

| | |
|---|---|
| **Role** | Any |
| **Prerequisites** | **Put the mouse out of reach.** This is not a figure of speech |
| **Data** | P5 |
| **Steps** | Using only Tab, Shift+Tab, arrows, Enter, Space and Escape: 1. Sign in. 2. Create a customer. 3. Open a shipment and record an event. 4. Open Reports and export. |
| **Expected** | All completable; focus always visible; Escape closes dialogs and returns focus to where you were |
| **Privacy / permission** | `Design.md` section 19 requires keyboard completion of these workflows |
| **Evidence to capture** | Note **every** place you had to guess where focus was |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-13 — Usable on a phone

| | |
|---|---|
| **Role** | Any |
| **Prerequisites** | A real phone, not a resized desktop window |
| **Data** | — |
| **Steps** | 1. Open public tracking and look up a shipment. 2. Sign in to the staff portal. 3. Open a customer and a shipment. |
| **Expected** | No horizontal scrolling; text readable without zooming; targets big enough to hit |
| **Privacy / permission** | — |
| **Evidence to capture** | Screenshots from the phone |
| **Added at Phase 12** | Add the Customer Account: registration, sign-in, the pending card, the shipment list and one shipment, on the same phone. The list must be cards rather than a sideways-scrolling table |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-14 — Vietnamese interface reads correctly

| | |
|---|---|
| **Role** | **A Vietnamese-speaking member of staff.** This case cannot be run by anyone else |
| **Prerequisites** | Vietnamese selected |
| **Data** | — |
| **Steps** | 1. Switch the staff interface to Vietnamese. 2. Walk through customers, shipments and reports. 3. Open the public page in Vietnamese and read the milestone wording. |
| **Expected** | Everything translated; nothing falling back to English; **and the wording is how Solaris actually speaks to customers** |
| **Privacy / permission** | **This is the open item.** The Vietnamese has never been reviewed by a native speaker — both the staff catalogue and the 17 customer-facing templates |
| **Evidence to capture** | **List every phrase that reads wrongly**, with a suggested replacement |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |

### UAT-XX-15 — Staff data is never visible to the public

| | |
|---|---|
| **Role** | Any, in **two browsers** |
| **Prerequisites** | Signed in as staff in browser A |
| **Data** | A shipment with internal notes and a recorded cost |
| **Steps** | 1. In A, add an internal note and confirm a cost is recorded. 2. In B, **signed out**, open the public page for that shipment. 3. Read every word, and use View Source. |
| **Expected** | **Neither the note nor the cost appears anywhere — including in the page source** |
| **Privacy / permission** | **S1 if anything leaks.** Check the source, not just the rendering |
| **Evidence to capture** | Screenshot of the page and the relevant source |
| **Added at Phase 12** | Extend to the authenticated Customer Account: no internal field, no financial value, no recipient detail beyond a city, no staff note, no provider or integration state, and no other customer's shipment |
| **Evidence obtained** | |
| **Result** | |
| **Defect** | |
