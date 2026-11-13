# Vietnamese review — staff interface and public tracking

> ## ⚠ NOT REVIEWED
>
> **No Vietnamese speaker has reviewed this wording.** Every field is blank and must be
> filled in by the reviewer who read the screen. Claude did not fill in any of them and
> must not.

Two separate sheets in one file, because they have different audiences and different
stakes. The customer update templates are reviewed separately in
`REVIEW_vietnamese_templates.md`.

**Owner decisions:** OD-08 (staff UI) and OD-09 (customer-facing) — both open.

---

## Field classes on this sheet

Four kinds of field appear below, and they must never be confused with one another.

| Class | What it is | State before review |
|---|---|---|
| **Content under review** | The screen, sentence, template or check being judged. Written in advance as part of this sheet | Prewritten — **not** a reviewer's answer |
| **Reviewer response** | What the reviewer judged, observed or would change | **Blank** |
| **Evidence obtained** | What the reviewer actually captured — recordings, transcripts, screenshots, photographs | **Blank** |
| **Result / sign-off** | The outcome, the signature and the date | **Blank** |

Prewritten content is never evidence that this sheet was reviewed. A sheet is reviewed
only when the **Reviewer response**, **Evidence obtained** and **Result / sign-off**
fields have been filled in by the person who did the work.

---

# Part A — Vietnamese staff interface

Source: `frontend/src/i18n/vi.js`. A complete working translation at key parity with
English, produced during development. **It is not approved copy.**

Audience: Solaris staff. The stakes are operational — a mistranslated route or shipment
term causes a real dispatch error, which is why this is not a cosmetic review.

## Reviewer

| Field | Reviewer response |
|---|---|
| Reviewer name | |
| Date | |
| Fluency (native / professional / conversational) | |
| Business-context familiarity (shipping/logistics) | |
| Browser and viewport used | |
| UAT account used | |

## Screens to review

Switch the interface to Vietnamese and walk each screen. Record per screen.

| # | Screen (content under review) | Natural? | Terminology correct? | Consistent with other screens? | Correction | Approved |
|---|---|---|---|---|---|---|
| 1 | Sign in | | | | | |
| 2 | Dashboard | | | | | |
| 3 | Customer list and filters | | | | | |
| 4 | Customer detail | | | | | |
| 5 | Customer create / edit form | | | | | |
| 6 | Validation error messages | | | | | |
| 7 | Duplicate review panel | | | | | |
| 8 | Consent and suppression | | | | | |
| 9 | Shipment list | | | | | |
| 10 | Shipment detail and tabs | | | | | |
| 11 | Booking wizard | | | | | |
| 12 | Packages | | | | | |
| 13 | Cancel / rebook | | | | | |
| 14 | Events and timeline | | | | | |
| 15 | Label preview | | | | | |
| 16 | Tracking references (manual / external link) | | | | | |
| 17 | Follow-up tasks | | | | | |
| 18 | Segments | | | | | |
| 19 | Reports | | | | | |
| 20 | Export controls | | | | | |
| 21 | Import — upload, mapping, preview | | | | | |
| 22 | Import — duplicate decisions and confirmation | | | | | |
| 23 | Settings | | | | | |
| 24 | Empty states | | | | | |
| 25 | Permission-denied and not-found states | | | | | |
| 26 | **Customer account applications — the queue** *(new, Phase 12)* | | | | | |
| 27 | **Customer account applications — one application** *(new, Phase 12)* | | | | | |
| 28 | **Customer account applications — duplicate candidates** *(new, Phase 12)* | | | | | |
| 29 | **Customer account applications — the disclosure preview and its acknowledgement** *(new, Phase 12)* | | | | | |
| 30 | **Customer account applications — approval, rejection and conflict states** *(new, Phase 12)* | | | | | |

> **Screens 26–30 are new in Phase 12** and add roughly ninety Vietnamese strings under
> the `customerAccounts` key in `frontend/src/i18n/vi.js`. They were produced during
> development at key parity with English, like the rest of this catalogue, and are **not
> approved copy**. Two of them carry more weight than the others: the disclosure
> acknowledgement (screen 29) is a sentence a reviewer is certifying they have read, and
> the rejection reasons (screen 30) are recorded in an audit log other people read.
> A mistranslation there is not cosmetic.

> The **Customer Account customer-facing surface** is not in this sheet. It was English
> only (OD-39) when the sheet was written; since 2026-10-20 it is **Vietnamese first** with
> an English switch (OD-71), and its Vietnamese strings await their own native review
> (`19_OWNER_QUESTIONS.md` #6).

## Terminology check

The words that must mean the same thing on every screen.

| English term (content under review) | Vietnamese used | Correct? | Preferred term | Notes |
|---|---|---|---|---|
| Shipment | | | | |
| Package | | | | |
| Booking | | | | |
| Draft | | | | |
| Confirmed | | | | |
| Cancelled | | | | |
| Rebooked | | | | |
| In transit | | | | |
| Delivered | | | | |
| Exception | | | | |
| Route group | | | | |
| Sender / Recipient | | | | |
| Tracking reference | | | | |
| Carrier | | | | |
| Customer | | | | |
| Follow-up task | | | | |
| Consent | | | | |
| Customer account *(new, Phase 12)* | | | | |
| Application / applicant *(new, Phase 12)* | | | | |
| Disclosure *(new, Phase 12)* | | | | |
| Acknowledge *(new, Phase 12)* | | | | |
| Suppression | | | | |

> **Route groups** are the four Solaris corridors. Confirm the Vietnamese names match what
> staff actually say in the office, not a literal translation of the code.

## Part A — result / sign-off

| Field | Reviewer response |
|---|---|
| Evidence obtained (screenshots of the screens reviewed) | |
| Screens approved as written | |
| Screens needing change | |
| Is the Vietnamese **staff** interface approved for use? (yes/no) | |
| Reviewer signature | |
| Date | |

---

# Part B — Vietnamese public tracking

Source: the public tracking page in Vietnamese. Audience: **customers**. The stakes are
external and unrecoverable — an awkward register is visible outside the company.

## Reviewer

| Field | Reviewer response |
|---|---|
| Reviewer name | |
| Date | |
| Fluency | |
| Device and viewport (test 375 px as well as desktop) | |

## Screens and states

| # | State (content under review) | Natural? | Tone right for a customer? | Correction | Approved |
|---|---|---|---|---|---|
| 1 | Lookup form, empty | | | | |
| 2 | Successful result | | | | |
| 3 | Result with packages listed | | | | |
| 4 | Unknown / not-found reference | | | | |
| 5 | Malformed reference | | | | |
| 6 | Cancelled shipment | | | | |
| 7 | Exception state | | | | |
| 8 | Rate-limited ("too many lookups") | | | | |
| 9 | Language switch labels | | | | |
| 10 | Page title and headings | | | | |
| 11 | Dates and times as displayed | | | | |
| 12 | The timeline entries | | | | |

## Specific checks

| Check | Reviewer response |
|---|---|
| Do diacritics render correctly everywhere, including headings? | |
| Does any Vietnamese string overflow or clip at 375 px? | |
| Is the document language attribute Vietnamese when Vietnamese is selected? | |
| Is the politeness level right for a stranger? | |
| Does anything read as machine-translated? | |
| Is the contact link **absent**? (it should be — `PUBLIC_HELP_URL` is empty, OD-06) | |

## Part B — result / sign-off

| Field | Reviewer response |
|---|---|
| Evidence obtained (screenshots of the states reviewed) | |
| States approved as written | |
| States needing change | |
| Is the Vietnamese **public** page approved for customers? (yes/no) | |
| Reviewer signature | |
| Date | |

---

**Blank is not approval.** Until a person signs both result tables, the Vietnamese
interface remains explicitly unapproved for launch.
