# 14 — Phase 13G completion record: customer quote acceptance

**Date:** 2026-10-20 · **Branch:** `phase-13-b2c-merge` · **Base:** c4085c7 (Phase 13F) ·
**Migration:** `b7d2e9a4c1f6` (head), from `a3c9e7f1b5d2` · **Decision:** DEC-0213 ·
**Owner decisions:** OD-77 (D-08), OD-79 · **Scope:** air only

Nothing is deployed, pushed or merged. **No email reaches a customer**: the quote-sent email
goes through the account email seam, whose only transports are null and capture (OD-34 still
selects no provider). Test data only.

## 1. What was built

| Area | Where | What it does |
|---|---|---|
| Offers | `models/quote_offers.py` (new table `quote_offers`), `services/quote_offer_service.py` | One offer per finalised version, at most one `sent` per shipment; a frozen **customer view** (service label, billable kg, rate per kg, base charge, the surcharges the customer pays, total, CAD, before tax), read only from the customer side of the version |
| Send / withdraw (staff) | `api/v1/routes/quote_offers.py` | `POST /shipments/{id}/quotes/send` (only the latest version, only when finalised, once); `GET /shipments/{id}/quote-offers`; `POST /quote-offers/{id}/withdraw {reason}`. Same permissions as finalising (Operations, Admin) |
| Re-pricing | `services/pricing_service.finalize` | Finalising a newer version withdraws an unanswered offer ("superseded by vN"); acceptance re-checks that the version is still the latest finalised one |
| Answer (customer) | `api/account/quotes.py` | `GET /account/quotes`, `GET /account/quotes/{id}`, `POST …/accept`, `POST …/decline {reason?}`, authorized like the other account routes (session, CSRF on POST, rate limit, the identity's one active link); another customer's offer is the same 404 as an unknown one; a second answer is a 409 |
| Email | `services/account_email_service.py` (`quote.sent.vi`, `quote.sent.en`) | After the offer commits, outside any retried unit: reference and the account's quotes link only, no amount; Vietnamese unless the customer is English; sent even to a suppressed address (operational email, DEC-0143); the outcome is recorded on the offer |
| Staff screen | `features/workspace/OfferPanel.jsx` in the quote panel | "Send to customer" on a finalised quote; the offer's status (sent, accepted, declined with the customer's reason, withdrawn with the staff reason), the email outcome, Withdraw with a required reason, earlier offers |
| Customer screens | `src/account/pages/QuotesPage.jsx`, `QuoteDetailPage.jsx`, "Quotes" in the account navigation | List and detail; Accept asks for confirmation (stating the total) before sending; Decline with an optional reason; focus moves to the confirmation and then to the outcome; Vietnamese first, English switch; nothing stored in the browser |

## 2. Trying it

Rebuild the demo (`scripts/workspace_demo_env.py --reset`) and start it as in
`11_PHASE_13D_RECORD.md` §2. In the workspace, finalise a quote for a customer whose Customer
Account is approved, then press **Send to customer**. Sign in to the Customer Account at
http://localhost:5173/account as that customer, open **Báo giá** (Quotes), open the quote and
accept or decline it. The workspace then shows the answer. With
`ACCOUNT_EMAIL_TRANSPORT=capture` the quote-sent email is written to the capture directory.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 3,999 passed; the known environmental pair failed, and `test_uat_round_7` caught the quote email reading suppressions -- fixed (DEC-0143: a quote is operational email); the affected files rerun green (40 passed) |
| ruff check / format | clean |
| eslint, vitest | clean; 638 passed |
| vite build | built |
| Playwright (run alone) | 311 passed |
| Alembic on a scratch database | upgrade head → `b7d2e9a4c1f6`, check clean, downgrade -1, upgrade head |
| Verifiers | every check passed |

Independent tester: 12 black-box golden tests (`test_quote_offers_golden.py`), no product
defect. Independent reviewer: no high finding; three medium (accept during re-pricing, customer
merge, customer change) and the low findings fixed.

Developer's targeted run before hand-off: `test_quote_offers.py` 16 passed; with
`test_quotes.py`, `test_account_boundary.py`, `test_migrations_phase13f.py`,
`test_route_permissions.py`, `test_account_email_capture.py` and `test_notifications.py`,
1,092 passed; ruff check and format clean; eslint clean; vitest 635 passed (45 files); vite
build built; `accountQuotes.spec.js` alone (account project, no dependencies) 1 passed,
including its axe audit (before the review fixes); Alembic on a scratch database: upgrade head → `b7d2e9a4c1f6`, check
clean, downgrade -1, upgrade head; `verify_decision_log.py` every check passed. After the review fixes: `test_quote_offers.py` (21) and
`test_quote_offers_golden.py` (12) with the quote, boundary, migration, customer and merge
suites, 168 passed; vitest 638 passed; eslint, ruff and the build clean.

## 4. Stand-ins (unspecified behaviour; the safest choice taken)

| Question | Stand-in |
|---|---|
| A draft is open after the finalised version | Sending is refused ("finalise the quote first"): staff are re-pricing, and the customer must not accept a price staff are changing |
| What the customer total includes | Revenue lines only, before tax; the page says taxes, if any, are added on the invoice (GST/HST is chosen per invoice, OD-64). A surcharge line with no customer charge (a cost share only) is left out, as on the invoice |
| Surcharge names shown to the customer | The quote line's description, which comes from the fee (vendor tariff) rule name -- exactly what the invoice already prints. **Owner to confirm these names are customer-safe** |
| The staff withdrawal reason | Never shown to the customer (it may be internal); the customer sees "no longer valid" |
| A failed quote-sent email | Recorded on the offer (`email_status = failed`), shown to staff; not retried automatically (no worker), so a lock can never send it twice; the offer stands |
| The shipment's customer changes after sending | An unanswered offer is withdrawn ("customer changed"; "customer merged" in a customer merge, the only path that moves a shipment today) and answered offers follow the shipment to the new customer; until then an answer is refused (409) |
| Staff open a new draft after sending | The customer cannot answer ("Solaris Express is updating this quote"); the offer stays sent until the new version is finalised |
| A newer version is finalised after the customer accepted | The acceptance stands, is flagged (`superseded_by_version`) and audited (`quote.accepted_superseded`); the workspace warns that the customer accepted an earlier price |
| Accepting | Records the answer and freezes it; it does not book, invoice or change the shipment |
| Reading quotes | Reads commit the session's last-seen touch best effort; a lock loses the touch, never the answer (found by the browser run) |
| Who may read offers (staff) | The quote readers (`shipment:read`, `tariff:read`, `financial:read`); Marketing and the read-only manager get 403 |

## 4a. Independent review fixes (2026-10-20)

Answering requires the offer's version to be the shipment's **latest version of any status**
(an open draft gives 409 "being updated"); acceptance before a re-finalisation is flagged for
staff; a customer merge withdraws sent offers and re-points answered ones; a customer change
withdraws sent offers; the account states each closed reason (`closed_reason`: accepted,
declined, withdrawn, replaced, updating) without internal wording; accept and decline have their
own rate-limit bucket; Cancel returns focus to the opening button; weights are formatted per
locale; the list refreshes after an answer; Vietnamese wording polished. The tester's
`test_quote_offers_golden.py` gained one expected key (`closed_reason`) in its allowlist check.

## 5. Not done

No production email provider (OD-34); no automatic re-send of a failed quote email; no offer
expiry date; acceptance does not yet drive booking or invoicing; the Vietnamese wording awaits
review by Vietnamese-speaking staff. Sea is not quoted (air only).
