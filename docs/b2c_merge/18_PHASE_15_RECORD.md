# 18 — Phase 15 completion record: workflow hardening

**Date:** 2026-10-21 · **Branch:** `phase-13-b2c-merge` · **Base:** 97e38fe (Phase 14) ·
**Migration:** none (head stays `c5e8a1f3d7b9`) · **Decision:** DEC-0216 · **Scope:** air only

Nothing is deployed, pushed or merged. No table is added or altered (DEC-0181). No email reaches
anybody (milestone and quote emails stay on the null / capture transports, OD-72). Test data
only: the sanitized fixture workbook, the demo exchange rate and demo addresses. Vendor cost,
exchange rate and markup reach no Customer Account or public surface.

## 1. What was built

| Area | Where | What it does |
|---|---|---|
| Milestone email never behind the furthest point | `services/notification_service.py` (`furthest_reached`, `_finished`, `_decide`) | The furthest milestone reached is the highest of the shipment's state (when on the received / in transit / out for delivery / delivered ladder) and every other **published, unvoided** milestone event. A milestone below it is not queued, so a shipment in exception or return in progress (rank 0 as a state; a delivery attempt ranks as out for delivery) no longer lets a late or backdated earlier step through. A recipient delivery counts as delivered only when the whole shipment is (otherwise as out for delivery). "Closed" is read from the shipment's state only (returned or cancelled, a cancelled booking, or every active package returned): nothing is queued; a row queued before is skipped at dispatch as `closed` and its key freed. One parcel of several returned does not close the shipment; a shipment sent out again notifies normally |
| Customer timeline wording | `schemas/account_shipments.py` (`event_type`), `services/customer_account_shipment_service.py`, `account/pages/ShipmentDetailPage.jsx` (`TimelineWording`), `account/i18n/{en,vi}.js` (`detail.event.*`, `detail.eventFallback`, `detail.staffNote`) | Each entry shows the standard sentence for its event type in the customer's language, and beneath it the staff's published text (a standard update rendered in the same language, or the typed sentence), unless it repeats the standard sentence. A collection-point handover reads as such, not as "out for delivery". Internal notes are not in the response shape. The public tracking page and its 24-field contract are unchanged (separate component) |
| Quote email resend | `services/quote_offer_service.prepare_resend`, `POST /quote-offers/{id}/resend-email` (`routes/quote_offers.py`), `workspace/OfferPanel.jsx` | For an unanswered offer whose email `failed`, or had `no_email` and the customer now has an address. Conditional claim (`email_status = resending`: two presses send once), audit `quote.email_resent`, commit; then the same decide / send / record seam as the first send, outside any retried unit. "Resend email" button (send / withdraw permission) with a hint and a status line announcing the outcome |
| Accepted quote → invoice prompt | `workspace/OfferPanel.jsx`, `workspace/InvoiceLink.jsx`; `GET /finance/accepted-not-invoiced` (`routes/finance.py`, `quote_offer_service.accepted_not_invoiced`); `finance/FinancePage.jsx` (`AcceptedNotInvoiced`) | When the latest offer is accepted and the shipment has no live invoice, the offer panel shows "Customer accepted vN — issue the invoice" with "Go to Issue invoice", which moves focus to the existing Issue invoice button. Finance → Invoices lists "Accepted, not invoiced" (read-only, `financial:read`), each row linking to the master. Nothing is invoiced automatically; voiding the invoice brings the prompt back |
| Tariff approver badge | `GET /tariffs/intake/pending-count` (`routes/tariffs.py`, `tariff_intake_service.pending_counts`), `settings/useTariffPending.js`, `components/layout/AppShell.jsx`, `settings/SettingsPage.jsx` | Drafts with no approver decision plus held-sender intakes, and whether the viewer is an approver. Holders of `tariff:manage` ask; a designated approver sees the count on the Settings navigation entry (with a screen-reader sentence) and on the Tariff updates tab ("Tariff updates (2 waiting)"). Approve, reject, release, upload and manual import refresh it. No email |
| Translations | `i18n/en.js`, `i18n/vi.js` (`workspace.offer.*`, `finance.accepted*`, `tariffPending`, `notifications.reason.closed`); account catalogues as above | At parity |
| Tests | Backend `test_notifications_phase15.py` (11), `test_account_timeline_wording.py` (3), `test_quote_offers_phase15.py` (11), `test_tariff_intake_pending_count.py` (3); `test_account_shipment_detail.py` key list gains `event_type` and `scope`. Frontend `accountTimelineWording.test.jsx` (7), `phase15Workflow.test.jsx` (14). Playwright `accountTimelineWording.spec.js` (new, account project); `accountQuotes.spec.js` extended with the staff prompt, the Finance list (axe audit) and issuing the invoice | See §3 |

## 2. Trying it

Rebuild the demo (`scripts/workspace_demo_env.py --reset`) and start it as in
`11_PHASE_13D_RECORD.md` §2. In the **Workspace**, send a finalised quote; with the capture
transport broken or a customer without an email address, the offer shows "Email: failed" / "no
address on file" and **Resend email**. Accept it in the Customer Account: the workspace shows
"Customer accepted v1 — issue the invoice", and **Finance → Invoices** lists it under "Accepted,
not invoiced". As the designated approver, import a workbook in Settings → Tariffs: the Settings
entry and the Tariff updates tab show the count. In the Customer Account, a shipment's
**Updates** show the standard sentence with the staff's text beneath; switch to Tiếng Việt.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,188 passed, 1 skipped; 2 failed, the known environmental pair |
| ruff check / format | clean (329 files) |
| eslint, vitest | clean; 731 passed |
| vite build | built |
| Playwright (run alone) | 316 passed |
| Alembic on a scratch database | head `c5e8a1f3d7b9` (no migration), check clean, downgrade -1, upgrade |
| Verifiers | every check passed |

Independent tester: 19 backend golden tests, no product defect. Independent reviewer: no high
finding; six medium and the low findings fixed (§4a).

## 4. Stand-ins (unspecified behaviour; the safest choice taken)

| Question | Stand-in |
|---|---|
| Customer timeline wording (plan stand-in) | Standard sentence for the event type in the customer's language; the staff's published text beneath it; left out when it repeats the standard sentence; an unknown event type reads "Your shipment has a new update." |
| Standard sentences | The shipment-level wording of each event type's first approved template (`public_update_templates.json`), shortened for delivery attempted and exception; Vietnamese awaits review |
| "On hold" | There is no on-hold state; an exception (or return in progress) is how staff record a hold, and neither lowers the furthest point |
| Returned | Read from the shipment's state only; a shipment sent out again (state back on the ladder) notifies its later milestones; a voided return frees the closed milestone |
| Package-level steps | An entry covering some, not all, of several active parcels has `scope: package` and reads "One of your parcels ..." (AC-7) |
| A resend claim left by a process that died | Taken over after 10 minutes; a press within the window is refused (409). An offer answered or withdrawn before the send gets nothing (`skipped`) |
| A row queued before a return or cancellation | Skipped at dispatch (`closed`), shown to the customer as "not sent" |
| Resend for `no_email` | The button shows; the server refuses (409, worded) until the customer has an address |
| Accepted, then a newer version finalised | The workspace says "agree the price first" and offers no shortcut to the invoice; Finance flags it the same way |
| Go to Issue invoice with no control to go to | A status message says why: no permission, or not available yet |
| Approver badge counts for a non-approver | Zero counts and `viewer_is_approver: false` from the server |
| Accepted quote and invoicing (plan stand-in) | Acceptance records only; staff are prompted (workspace and Finance) and issue through the existing button; the GST/HST choice stays theirs |
| Which accepted offer prompts | Each shipment's latest accepted offer, while no unvoided invoice exists and the booking is not cancelled; a newer finalised version is flagged ("agree the price first") |
| Who sees the badge | Only a designated approver, and only when something waits; others with `tariff:manage` do not; roles without it do not ask |

## 4a. Independent review fixes (2026-10-21)

Eleven findings (six medium, five low), all fixed (DEC-0216, "Review fixes"): closed read from the
shipment's state only (one parcel of three returned; returned then sent out again); closed rows
free their dedup key; a stale resend claim taken over after 10 minutes and the offer re-checked
before sending (`skipped`); the superseded acceptance in the workspace; package-level timeline
wording (`scope`); approver-only counts; the accepted list limited in SQL with a true total; the
delivery-attempt rank documented correctly; a reason shown when Go to Issue invoice has no
target; Vietnamese "đang được giao" and "lô tổng". New tests in `test_notifications_phase15.py`,
`test_quote_offers_phase15.py`, `test_account_timeline_wording.py`,
`test_tariff_intake_pending_count.py` (the non-approver test now expects zero counts),
`accountTimelineWording.test.jsx` and `phase15Workflow.test.jsx`.

The tester's `backend/tests/test_phase15_golden.py` changed in one place, because fix 1+3
changes the intended behaviour: in
`test_a_returned_shipment_gets_nothing_further_and_its_queued_row_is_closed` the delivery
recorded "after the return" puts the state back on the ladder, so it now notifies: the expected
emails became `["received", "delivered"]` (was `["received"]`) and the rows gained
`("delivered", "sent", None)`. The queued out-for-delivery row is still `closed`.

## 5. Not done

No automatic invoice; no reminder email to approvers or customers; no sea; the Vietnamese
wording (account standard sentences, staff prompts) awaits review by Vietnamese-speaking staff.

## Open questions for the owner (development continues on the stand-ins)

1. Should acceptance ever issue the invoice automatically (it does not; staff are prompted)?
2. Are the account's standard sentences the wording the owner wants customers to read?
3. Carried: the open questions in `16_REMAINING_WORK_PLAN.md`.
