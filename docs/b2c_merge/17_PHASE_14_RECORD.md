# 17 — Phase 14 completion record: staff screens for API-only features

**Date:** 2026-10-20 · **Branch:** `phase-13-b2c-merge` · **Base:** 38b845f (Phase 13H) ·
**Migration:** none (head stays `c5e8a1f3d7b9`) · **Decision:** DEC-0215 · **Scope:** air only

Nothing is deployed, pushed or merged. No table is added or altered (DEC-0181). No email reaches
anybody (milestone emails stay on the capture transport, OD-72). Test data only: the sanitized
fixture workbook, the demo exchange rate and demo addresses.

## 1. What was built

| Area | Where | What it does |
|---|---|---|
| Settings → Pricing | `features/settings/PricingSettingsPanel.jsx` | Air Standard and Air Express default rates (Express may be empty), the trigger share as numerator / denominator (OD-48), the owner-confirmed flag read-only, the default surcharge markup (OD-74); the active tariff's HCM / Hà Nội air surcharges with an accent-insensitive search and each rule's policy (Default, percent, fixed CAD, pass through; value; weight-basis override; note, OD-44). Read with `tariff:read`; saved by Admin (`settings:manage`). Only changed fields are sent; mistakes are named beside their field before sending, and a server refusal beside the field it names; focus moves to the field or to the confirmation |
| Settings → Tariffs | `features/settings/TariffBrowserPanel.jsx` | Versions with status (a rejected draft reads "Rejected by approver"); a version's air products and rate brackets, air accessorials, beyond-area rates; the exchange-rate history (demo readings labelled). Manual workbook import (`tariff:manage`) → a **draft**, reviewed with the 13H diff and Approve / Reject, shown **only to a designated approver** (`VersionReview`, refactored out of `TariffUpdatesPanel.jsx`, which behaves as before) |
| Master milestone | `features/workspace/MasterActions.jsx` | Record once on the master; the server writes it on every member. Template or own wording (never both), as on a shipment. The result lists updated / already had it / refused (with the reason) and takes focus |
| Complete / cancel a master | same | Complete (booked) and Cancel (open or booked; a reason is required) each behind a confirmation dialog |
| Edit an item | `features/workspace/CustomerCard.jsx` (`EditItemForm`) | Description, quantity, unit, weight, notes; changed fields only; an emptied weight is cleared; focus returns to the item's Edit button |
| Printable quote | `features/workspace/QuotePrintPage.jsx`, route `/workspace/quotes/:shipmentId/:version/print`, link "Print customer quote vN" in the quote panel | Company details as on invoices (OD-64: legal name, BN 795093756RT0001, 2446 Cawthra Road B1U8, Mississauga ON L5A 3K6), the customer, Air Standard / Air Express, the base freight line, the surcharges the customer pays, total before tax and the tax note; the invoice print CSS |
| Quote document route | `api/v1/routes/quote_offers.py`, `schemas/quote_offers.py` (`QuoteDocumentOut`) | `GET /shipments/{id}/quotes/{version}/document`: an allowlist read by the 13G `build_customer_view`; finalised or superseded (with `superseded_by_version`); a draft is 409; same permissions as reading a quote |
| Finance settings | `services/finance_service.update_settings` | A save that changes nothing writes nothing and no audit entry |
| Review state on versions | `api/v1/routes/tariffs.py`, `schemas/tariff.py` | `review_decision` on `GET /tariffs/versions` and `/tariffs/versions/{id}` |
| Customer milestone emails | `features/customers/NotificationChoicesCard.jsx` on the customer record | The four choices (received, in transit, out for delivery, delivered); `tracking:write` saves them on the customer's behalf |
| Invoice terms | `features/finance/FinancePage.jsx` (`FinanceSettingsCard`), Finance → Periods | Invoice due days, 0–365; Admin saves; the tax setting is shown |
| Translations | `i18n/en.js`, `i18n/vi.js` | `pricingSettings`, `tariffBrowser`, `masterOps`, `quoteDoc`, `customerNotify`, `financeSettings` and new `workspace` keys, at parity |
| Tests | `backend/tests/test_phase14_staff_screens.py` (4); `frontend/tests/pricingSettings.test.jsx` (12), `tariffBrowser.test.jsx` (8), `masterActions.test.jsx` (11), `customerNotifyFinanceSettings.test.jsx` (4); Playwright `staffPricingSettings.spec.js`, `staffMasterEvents.spec.js`, `staffQuotePrint.spec.js` (helper `workspaceHelpers.js`) | See §3 |

## 2. Trying it

Rebuild the demo (`scripts/workspace_demo_env.py --reset`) and start it as in
`11_PHASE_13D_RECORD.md` §2. As the demo administrator: **Settings → Pricing** (change a rate,
edit a surcharge policy), **Settings → Tariffs** (open a version; import the sanitized fixture
workbook as a draft and review it as the approver). In the **Workspace**, open `MST-000001`:
**Record a milestone** (open a member shipment to see it on its timeline), **Edit** an item,
finalise a quote and use **Print customer quote**; Complete / Cancel master ask first. On a
customer record, **Milestone emails**; in **Finance → Periods**, **Invoice terms**.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,123 passed, 1 skipped; 2 failed, the known environmental pair |
| ruff check / format | clean (324 files) |
| eslint, vitest | clean; 710 passed |
| vite build | built |
| Playwright (run alone) | 315 passed |
| Alembic on a scratch database | head `c5e8a1f3d7b9` (no migration in this phase), check clean, downgrade -1, upgrade |
| Verifiers | every check passed |

Independent tester: 17 backend and 15 frontend golden tests, no blocking defect. Independent
reviewer: no high finding; three medium and the low findings fixed (§4a).

## 4. Stand-ins (unspecified behaviour; the safest choice taken)

| Question | Stand-in |
|---|---|
| Language of the printed quote | The staff member's interface language (English or Vietnamese); the figures are identical |
| Surcharge names on the printed quote | The same customer-facing descriptions as the 13G offer (from the vendor sheet; open question 4) |
| Who sees Settings → Pricing and Tariffs | Everyone with `tariff:read` (Operations, Admin) reads; only Admin saves pricing, only `tariff:manage` imports, only a designated approver sees Approve / Reject |
| A rejected draft in the browser | Shown as "Rejected by approver" with no review actions (it can never be activated, 13H) |
| Sea | Not listed: sea products and sea-only accessorials are hidden; only the HCM and Hà Nội air surcharge sheets have policies (OD-49) |
| Workspace permission checks | The master's milestone, complete and cancel buttons are hidden without `tracking:write` / `shipment:write`; the server refuses anyone else |
| Invoice terms location | Finance → Periods (finance settings had no screen before) |
| Cancelling a master whose customers are already quoted | The confirmation lists members with a finalised quote or an accepted offer and warns that cancelling does not withdraw them; the server rule is unchanged (cancel releases members; quotes and offers stay as they are). The list is read from what the workspace page already loaded for each customer card, with no extra request |
| A superseded quote version | Printable, marked "Superseded by vN" on the page; a draft has no document (409) |
| A milestone that reached no shipment | Shown as a failure with each member's reason, not as a recorded milestone |
| Item units | The server's allowed list (piece, pair, box, bottle, set, kg, carton, other), mirrored on the screen; the server stays the authority |

## 4a. Independent review and test fixes (2026-10-20)

Eleven findings (three medium, eight low), all fixed (DEC-0215, "Review fixes"): superseded
versions printable with a note; a milestone that reached no shipment shown as a failure;
pricing, milestone-email and due-days forms safe against a refetch (changes measured from what
was loaded; only changed choices sent; Save disabled when nothing changed); the tax setting
worded; units as a select of the server's list; two decimals on the default markup; the 4 MB
workbook limit checked before upload, with the importer's counts and warnings shown after
import; master buttons hidden without the permission; Vietnamese "Sửa món hàng" / "Lưu món
hàng"; a finance-settings save that changes nothing writes no audit entry; the cancel
confirmation lists customers already quoted. New tests in `test_phase14_staff_screens.py` and
the four Phase 14 vitest files.

The tester's `backend/tests/test_phase14_golden.py` changed in one place, because fix 10
changes the intended behaviour: in `test_finance_due_days_validation` the first PATCH (0) equals
the unsaved default (0), so it is no longer audited; the expected audit list became `[365, 30]`
(was `[0, 365, 30]`). `frontend/tests/phase14Golden.test.jsx` is unchanged.

## 5. Not done

The printed quote is not produced in the customer's language when it differs from the staff
member's; nothing is emailed or attached from the print page (sending stays the 13G offer); no
sea screens; the Vietnamese wording awaits review by Vietnamese-speaking staff.
