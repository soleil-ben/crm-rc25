# Workspace redesign — record

**Asked:** Louis, 2026-11-04: rework the Workspace tab to his handwritten outline; keep
every other function. Decisions DEC-0271 and DEC-0272.

## The page, top to bottom

1. **Master**: master tracking (AWB; it covers every piece), origin (SGN (Hồ Chí Minh City) /
   HAN (Hà Nội)), service (Kango Air Standard, Kango Air Express, UPS, Air Cargo, Sea). Edit
   and Book are here; the lock badge is in the page header.
2. **Master piece #1**: gross weight and dimensions, CW and vendor bill weight from the server,
   optional last-mile tracking. The **vendor base cost** for the whole master sits here:
   the rate-sheet figure, with "Enter a different base cost" (reason required) or, for UPS
   and Air Cargo, the cost and selling rate entered by hand. On a one-piece master, "Packed as
   one box for Kango" is here too.
3. **Customers in piece #1**: each customer's card (billable weight, cost shares, items, fees,
   quote and confirmation, as before). An item whose name matches a Kango surcharge shows
   **"Suggested surcharge … Review and add"**; nothing is added until staff add it.
4. **Add customer to piece #1**: find the profile, or create a new one in a short pop-up.
   Then the reference code, weight and dimensions (live CW), contents, and the sender and
   recipient, filled from the profile's saved addresses. One click books, confirms and places
   the shipment. "Attach an existing booking" still works.
5. **Master piece #2 …**, each with its own customers, and **Add master piece**.
6. **Whole master**: cost vs quote (master / package / customer), vendor bill, milestones and
   closing. The vendor-cost summary stays on the right.

A piece whose CW is lower than its customers' total shows an information note (normal: the
small boxes never fill the master box). Customers on a multi-piece master that are not yet
in a piece appear under "Customers not in a piece", with a selector.

## Pricing changes (DEC-0271)

- **Kango Air Express** is priced on Kango's Express table at zone 3 (warehouse L5A 3K6).
  The selling rate is the one entered for the master, otherwise the Air Express default on
  Settings → Pricing.
- **Base cost override** on any rate-sheet service needs a reason. It is audited and flagged
  on the estimate ("base_cost_overridden").
- **Air Cargo** (new) is priced by hand, like UPS.
- **S1–S7 unchanged** (Air Standard and Sea).

## Names

Staff screens say "Kango Air Standard" and "Kango Air Express". Quotes, invoices and offers
keep the customer names ("Air Standard", "Air Express"), which never mention the vendor
(DEC-0222).

## Backend

- New table `consolidation_piece_tracking` (migration `b2c4d6e8f0a1`).
- New routes: `PATCH /consolidations/{id}/packages/{seq}/tracking` and
  `POST /consolidations/{id}/customers`.
- `GET /consolidations/{id}/packages` now returns `tracking`.

## Tests

- **Backend:** `test_workspace_redesign.py` (Express zone 3, default and entered selling
  rate, override needs a reason, Air Cargo, staff vs customer names, piece tracking, the
  add-customer endpoint including "refused leaves nothing behind" and permissions).
- **Frontend:** `workspaceFlow.test.jsx` (pieces and placement, CW preview, surcharge
  suggestions, piece section, tracking, add customer with address prefill, quick profile),
  plus the base-cost panel tests in `step2Screens.test.jsx`.

## Not done / to note

- **No stored "base cost confirmed" tick.** The base cost is checked against the vendor's
  bill in the Vendor bill panel.
- **Suggestions are word matches.** They use the rule names and notes, so they can miss an
  item described in other words; the full fee list is still one click away.
- **E2E specs not run here.** Their selectors were updated but they were not run in this
  environment.

## Round 2 — owner review of 2026-11-05 (DEC-0273)

| Owner comment | Change |
|---|---|
| New master: split shipment and piece; allow pieces 2, 3 | Part 1 · Shipment (tracking, origin, service); Part 2 · Master pieces: a table of rows, "Add master piece", live CW per row and totals |
| "Packed as one box" — what is it? | Hidden: each master piece *is* the box Kango receives. Pricing unchanged; the global "Per-box fee, cost" setting still decides box vs package |
| "Contents" field — 10 items? | Removed. The add form takes the item list; the contents line is written from the item names; items are created with the booking |
| No remove-item button | "Remove item" on every item (its fees removed first), and in the add form |
| Surcharge list not enough; origin swap needs refresh; "mỹ phẩm" not recognised | All surcharges listed (was 12) with a count; search reads the note too; card remounts on origin change; suggestions match an item name inside a rule phrase |
| No edit for a customer after adding | "Edit customer": reference, weight and size, piece. Locked weights on a booked master (Admin unlock), reference always |
| Too much on screen | Collapsible pieces, customers, cost vs quote, vendor bill, milestones, with summaries; Expand all / Collapse all |
| Save and Book at the end | Fixed bottom bar: "Save and close" and "Book with vendor" |
| "Master" → "Shipment" | Done |

## Round 5 — surcharges per master piece and per shipment (DEC-0276)

From the owner's handwritten cases and answers of 2026-11-06 (air Vietnam → Canada only):

| Fee | Our cost (Kango) | Customer quote |
|---|---|---|
| Banded per piece (nail polish, perfume, battery) | Once per master piece, band on the total kg of that item in the piece (OD-50 rounding; battery 0.1 kg) | Full fee, band on the customer's own kg |
| Flat per piece (HCM-12, 28; HAN-07, 09, 10; manual HCM-04, 13) | Once per master piece | Full fee to each customer with the item |
| Fumigation HCM-47 | 550,000 once per shipment | 550,000 to each customer with wooden items |
| Per kg on the item | Rate × item kg (unchanged) | Same |
| HCM-14 full box | Unchanged (2/3 rule) | Unchanged |

Tests: `backend/tests/test_workspace_per_piece_surcharges.py` (both handwritten cases, rounding
5.1 / 5.2, two pieces, piece not recorded, battery total, flat per piece, fumigation 1 and 2
customers, over 30 kg, no item weight); `frontend/tests/workspaceRound2.test.jsx` (fee picker).
S1–S7 unchanged.

## Round 6 — two panes with data checks (DEC-0277)

Direction B of the 2026-11-06 drafts. New: `WorkspaceTwoPane.jsx` (summary bar, tree,
checklist, customer alerts, piece tables, book confirmation), `workspaceModel.js` (customer
states and checks, pure). `WorkspacePage.jsx` lays them out; `PieceSection` gains
`showCustomers` / `collapsible`, `AttachBooking` is exported, `AddPiece` can open directly.

Tests: `frontend/tests/workspaceModel.test.js`; page tests in `workspaceRound2.test.jsx`
(shipment and checks, one screen at a time, book with problems, customer not in a piece,
unsaved typing, origin change). E2E: the shared helper opens "+ Add customer" from the tree;
the older workspace specs still use pre-redesign selectors and were not run here.
