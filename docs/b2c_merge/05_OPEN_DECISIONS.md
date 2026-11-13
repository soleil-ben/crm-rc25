# 05 — Open decisions for the B2C merge

Only the owner (or, where marked, the vendor) can answer these. Each names what is blocked
and what proceeds meanwhile. Nothing here is invented; where a default is proposed it is
labelled as such and the engine will mark results "provisional" until confirmed.

## Owner decisions

| ID | Question | Blocks | Proposed default while open |
|---|---|---|---|
| D-01 | **Answered 2026-10-19 (OD-42, DEC-0174): `STCA-`.** Issued `CUS-` identifiers renamed by migration `a7c3e1d9b2f4`, former ones kept as aliases, six digits kept | — | — |
| D-02 | **Answered 2026-10-19 (OD-43, DEC-0175): a sellable Solaris service mapped per tariff version to one vendor product; air only for now (Air Standard → `AIR-CAD`, Air Express → `AIR-CAD EXPRESS`); Sea deferred; UPS unpriced.** Original question: canonical service taxonomy: `Air Standard`, `Air Express`, `UPS`, `Sea` (handoff) vs the Package's `service_type` (standard_parcel / express_parcel / epacket / other) × `transport_mode`. Proposal: add a **vendor product** dimension (Kango `AIR-CAD`, `AIR-CAD EXPRESS`, `KSN-SEA-CAD-PURO`, `-BH`, `-TRUCKING`, UPS direct) and map each sellable service to one vendor product per tariff version | Pricing engine design | Build the mapping table; UPS / Air Express have **no tariff on file** and cannot be priced |
| D-03 | **Answered 2026-10-20 (OD-79): Air Standard and Air Express.** Original question: Which customer-facing **service names** appear on quotes and tracking (Solaris names, never Kango's)? | Document templates | "Air Standard / Air Express / Sea / UPS" |
| D-04 | **Answered 2026-10-19 (OD-44, DEC-0176): per-rule markup (pass-through, fixed CAD or percent), default pass-through at SELL, negative margin refused without a reasoned override; real markups set later in Settings.** Original question: surcharge markup policy: pass-through at SELL, fixed CAD, percentage, or per-rule? (v2.1 §2 says pending.) Note: pass-through at SELL with 0 markup bills below cost | Finalising any quote with surcharges | Engine computes revenue − cost per fee line and **refuses to finalise a negative-margin fee without a reason**; markup field exists, default 0, labelled provisional |
| D-05 | Rounding and display: round VND per-bill prices to whole VND? CAD to cents per line, totals from rounded lines? | Golden tests | Store exact; present rounded; totals = Σ rounded lines |
| D-06 | **Answered 2026-10-19 (OD-45, DEC-0177): Operations sees vendor cost, confirms the default rate, and overrides or waives with a typed reason; every act audited; Admin reviews the log. Marketing and the read-only manager see no cost.** | — | — |
| D-08 | **Answered 2026-10-20 (OD-77): staff send the quote; the customer accepts it in the Customer Account (Phase 13G).** Original question: Does the customer **quote acceptance** happen in the Customer Account portal (new surface) or stay staff-recorded for the first release? | Phase order | Staff-recorded first (v2.1 §6 agrees); portal acceptance later |
| D-10 | **Answered 2026-10-20 (OD-65): due on issue.** Original question: Payment terms: must payment precede dispatch? Partial payments allowed? | Finance model defaults | Configurable; no gate by default |
| D-11 | **Answered 2026-10-20 (OD-64): GST/HST per invoice 0/5/13 %, only for domestic moves; BN 795093756RT0001; INV-/RCT- kept.** Original question: Tax on customer invoices (HST applicability, wording) and invoice numbering | Invoice generation | Invoices marked "tax review pending" until answered |
| D-12 | **Answered 2026-10-20 (OD-76): rate emails arrive in Ben's Soleil mailbox; Ben approves new tariff versions (Phase 13H).** Original question: Vendor **rate email** workflow (v2.0 §7): which mailbox, who approves a new tariff version? | Later phase only | Manual workbook import with approval |
| D-13 | **Answered 2026-10-20 (OD-71): Vietnamese first, English option.** Customer Account in Vietnamese: lift OD-39 (English first) now that the directive asks for EN/VI? | Account UI work | Keep OD-39 until the owner changes it |

## Finance questions raised by Phase 13E (2026-10-20)

| ID | Question | Meanwhile |
|---|---|---|
| OD-66 | Customer payments in VND | **Answered (2026-10-20); superseded by OD-73 with the same result: CAD to VND, so the selling rate on the invoice date** |
| OD-67 | Vendor bills in VND | **Superseded (2026-10-20) by OD-73: Vietcombank buy rate (first column) on the bill date** |
| OD-73 | FX rule everywhere | **Answered (2026-10-20): VND to CAD at the buy rate, CAD to VND at the sell rate (DEC-0212)** |
| OD-74 | Surcharge markup | **Answered (2026-10-20): 2 % default, configurable; per-rule policy overrides (DEC-0212)** |
| OD-69 | Who may refund, void and reopen | **Answered (2026-10-20): Admin and Operations** |

OD-68 is answered: no customer credit ("do not enable credits").

## Build direction of 2026-10-24 (Ben) -- RC-UAT-21

Applied in the RC-UAT-21 build (`25_BUILD_RC21_RECORD.md`, DEC-0230 to DEC-0233).

| OD | Question | Answer | Applied as |
|---|---|---|---|
| OD-109 | P-9 quote tax wording | **Open, stand-in in force, pending Ben**: domestic quotes say GST/HST included at the destination province's rate; international quotes zero-rated | Customer Account quote and printed quote (DEC-0232); supersedes OD-108's tax note |
| OD-110 | Build now or wait for UAT? | Build every remaining feature now with safe stand-ins, each an open question; not returns, staff MFA, production email or provider sync | Shipment import and legacy baseline (OD-15, OD-16), account security, quote soft delete (OD-107), retention machinery disabled (OD-01, OD-36); stand-ins A-1..A-14, B-1..B-14, D-1..D-12 in `19_OWNER_QUESTIONS.md` §0000 |

## Owner answers to the RC-UAT-19 questions (Ben, 2026-10-23)

Applied in the RC-UAT-20 fix pack (`24_FIXPACK_RC20_RECORD.md`).

| OD | Question (sheet 19) | Answer | Applied as |
|---|---|---|---|
| OD-102 | P-1, P-2 GST/HST on draft invoices | International zero-rated 0 %; domestic included and backed out at the destination province's rate (ON 13, NS 14, NB/NL/PE 15, others 5 % GST) | Auto-filled from the route and the `tax_rates` config table; staff may change; tick kept (replaces the 13 % stand-in, OD-94) |
| OD-103 | P-3 costume jewellery | Staff enter both the vendor's VND cost and the customer price; no defaults; finalise blocked until both | Two fields per line (replaces OD-93's stand-in) |
| OD-104 | P-4 Vietnamese leg names | Approved | "Theo dõi chặng chính" / "Theo dõi chặng cuối" |
| OD-105 | P-5 vendor-addressed links | Stay hidden | Unchanged |
| OD-106 | P-6 directly issued invoices | Unchanged | Unchanged |
| OD-107 | P-7 Admin delete of retained quotes | Later | Deferred |
| OD-108 | Wording | Keep "Tổng cộng" (tax added on the invoice note) and "Ghi chú từ Solaris Express" | Pinned by test |

## Owner answers to the RC-UAT-18 follow-ups (Louis Tong, 2026-10-22)

Answered on Ben's behalf; applied in the RC-UAT-19 fix pack (`23_FIXPACK_RC19_RECORD.md`).

| OD | Question (sheet 19) | Answer | Applied as |
|---|---|---|---|
| OD-91 | Q-P1 last-mile carrier link | Links stay visible; hide the vendor name in any label or text around them | Carrier links shown with a neutral label; vendor-hosted links stay hidden (stand-in) |
| OD-92 | Q-P2 vendor names in milestone / tracking names | Generic names: **Master Tracking** (Vietnam to the vendor's Canadian warehouse), **Last Mile Tracking** (vendor warehouse to Solaris or final destination) | Customer-facing leg names; Vietnamese "Theo dõi chặng chính" / "Theo dõi chặng cuối" proposed, for review |
| OD-93 | F-1 costume jewellery (HCM row 27) | Manual quote input: staff enter the charge | Fee line amount entered by staff (stand-in: vendor's quoted VND); no kg basis |
| OD-94 | F-3 GST/HST on draft invoices | Rates are all-in: auto-fill tax, show totals tax-included, confirm before Save/Send, staff may change | 13 % included (backed out) auto-filled; confirmation required (pending: rate for VN to CA air; included vs added) |
| OD-95 | F-4 quote with an issued invoice | Does not expire (keep); minimal storage; Admin manual delete later | Unchanged; delete logged as a future item (not built) |
| OD-96 | F-5 email on expiry | None | Unchanged |
| OD-97 | F-6 relock | Keep: relock when a member quote is finalised | Unchanged |
| OD-98 | F-7 booked-master quotes | Do not expire; same retention note | Unchanged |
| OD-99 | F-8 exception milestone | Not "received", OK for now | Unchanged |
| OD-100 | F-9 Back button on unsaved draft | OK without a warning | Unchanged |
| OD-101 | F-10 whole-word matching | OK for now | Unchanged |

## Owner answers to the RC-UAT-17 questions (Louis Tong, 2026-10-21)

Louis Tong, project owner and developer, answered on Ben's behalf (15:50 ET; item 9a confirmed
16:02 ET). Applied in the RC-UAT-18 fix pack (`22_FIXPACK_RC18_RECORD.md`, DEC-0219 to DEC-0222).

| OD | Question (sheet 19) | Answer | Applied as |
|---|---|---|---|
| OD-81 | D-07 Express zone 2 drop at 16 kg | Correct; follow the sheet exactly; no flag | The three drops are owner-confirmed price steps in the import report, not anomalies |
| OD-82 | D-09 HCM meat / egg / dairy / honey | 20,000 VND/kg for route VN-CA | HCM air row 41 at 20,000 VND/kg on the Vietnam to Canada air route, full carton |
| OD-83 | V-20 per-kg basis | Follow the sheets and notes exactly; silent notes keep current behaviour; pharma on the item's own kg | No scope change (table below); pinned by a regression test |
| OD-84 | Surcharge names customer-safe | No vendor or carrier name on anything customer-facing, surcharge labels included | Neutral label wherever vendor text names a vendor (Customer Account, printed quote, invoices and PDFs, receipts, emails) |
| OD-85 | Vietnamese wording review | Accepted as is | No change |
| OD-86 | Air Express default rate | None; manual rate on each quote | Confirmed; test kept |
| OD-87 | Vendor rate-email mailbox | benjamin.le@soleiltransportation.com for now (D-12) | Confirmed (OD-76 defaults); no live mailbox yet |
| OD-88 | Edits after booking | A booked master locks items and fees; Admin unlocks with a reason, audited | Lock, Admin unlock, relock (DEC-0219) |
| OD-89 | Invoice on acceptance; quote expiry | Acceptance creates the invoice as a draft; quotes expire only when goods are not yet received AND a new tariff version becomes active | Draft on acceptance; expiry on tariff activation (DEC-0220, DEC-0221) |
| OD-90 | Draft invoice screen | Save, Send (issue and email), Download (PDF), Edit; Save before anything else; edits audited | Draft screen, revision-checked saves, DRAFT watermark (DEC-0221) |

### OD-83: the kg basis of every air per-kilogram surcharge, as the Kango notes state

Notes read from sheet `PHỤ THU` of the sanitized workbook (identical to the vendor file apart
from the removed staff sheet). The footer B105 says per-kg surcharges are charged on the full
carton's kg, not each item's own kg.

| Section / row (cell) | Surcharge | What the row's note says about the basis | Basis applied |
|---|---|---|---|
| HCM 14 (B23) | Fake brand clothing, 30,000/kg | D23: full carton, not split by item | Full carton (note agrees) |
| HCM 21 (B30) | Incense, 120,000/kg | Silent | Full carton (footer; kept) |
| HCM 22 (B31) | Books, 15,000/kg | Silent | Full carton (kept) |
| HCM 23 (B32) | Bird's nest, 350,000/kg | D32: 1 kg cap per bill only | Full carton (kept) |
| HCM 24 (B33) | Cordyceps / saffron, 150,000/kg | Silent | Full carton (kept) |
| HCM 25 (B34) | Jarred bird's nest, 30,000/kg | Silent | Full carton (kept) |
| HCM 27 (B36) | Costume jewellery, 100,000–300,000/kg, quoted case by case | D36: case by case | **Manual quote input: staff enter the charge (OD-93, 2026-10-22)** |
| HCM 32 (B41) | Traditional medicine, 30,000/kg | Silent | Full carton (kept) |
| HCM 35 (B44) | False lashes / wigs, 30,000/kg | Silent | Full carton (kept) |
| HCM 37 (B46) | Stones, 200,000/kg | Silent | Full carton (kept) |
| HCM 38 (B47) | Milk powder, 20,000/kg | Silent | Full carton (kept) |
| HCM 39 (B48) | Pharmaceuticals, 200,000/kg | Silent | Item's own kg (owner rule, OD-70) |
| HCM 40 (B49) | Seeds / rice, 30,000/kg | Silent | Full carton (kept) |
| HCM 41 (B50) | Meat / egg / dairy / honey, 20,000/kg (OD-82) | D50: routes only | Full carton (kept) |
| HCM 42 (B51) | Foreign herbal medicine, 120,000/kg | Silent | Full carton (kept) |
| HCM 43 (B52) | Foreign cosmetics / supplements, 30,000/kg | Silent | Full carton (kept) |
| HCM 46 (B55) | Medicinal oils, 30,000/kg | Silent | Full carton (kept) |
| HCM 48 (B57) | Non-electronic machines, 10,000/kg | Silent | Full carton (kept) |
| HCM 49 (B58) | Test strips / Salonpas, 30,000/kg | Silent | Full carton (kept) |
| HCM 51 (B60) | Wood, 20,000/kg | Silent | Full carton (kept) |
| HN 1 (B64) | Pharmaceuticals, 200,000/kg, min 1 kg | D64: routes only | Item's own kg (owner rule, OD-70) |
| HN 2 (B65) | Meat / egg / dairy / honey, 15,000/kg | D65: routes only | Full carton (kept) |
| HN 3 (B66) | Bird's nest, 300,000/kg | D66: routes and a 1 kg cap | Full carton (kept) |
| HN 4 (B67) | Seeds, 15,000/kg | D67: routes only | Full carton (kept) |
| HN 5 (B68) | Fake goods, 15,000/kg | D68: routes only | Full carton (kept) |

HCM 44 and HN 8 (plants) apply to EU/UK only and are not priced for Canada. HCM 47 (fumigation)
is per shipment ("550.000/1 Lô Hàng"), not per kg. A full-carton rule on a master with several
cartons is priced on the master's chargeable kg and flagged provisional
(`full_carton_uses_master_weight`), unchanged.

## Vendor (Kango) questions — surfaced by the workbook audit

The owner answered V-01 … V-19 on 2026-10-19 (OD-49 … OD-63) and set the scope to **air
only** (OD-49). V-20 (non-pharma per-kg) and D-07 / D-09 remain open; the owner answers them later and development continues on stand-ins (OD-80). OD-75 confirms a CAD invoice paid in VND converts at the sell rate. OD-78: no QuickBooks export.

| ID | Question |
|---|---|
| D-07 | **Answered 2026-10-21 (OD-81, Louis Tong): correct; follow the vendor rate sheet exactly, no flag.** Original question: Express zone 2 price drops at 16.0 kg (HCM, HN; HN Express zone 3 too) — typo or intended? Which of 15.5 / 16.0 is wrong? Also the larger steps at 10.5, 15.5, 20.5 kg |
| D-09 | **Answered 2026-10-21 (OD-82, Louis Tong): 20,000 VND/kg for route VN-CA.** Original question: HCM Air row 41 (meat / egg / dairy / honey): confirm Canada = 20,000 VND/kg, not the 10,000 printed |
| V-01 | **Answered 2026-10-19 (OD-50, DEC-0191): per shipment, every weight; 0.5 kg steps: x.0–x.1 → x.0, x.2–x.6 → x.5, x.7–x.9 → next whole kg.** Original question: Weight bands 0.5–20.5: is the label the upper bound of a 0.5 kg band? Round up to the next 0.5 kg? Per piece or per shipment? |
| V-02 | **Answered 2026-10-19 (OD-50): the same rounding above 20.5 kg (20.6 → 20.5, 20.7 → 21).** Original question: Above 20.5 kg: confirm round-up to whole kg and inclusive tier bounds; what applies to 20.6–20.9 kg? |
| V-03 | **Answered 2026-10-19 (OD-51): the matching band's rate on the rounded weight; no minimum bill.** Sea minimums out of scope (OD-49). Original question: Is the ≥ 21 kg per-kg price applied to the whole weight with no minimum bill? Minimum billable weight for Sea (tables start at 21 kg)? |
| V-04 | **Answered 2026-10-19 (OD-52): divisor 6000 for everything.** Original question: Dimensional divisor 6000 for all Purolator-delivered services, 5000 trucking — per piece then summed, or on the shipment envelope? |
| V-05 | **Answered (OD-46): Kango always delivers to L5A 3K6.** Beyond code **180**: rates, or is service refused to those 123 postal codes? **Moot for vendor cost (OD-46, 2026-10-19): vendor cost is zoned at L5A 3K6, which is not beyond-area.** Still relevant if a direct final-mile service is ever priced from this tariff |
| V-06 | **Answered 2026-10-19 (OD-53): convert lb to kg, apply the OD-50 rounding, then the matching band rate.** Not reached while vendor cost is zoned at L5A 3K6. Original question: Beyond fee lb conversion: from unrounded chargeable kg (calculator) or whole-kg rounded (rate sheet)? Per piece confirmed? |
| V-07 | **Answered 2026-10-19 (OD-54): no fixed 19,500; Vietcombank cash buying for VND → CAD, selling for CAD → VND.** Original question: CAD accessorials billed at the fixed 19,500? Validity period of 19,500? Currency of the "$5" name-correction fee? |
| V-08 | **Answered 2026-10-19 (OD-55): vendor data as provided; use as is.** Original question: HCM Air zone 1 = zone 3 prices — intentional? |
| V-09 | **Answered 2026-10-19 (OD-55): vendor data as provided; use as is.** Original question: 35 FSAs with Express zone lower than Ground zone — intentional? Duplicate K1A — confirm ON |
| V-10 | **Answered 2026-10-19 (OD-56, DEC-0193): manual quote, prefilled with the file's minimum.** Original question: Unpriced surcharge rows (HCM Air 4, 5, 10, 13, 27, 31, 33, 34, 45): fixed prices or decision rules, or always manual quote? |
| V-11 | **Answered 2026-10-19 (OD-57, DEC-0192): no overlap; perfume adds 50,000 per bottle; above 30 kg the top tier.** Original question: Nail polish / perfume tiers overlap at exactly 5 and 22 kg; gross or chargeable weight; above 30 kg? |
| V-12 | **Answered 2026-10-19 (OD-58, DEC-0195): not refused; 200,000 VND/kg. The OD-47 block is removed.** Original question: Pharmaceuticals: refused (Air sheet) or 200,000 VND/kg (surcharge sheet)? For Canada? |
| V-13 | **Answered 2026-10-19 (OD-59): up to 3.5 kg the 1–3 kg group, 3.6–8 kg the 4–8 kg group, above 8 kg manual quote.** Original question: Battery rows: 3–4 kg and above 8 kg undefined |
| V-14 | **Out of scope (OD-49): sea is ignored.** Original question: `KSN-SEA-CAD-PURO-BH`: confirm the whole customs-surcharge list is waived |
| V-15 | **Out of scope (OD-49): sea is ignored.** Original question: Sea trucking: 100 kg minimum per pallet or shipment; pallet C$ fees in addition to VND/kg; postal-code delimitation of "surrounding" and "other" areas |
| V-16 | **Answered 2026-10-19 (OD-60): no rounding of VND bill amounts; the vendor bills VND, the customer pays CAD.** Original question: Do you round the computed VND per-bill prices (stored as floats)? |
| V-17 | **Answered 2026-10-19 (OD-61): effective from 12 Oct 2026, no end date.** Original question: Effective end date of the 12 Oct 2026 workbook; will the missing `DASHBOARD` and other sheets be provided? |
| V-18 | **Answered 2026-10-19 (OD-62, DEC-0194): 300,000 Ground / 700,000 Express per carton under 12 kg on lots of 21 kg and over.** Original question: Under-12 kg piece fee on lots over 21 kg: confirm 300,000 (Ground) / 700,000 (Express) per piece and when it applies |
| V-19 | **Answered 2026-10-19 (OD-63): no tracking API yet; manual staff events stay.** Original question: Tracking: is there any authorised API or structured export for booking status? (Needed before any automation; manual staff events continue meanwhile) |
| V-20 | **Answered 2026-10-21 (OD-83, Louis Tong): follow the rate sheets and the vendor notes exactly; where a note is silent keep current behaviour (table below). Pharmaceuticals: the item's own kilograms (OD-70).** Other per-kg rules: still the sheet footer. Per-kilogram surcharges: the handoff's golden case SC-01 charges false eyelashes on the item's own 1 kg (30,000 VND), while the surcharge sheet's footer says per-kg surcharges are charged on the full carton weight. Which is right, rule by rule? Until answered the engine follows the tariff's stored scope (full carton); a per-rule scope override (`item_weight`) applies SC-01's reading without a release (DEC-0186) |

## Already decided by the owner (adopted, not re-asked)

From the master prompt v1.6 §13 and directive v2.1: separate B2C product, Kango CRM
untouched; Vietnam → Canada only for now; one unified workspace; explicit fee selection,
never auto-charge; one permanent customer ID and unique shipment IDs; master cost by CW
share; the 2/3–1/3 full-master rule and triggering-customer billing; $18/kg Air Standard
default with confirmation and reasoned override; customer documents revenue-only; cost at
VCB cash buying, customer surcharge at VCB selling; service chooser Air Standard / Air
Express / UPS / Sea; revenue period = VN hand-in date, transit = flight departure → arrival
Mississauga, M+7 lock; direct costs only in profitability; reporting currency CAD; vendor
cost strictly internal; customers track on Solaris's site, never redirected; manual tracking
first, automation only through authorised access; nothing live without explicit approval.
