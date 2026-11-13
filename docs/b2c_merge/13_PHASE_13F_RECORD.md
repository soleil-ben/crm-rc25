# 13 — Phase 13F completion record: milestone notifications and the Customer Account in Vietnamese

**Date:** 2026-10-20 · **Branch:** `phase-13-b2c-merge` · **Base:** 3f13cfa (owner answers) ·
**Migrations:** `f2b8d5a1c7e4`, then `a3c9e7f1b5d2` (head), from `e4a7c2d9f1b3` · **Decisions:** DEC-0209 to
DEC-0212 · **Owner decisions:** OD-71 to OD-74 · **Scope:** air only

Nothing is deployed, pushed or merged. **No email reaches a customer**: the email seam has only
the null and capture transports (OD-34 still selects no provider). Test data only.

## 1. What was built

| Area | Where | What it does |
|---|---|---|
| Milestone email | `services/notification_service.py`, `models/notifications.py`, hook in `event_service.py` | A published received / in transit / out for delivery / delivered milestone queues one email per shipment and milestone; delivered only when the whole shipment is; dedup, withdrawal on void, late steps ignored; claim → send → record; skip reasons opted out, suppressed, no address, voided |
| Templates | `services/account_email_service.py` | Milestone emails in English and Vietnamese (reference and tracking link only); Vietnamese versions of every account email |
| Choices and history | `api/account/notifications.py`, `src/account/pages/NotificationsPage.jsx` | Customers turn each milestone on or off (default on) and see what was sent |
| Staff | `api/v1/routes/notifications.py`, Settings → Customer notifications | The outbox with status and reason, retry for a failed row, a customer's choices changed on their behalf |
| Worker | `workers/notification_worker.py` | Picks up anything left queued or failed |
| Customer Account in Vietnamese | `src/account/i18n*`, every account screen | Vietnamese first with an English switch on every screen; the account's language applies at sign-in; nothing stored in the browser |

Language of a notification: the account's language, else English for an English customer record,
else Vietnamese.

## 1a. Owner correction applied first (2026-10-20 16:23, OD-73, OD-74, DEC-0212)

| Rule | Where | Now |
|---|---|---|
| VND to CAD at the **buy** rate (first column) | `pricing/engine.py` | A customer surcharge converts at the buy rate, like its cost: a pass-through surcharge recovers exactly its cost (was the sell rate, billing below cost) |
| | `services/finance_service.py` | A VND vendor bill converts at the buy rate of the bill date, frozen on the bill (OD-67's middle rate superseded) |
| CAD to VND at the **sell** rate (last column) | `services/finance_service.py` | A CAD invoice paid in VND: the customer owes CAD × sell dong (unchanged result; now under OD-73) |
| 2 % default markup on surcharges | `markup_defaults` (new table), `pricing_service`, `PATCH /api/v1/pricing/settings` | Applies to every surcharge rule without its own policy; Admin changes it; audited; a per-rule policy overrides; finalised quotes keep their figures |

Review fixes with it: a scope-only rule policy inherits the 2 % default; the default is a
single bounded row; VND bill and payment rates use the end of the local (Toronto) day with the
four-day age limit; voiding one package's milestone event keeps the shipment's notification on
another package's standing event; a failed outcome write no longer stops the batch, and the
worker no longer re-runs a whole dispatch.

## 2. Trying it

Rebuild the demo (`scripts/workspace_demo_env.py --reset`), start it as in
`11_PHASE_13D_RECORD.md` §2, open a demo shipment in Shipments, record a **published** "Received
at Solaris" event, then Settings → **Customer notifications**: the row shows as recorded (the demo
uses the null transport; with `ACCOUNT_EMAIL_TRANSPORT=capture` the message is written to the
capture directory instead). The Customer Account is at http://localhost:5173/account, in
Vietnamese, with the English switch at the top.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 3,946 passed; 2 failed, the known environmental pair (`test_e2e_safety` development-database probe, `test_incident_cleanup` UAT-database refusal) |
| ruff check / format | clean (305 files) |
| eslint | clean |
| vitest | 621 passed (44 files) |
| vite build | built |
| Playwright (run alone) | 310 passed |
| Alembic on a scratch database | upgrade head → `a3c9e7f1b5d2`, check (no new operations), downgrade -1, upgrade head |
| `verify_decision_log.py`, `verify_owner_decisions.py` | every check passed |

Independent tester: 18 golden tests for the correction (`test_fx_markup_correction_golden.py`)
and 52 for notifications (`test_notifications_golden.py`), all passing, no product defect.
Independent reviewer: no high finding; the medium and low findings were fixed (§1a), except the
rank of exception states (on hold, returned), left as is.

## 4. Not done

No production email provider (OD-34); no mobile push (later, OD-72); shipment timeline text from
staff still reaches the account as typed; the Vietnamese wording awaits review by
Vietnamese-speaking staff. The default markup is set through the settings API; no Settings screen
field for it yet.
