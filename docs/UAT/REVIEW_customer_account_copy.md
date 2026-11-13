# Customer-facing copy review — Customer Account

> ## ⚠ NOT REVIEWED
>
> **Nobody has reviewed this wording.** Every field below is blank and must be filled in by
> the reviewer who read the screens. Claude did not fill in any of them and must not.

**Owner decision:** OD-39 — open. Release 1 is English only, and the English copy has not
been reviewed either. This sheet is that review.

> **Since 2026-10-20 (OD-71)** the Customer Account opens in **Vietnamese first** with an
> English switch on every screen. This sheet still reviews the English copy; the Vietnamese
> copy is a native-speaker review that has not happened (`19_OWNER_QUESTIONS.md` #6).

**Why this is not a proofread.** Most of the sentences on this surface exist to *avoid*
saying something. A registration confirmation that becomes friendlier by naming the
address, a sign-in failure that becomes more helpful by saying which part was wrong, a
declined state that becomes kinder by explaining why — each is an improvement in tone and
a disclosure in substance. The reviewer's job is to improve the wording **without**
improving it in that direction, and the column headed *Discloses anything?* is where that
judgement is recorded.

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

## Reviewer

| Field | Reviewer response |
|---|---|
| Reviewer name | |
| Role | |
| Date | |
| Environment and URL used | |
| Browser and viewport | |
| Read the threat model's T-02 and T-17 first? | |

---

## Part A — the screens

Walk each screen and read every sentence on it, including the ones that only appear when
something goes wrong.

| # | Screen (content under review) | Clear? | Right tone? | Discloses anything? | Correction | Approved |
|---|---|---|---|---|---|---|
| 1 | Sign in | | | | | |
| 2 | Sign in — the failure message | | | | | |
| 3 | Register — the introduction and the staff-review notice | | | | | |
| 4 | Register — field labels and hints | | | | | |
| 5 | Register — the country-aware phone and postal guidance | | | | | |
| 6 | Register — the terms acknowledgement and its placeholder warning | | | | | |
| 7 | Register — the marketing consent wording | | | | | |
| 8 | Register — validation summary and inline errors | | | | | |
| 9 | Register — "accounts are not open yet" | | | | | |
| 10 | Check your email | | | | | |
| 11 | Verification succeeded, including "this is not approval" | | | | | |
| 12 | Verification failed | | | | | |
| 13 | Resend verification, including "a new link cancels the old one" | | | | | |
| 14 | Forgot password | | | | | |
| 15 | Reset password — the form | | | | | |
| 16 | Reset password — done, including the sign-out notice | | | | | |
| 17 | Reset password — refused | | | | | |
| 18 | Account pending review | | | | | |
| 19 | Application declined | | | | | |
| 20 | Account not available | | | | | |
| 21 | My shipments — the introduction and the filter labels | | | | | |
| 22 | My shipments — empty history | | | | | |
| 23 | My shipments — no match for the filters | | | | | |
| 24 | My shipments — rate limited | | | | | |
| 25 | My shipments — session ended | | | | | |
| 26 | My shipments — history not available on this account | | | | | |
| 27 | Shipment detail — the status and progress wording | | | | | |
| 28 | Shipment detail — the tracking-state sentences | | | | | |
| 29 | Shipment detail — cancelled | | | | | |
| 30 | Shipment detail — not found | | | | | |
| 31 | Page not found inside the Customer Account | | | | | |
| 32 | The shell: header, sign-out, footer | | | | | |

## Part B — the messages

Source: `backend/app/services/account_email_service.py`. Read the rendered body, not the
template.

| # | Template key (content under review) | Sent when | Clear? | Discloses anything? | Correction | Approved |
|---|---|---|---|---|---|---|
| 1 | `account.verify_email` | Registration and every resend | | | | |
| 2 | `account.registration_attempt_notice` | Registration for an address that already has an account | | | | |
| 3 | `account.password_reset` | A reset was requested | | | | |
| 4 | `account.password_changed` | A reset completed | | | | |
| 5 | `account.approved` | Staff approved the account | | | | |
| 6 | `account.rejected` | Staff declined it | | | | |

## Part C — the sentences that must not become helpful

Each of these is deliberately uninformative. Confirm the wording still is, and say so.

| # | Sentence (content under review) | Reviewer response | Note |
|---|---|---|---|
| 1 | "If that address can be registered, we have sent a message to it." | | |
| 2 | "If that address has an account, we have sent a message to it." | | |
| 3 | "Email or password is incorrect." | | |
| 4 | "That link is no longer valid. Request a new one." | | |
| 5 | "We could not find that shipment. Check the Solaris Shipment ID and try again." | | |
| 6 | "Your account cannot view shipment history yet. Solaris Express will be in touch once your account review is complete." | | |
| 7 | "This account request was not approved." | | |
| 8 | "You cannot sign in to this account at the moment." | | |
| 9 | "Customer accounts are not available yet. Please contact Solaris Express." | | |

## Part D — terminology

The words a customer reads must not be the words staff use internally.

| Staff term (content under review) | Must never appear | Reviewer response | Where |
|---|---|---|---|
| Portal | The Customer Account is never "the portal" | | |
| Booking state | | | |
| Operational state | | | |
| Lifecycle status | | | |
| Duplicate / candidate / match | | | |
| Proposal | | | |
| Canonical customer | | | |
| Identity | | | |

## Part E — findings

| # | Screen or message | Finding | Severity | Proposed wording | Accepted |
|---|---|---|---|---|---|
| | | | | | |
| | | | | | |
| | | | | | |

---

## Result / sign-off

Nothing below is filled in until Parts A to D are complete.

| | Name | Date | Signature |
|---|---|---|---|
| Copy reviewer | | | |
| Operations reviewer | | | |
| Owner acceptance | | | |

**This sheet does not close OD-39.** OD-39 also requires a qualified reviewer to approve
the Vietnamese customer-facing UI, the Vietnamese verification and password-reset
messages, the privacy and terms wording, and the Vietnamese operational notification
wording — none of which exists, because release 1 is English only. Completing this sheet
approves the **English** copy and nothing else.

**It does not close OD-37 either.** The terms and privacy text is a placeholder, and the
registration screen says so. Approved legal text with version identifiers is an owner
action.
