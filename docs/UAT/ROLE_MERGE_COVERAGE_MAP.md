# UAT coverage map for the Customer Service merge (DEC-0088)

The `customer_service` role is retired and the merged `operations` role carries the former
Customer Service permission set. The six `UAT-CS-*` cases therefore had to go somewhere.

**The case count is the output of this map, not an input to it.** No target was set before
the mapping was done. The pack went from **45 to 49** cases, and it went *up* because the
merge gave Operations seventeen permissions, several of which no case in the pack had ever
exercised — archiving a customer being the clearest example. A merge that only renamed
things would have produced 39; that number would have been a smaller pack covering less.

> **No result is carried across.** Every **Result**, **Defect**, **Tester**, **Date** and
> sign-off field in the remapped cases is blank, because no case has been executed. Nothing
> here converts a prepared case into a performed one.

---

## 1. The six former `UAT-CS-*` cases, one row each

| Original | Workflow and assertion covered | New case | Disposition | Where every original step and expected result now lives |
|---|---|---|---|---|
| **UAT-CS-01** | Create a customer with a Vietnamese name. Diacritics survive save, reopen and search — the normalization assertion | **UAT-OP-11** | **Renamed** | Same six steps, same expected result, same evidence. Only the **Role** row changed, from Customer service to Operations |
| **UAT-CS-02** | A near-duplicate is detected *before* save, shown with what matched, and **nothing merges automatically**. Merging is Admin-only | **UAT-OP-12** | **Renamed** | Same four steps and expected result. The permission note is strengthened, not weakened: Operations now holds `duplicate:review` but still does **not** hold `customer:merge`, so the Admin-only boundary is stated explicitly rather than implied by the role |
| **UAT-CS-03** | Record consent for a channel, then a withdrawal. History is **append-only**; suppression is global and survives merges and re-imports | **UAT-OP-13** | **Renamed** | Same four steps, same expected result, same privacy note verbatim |
| **UAT-CS-04** | Look up a shipment by Solaris ID; timeline readable; the copy control copies the exact ID | **UAT-OP-14** | **Renamed** | Same four steps, same expected result |
| **UAT-CS-05** | Complete a follow-up task; the dashboard due count decreases | **UAT-OP-15** | **Renamed** | Same four steps, same expected result, same before/after evidence |
| **UAT-CS-06** | **No cost figure anywhere**, and the financial report visible only if the role holds `financial:read` | **UAT-OP-10** | **Merged** | Merged with the former `UAT-OP-10`. See section 2 — this is the only case whose expected result changed, and it changed because the permission did |

**Five renamed, one merged. Nothing was removed.** The only case removed from the pack as a
*case* is the former `UAT-OP-10`, whose assertion had become false; its surviving half is
inside the new `UAT-OP-10`.

---

## 2. The one merge, in full

The former **`UAT-CS-06`** and the former **`UAT-OP-10`** asked the same question — what
does a non-Admin see on a shipment that has money on it? — and gave **opposite** answers,
because the two roles held different permissions:

| | Former `UAT-CS-06` | Former `UAT-OP-10` |
|---|---|---|
| Cost and profit | Absent | Absent |
| Financial report | Visible — Customer service held `financial:read` | Absent — Operations held neither |

Merged Operations holds `financial:read`. So the former `UAT-OP-10`'s expected result —
*"Operations holds neither `financial:read` nor `financial_cost:read`"* — is now **half
false**, and could not be carried forward unedited. One role now means one answer.

**The new `UAT-OP-10` carries every assertion from both:**

| Assertion | From | Present in new UAT-OP-10 |
|---|---|---|
| No cost figure anywhere on the page | both | Yes, step 2 |
| Not blank, not zero, not masked — structurally absent | former OP-10 | Yes, expected result |
| Never sent to the browser at all | former CS-06 privacy note | Yes — strengthened into step 4, which now reads the **raw API response**, an assertion neither original case made as a step |
| The financial report is visible when the role holds `financial:read` | former CS-06 | Yes, step 3 — and it is now a positive assertion rather than a conditional one |
| Revenue itself is visible | neither | New. Nothing tested it, because the role that could see it was the one nobody wrote a revenue case for |

Nothing was lost in the merge. One assertion was gained.

---

## 3. What no surviving case covered, and now does

The merge handed Operations seventeen permissions. Five of them landed on workflows the
pack had never exercised for **any** role, or had exercised only for a role that no longer
makes the point. These are the five genuinely new cases.

| New case | Permission gained | Why no existing case covered it |
|---|---|---|
| **UAT-OP-16** — update, archive and restore a customer | `customer:update`, `customer:archive` | **No case in the whole 45-case pack archived a customer.** Customer service held `customer:archive` and had no case for it; Operations did not hold it at all. The merge is what made the gap visible |
| **UAT-OP-17** — tags and a referral | `tag:write`, `referral:write` | Tag and referral writing was only ever reachable by Customer service and Marketing, and no case exercised either. `UAT-MK-*` covers segments and suppression, not tagging |
| **UAT-OP-18** — build and save a segment | `segment:read`, `segment:write` | `UAT-MK-01` covers segments **as Marketing**. That does not test the Operations grant, which is new. The case deliberately does not re-test suppression, which `UAT-MK-02` owns |
| **UAT-OP-19** — edit a shipment's revenue | `financial:write` | Nothing tested revenue **editing** by a non-Admin. `UAT-AD-05` covers Admin seeing cost and profit; `UAT-RM-03` covers the manager seeing revenue read-only. Neither writes |
| **UAT-OP-20** — the boundaries that did not move | *(none — negative)* | Seventeen permissions arrived at once. The ones that did **not** — `customer:merge`, `staff:manage`, `settings:write`, `export:customers`, `export:shipments`, `financial_cost:read` — are worth one explicit case rather than an assumption |

---

## 4. Required coverage, and where it lives

Every area the merged Operations section has to cover, with the case that covers it.

| Required coverage | Case | Status |
|---|---|---|
| Customer creation | `UAT-OP-11` | From `UAT-CS-01` |
| Normalization (diacritics on save, reopen, search) | `UAT-OP-11` | From `UAT-CS-01` |
| Duplicate review | `UAT-OP-12` | From `UAT-CS-02` |
| Customer updates and archive behaviour | `UAT-OP-16` | **New** |
| Addresses | `UAT-OP-03` | Existing, unchanged — covers `address:write` via the address-book edit |
| Consent and suppression | `UAT-OP-13` | From `UAT-CS-03` |
| Tags and referrals | `UAT-OP-17` | **New** |
| Segments | `UAT-OP-18` | **New** |
| Shipment workflows | `UAT-OP-01` … `UAT-OP-08`, `UAT-OP-14` | Existing, plus `UAT-CS-04` as `UAT-OP-14` |
| Cancellation / rebooking | `UAT-OP-09` | Existing, unchanged — covers `shipment:cancel` |
| Revenue visibility | `UAT-OP-10` | Merged case |
| Revenue editing | `UAT-OP-19` | **New** |
| Absence of costs and profit | `UAT-OP-10` | Merged case |
| Negative permission boundaries that remain meaningful | `UAT-OP-20`, and the permission notes on `UAT-OP-12` | **New** |

---

## 5. Why no assertion was lost

Checked category by category, against the six original cases:

* **Permission assertions.** Two existed: `UAT-CS-02`'s *"merging is Admin-only"* and
  `UAT-CS-06`'s *"the financial report is visible only if the role holds `financial:read`"*.
  The first is carried verbatim into `UAT-OP-12` and restated in `UAT-OP-20`. The second is
  carried into `UAT-OP-10` as a positive assertion, because the role now holds the
  permission. Neither was dropped.
* **Privacy assertions.** `UAT-CS-06`'s *"a figure you may not see is never sent to your
  browser"* is in `UAT-OP-10`, promoted from a note to an executable step that reads the raw
  response.
* **Consent assertions.** `UAT-CS-03`'s append-only history and global suppression are in
  `UAT-OP-13` unchanged, including the note that suppression survives merges and re-imports.
* **Duplicate-review assertions.** `UAT-CS-02`'s *"appears before saving"*, *"shows what
  matched"* and *"nothing merges automatically"* are all in `UAT-OP-12`.
* **Financial-visibility assertions.** Covered above; `UAT-OP-19` adds the write side.
* **Normalization assertions.** `UAT-CS-01`'s three checkpoints — save, reopen, search — are
  all three in `UAT-OP-11`.

---

## 6. Arithmetic

| | Cases |
|---|---:|
| RC-UAT-3 pack | 45 |
| Less the `UAT-CS-*` section | −6 |
| Subtotal | 39 |
| Plus renamed from `UAT-CS-*` into `UAT-OP-*` | +5 |
| Plus new cases for permissions nothing covered | +5 |
| **Total** | **49** |

`UAT-CS-06` accounts for the difference between the 5 renamed and the 6 removed: it was
merged into `UAT-OP-10` rather than renamed, so it adds no row.

**39 would have been the wrong answer.** It is what the pack would contain if the five
untested permissions were left untested, and if the former `UAT-OP-10` were kept with an
expected result that is no longer true.

---

## 7. Relationship to RC-UAT-3

RC-UAT-3 recorded `uat_cases: 45` and `uat_cases_executed: 0`. Both remain accurate **for
RC-UAT-3**, which is frozen and is not edited by this change. The 49-case pack supersedes it
for future execution. `docs/RC_UAT_3_BASELINE.md` records the supersession; the frozen
figures stay as they were measured.

Because `uat_cases_executed` was **0**, no completed human result is discarded by this
remapping. There were none to discard.

**Closed at RC-UAT-4 (2026-09-21).** The baseline in force now records `uat_cases: 49`,
measured from this pack, so `verify_rc_baseline.py` no longer reports the role-merge drift
against the current baseline. It still reports it against RC-UAT-1, RC-UAT-2 and RC-UAT-3,
which is the point of keeping them: the drift is the evidence of what this remapping
changed.

---

## 8. Phase 17: the air pack, by role (DEC-0218)

The air features of Phases 13A to 15 are tested in a **third pack**, `AIR_UAT_PACK.md`, not
added to this one: `UAT_CASES.md` stays at **49** and the Customer Account pack at **60**
(an owner decision, DEC-0136 and DEC-0162). The air pack holds **104** cases: the 36 of
Phase 17; since RC-UAT-18, 17 `UAT-OWN` cases for the owner answers of 2026-10-21
(OD-81 to OD-90; DEC-0219 to DEC-0222); since RC-UAT-19, 10 more (`UAT-OWN-18` to `-27`)
for the owner answers of 2026-10-22 (OD-91 to OD-101: GST/HST on the draft, generic tracking
names, costume jewellery by amount); and since RC-UAT-20, 8 more (`UAT-OWN-28` to `-35`) for
Ben's answers of 2026-10-23 (OD-102 to OD-108; DEC-0227 to DEC-0229: GST/HST by route and
province, the rate table, costume jewellery cost and price, and the RC-UAT-19 findings); and
since RC-UAT-21, 17 `UAT-BLD` cases (`UAT-BLD-01` to `-17`) for the build Ben asked for on
2026-10-24 (OD-110; DEC-0230 to DEC-0233: shipment import and legacy history, password and
sign-in email change — since RC-UAT-25 the Admin's change of a customer's sign-in email (customers cannot change it, RC-UAT-25) — reinstatement, the quote GST/HST
line, quote soft delete, retention); since RC-UAT-22, 2 more (`UAT-BLD-18`, `-19`, B-13);
since RC-UAT-23, 5 (`-20` to `-24`, the invoices); since RC-UAT-24, 1 (`-25`, the legal
entity); and since RC-UAT-25, 8 (`-26` to `-33`) for Ben's live UAT of 2026-10-25 (OD-113;
DEC-0240 to DEC-0247), which also rewrote `-09` and withdrew `-10` (its heading kept). The
account cases among them (`-08` to `-14`) use the seeded A1 and A2 accounts, so they live here
and the Customer Account pack stays at 60. As in §6, the count is the output of the mapping
below, not a target.

| Role | Permission exercised | Cases |
|---|---|---|
| **Operations** | `tariff:read` (Workspace, vendor cost, Settings → Pricing and Tariffs read-only, Payables, Profitability); quotes, invoices, draft invoices (`financial:read` / `financial:write`), payments, refunds, voids, vendor bills, month reopen (`financial:adjust`, OD-69); `shipment:write` (**Lock again** on an unlocked master); `tracking:write` (master milestones, a customer's milestone choices); refused **Unlock for edits** | `UAT-WSQ-01` to `-06`, `UAT-QAC-02`, `-03`, `UAT-FIN-01` to `-07`, `UAT-PRC-01` (read), `-04`, `UAT-TAR-01`, `-05` (refused), `UAT-MLS-01` to `-04`, `UAT-VIA-03`, `-04` (staff side), `UAT-OWN-01` to `-16`, `-18` to `-28`, `-29` (read only), `-30` to `-34` (staff side), `UAT-BLD-01`, `-06` (import pages refused, legacy list read), `-11` (own password), `-12` (no reinstate control), `-14` (draft invoice), `-15` (set-up), `-16`, `-17` (no Quote history panel, no Retention tab), `-09` (no **Change sign-in email**), `-26` to `-28` (booking form), `-30`, `-31` (`tracking:write`: record and correct a published event), `-32`, `-33` (Financials: Quote and invoice, Issue invoice) |
| **Admin** | Saving pricing settings and invoice terms; `tariff:manage` **and** a place on the approver list (OD-76): approve, reject, release, upload, import, the approver list; month close; `master:unlock` (OD-88) | `UAT-WSQ-07`, `UAT-FIN-05`, `-07`, `-08`, `UAT-PRC-01` to `-03`, `UAT-TAR-02` to `-05`, `UAT-OWN-02`, `-04`, `-05`, `-15`, `-17`, `-19`, `-20`, `-22`, `-26`, `-27`, `-29` (saving **Settings → GST/HST rates**, `settings:manage`), `UAT-BLD-01` to `-07` (`import:*`: dry run, import, void), `-08` (audit), `-09` (`customer_account:deactivate`: change a customer's sign-in email), `-12`, `-13` (`customer_account:deactivate`: deactivate, reinstate), `-15`, `-16` (`quote:delete`), `-17` (`retention:manage`, dry run only), `-31` (audit of an event edit), `-32` (recorded amounts, shipping cost) |
| **Marketing** | Refused: no Workspace, no vendor cost, no Payables or Profitability, no milestone-choice changes, no GST/HST rates, no tariffs | `UAT-WSQ-07`, `UAT-FIN-08`, `UAT-MLS-03`, `UAT-OWN-29`, `-34`, `UAT-BLD-16`, `-31` (no **Edit** on the timeline) |
| **Read-only manager** | Refused the same way; reads the GST/HST rates and a draft invoice without changing them | `UAT-WSQ-07`, `UAT-FIN-08`, `UAT-OWN-29`, `-30`, `UAT-BLD-06` (legacy list read), `-16`, `-33` (quoted revenue, no vendor cost, no Issue invoice) |
| **Customer (A1, Vietnamese)** | Their own quotes, shipments, notifications and profile only; an expired quote cannot be answered | `UAT-QAC-01`, `-04`, `UAT-VIA-01`, `-02`, `-04`, `UAT-OWN-05`, `-07`, `-08`, `-15`, `-21`, `-23`, `-24`, `-35`, `UAT-BLD-06` (no legacy record), `-08` (own password), `-13` (pending after reinstatement), `-14`, `-26` (asterisks), `-30`, `-31` (the received event and its correction) |
| **Customer (A2, English)** | The same | `UAT-QAC-03`, `-04`, `UAT-VIA-03`, `UAT-OWN-05`, `-06`, `-33`, `UAT-BLD-09` (sign-in email read only; an Admin changes it), `-12`, `-14`, `-16` (a deleted quote reads as not found), `-29` (an old email-change link refused) |

| Group | Cases |
|---|---:|
| `UAT-WSQ` workspace pricing and quotes | 7 |
| `UAT-QAC` quote acceptance in the account | 4 |
| `UAT-FIN` finance | 8 |
| `UAT-PRC` pricing settings and markup | 4 |
| `UAT-TAR` tariffs, rate emails, approval | 5 |
| `UAT-MLS` milestone emails and choices | 4 |
| `UAT-VIA` the Vietnamese-first account | 4 |
| `UAT-OWN` owner answers of 2026-10-21 (RC-UAT-18): master lock, quote expiry, draft invoices, tariff readings, vendor names | 17 |
| `UAT-OWN` owner answers of 2026-10-22 (RC-UAT-19): GST/HST check on the draft, generic tracking names, costume jewellery by amount | 10 |
| `UAT-OWN` owner answers of 2026-10-23 (RC-UAT-20): GST/HST by route and province, the rate table, Download after the check, payment date, costume jewellery cost and price, the vendor on the final leg, tariff warnings, wording kept | 8 |
| `UAT-BLD` build of 2026-10-24 (RC-UAT-21): shipment import, legacy history, password and email change (since RC-UAT-25 the Admin's change; `-10` withdrawn, its heading kept), reinstatement, quote GST/HST line, quote soft delete, retention | 17 |
| `UAT-BLD` RC-UAT-22: re-link or close an account left without a customer (B-13) | 2 |
| `UAT-BLD` RC-UAT-23: invoices on the Solaris Invoicing layout | 5 |
| `UAT-BLD` RC-UAT-24: the legal entity and the draft editor's wording | 1 |
| `UAT-BLD` RC-UAT-25: Ben's live UAT of 2026-10-25 — asterisks, the currency list, the saved recipient, the old email-change link, Received at warehouse, editing a published event, the Financials tab | 8 |
| **Total** | **104** |

No case moved between packs and no result exists to carry: every field in the air pack is
blank, checked by `scripts/verify_uat_blank.py`.
