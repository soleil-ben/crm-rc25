# 02 — Kango workbook audit (`KANGO-CANADA RATES APPLY 12OCT 2026.xlsx`)

Read-only, with openpyxl, against `kango_reference.json` from v1.5. Effective date on the
title: 2026-10-12. The file is an extract of a larger vendor workbook (hyperlinks to a
`DASHBOARD` sheet that is not present).

## 1. Sheets

| Sheet | Content | In the JSON? |
|---|---|---|
| `CHÍNH SÁCH ĐỀN BÙ` | 27 compensation / claims clauses, plus resale-courier and ePacket policies | No |
| `DS SDT NV VẬN HÀNH` | **Vendor staff directory: 10 named people with personal mobile / Zalo numbers** | No — and must stay out of the CRM, logs and shared artefacts |
| `PHỤ THU` | Customs/handling surcharges in 4 sections: HCM Air 51, Hà Nội Air 10, Sea AU/CA/UK/EU 11, Sea USA 13 (+2 advisory rows) | Yes, 85 rows, text byte-identical |
| `HCM-AIR-CAD` | HCM air, duty paid, 5–10 days; Purolator Ground vs Express last mile; two hubs (YVR west, YYZ east) | Rates yes; rules and accessorials no |
| `HN-AIR-CAD` | Hà Nội direct to YVR; same layout **shifted up one row** (no hub-split row) | Rates yes |
| `HCM-SEA-CAD`, `HN-SEA-CAD` | Sea per-kg tiers for PURO, PURO-BH (insured, no customs surcharges) and TRUCKING; HN = HCM + 10,000 VND/kg everywhere | PURO and BH yes; trucking no |
| `Zone CAD` | Calculator + FSA zone table (1,675 rows) + beyond postal codes (16,200) + beyond rates (8) | Yes |

## 2. Rate structure

**Air.** 0.5 → 20.5 kg in 0.5 kg steps, price in **VND per bill**, six price columns
(Ground zone 1/2/3, Express zone 1/2/3). From 21 kg: four **VND per kg** tiers
(21–44, 45–99, 100–299, 300+). Above 20.5 kg the weight is rounded **up to the whole kg**
(21.2 → 22). Chargeable weight = max(gross, L×W×H/6000). HCM zone 1 and zone 3 prices are
identical in every row; HN zone 3 is distinct. Prices are stored as unrounded floats
(e.g. 1,292,966.4000000001) — they were computed, and the vendor's display rounding is unknown.

**Sea.** Six per-kg tiers (21–44 … 1000+), no row under 21 kg, no stated minimum.
Trucking: VND/kg with a 100 kg minimum plus C$ pallet delivery fees by pallet count and area.

**Beyond area.** Fee per piece in **CAD** = base + CEILING(kg × 2.2046, 1) × per-lb rate,
converted at the fixed 19,500; eight rate codes 100–170.

## 3. JSON vs workbook: value-for-value result

| Table | Workbook | JSON | Mismatches |
|---|---|---|---|
| 6 rate tables (HCM/HAN × AIR, AIR-TIERS, SEA) | 102 rows × 7 cols | same | 0 |
| FSA zones | 1,675 rows (K1A listed twice, QC and ON) | 1,674 | 0; JSON kept ON for K1A (correct) |
| Beyond postal codes | 16,200 | 16,200 | 0 |
| Beyond rates | 8 | 8 | 0 |
| Surcharges | 85 priced rows | 85 | 0 in name / rule / note text |
| Exchange | 19,500 fixed | 19,500 | 0 |

So the snapshot is faithful. **What it omits is the problem**, not what it holds.

## 4. Rules the JSON does not carry (must be modelled explicitly)

- Dimensional divisor **6000** (5000 for trucking); whole-kg round-up above 20.5 kg;
  band semantics below 20.5 kg are not stated.
- Per-piece minimums on lots over 21 kg: Air pieces under 12 kg → 300,000 VND (Ground) /
  700,000 VND (Express) each; Sea pieces under 15 kg → 300,000 VND; trucking under 12 kg
  → 500,000 VND. Purolator piece limit 22 kg; hard refusal over 68 kg or 410 cm girth.
- Fuel included, VAT excluded; no PO Box; prohibited-goods list.
- **CAD accessorials** (Purolator): Saturday delivery 21/shipment; address change 5;
  re-delivery 5; address correction 10; signature 3; additional handling 6/piece;
  oversized 9/piece; residential heavyweight 40/piece; large package 35/piece.
  Sea only: name correction $5/piece; CBSA random exam CAD 100/piece.
- **VND fees**: return re-delivery 700,000 (Ground) / 2,000,000 (Express) per piece;
  destruction 500,000/piece; storage 650,000/piece/week after two free weeks; wooden-pallet
  fumigation $10/bill.
- **Beyond code 180 has no rate** anywhere in the workbook (123 far-north postal codes in
  NU, NT, northern QC and ON). The vendor's own formula yields CAD 0 for them. The engine
  must mark them "no rate — refer to vendor", never 0.
- Sea trucking service and its pallet fee table.

## 5. Surcharge semantics that need encoding, not regex

- Every per-kg surcharge applies to the **full carton chargeable weight**, never the item's
  own kg (sheet footer, and the section-3/4 notes).
- **UNPRICED / VENDOR REVIEW REQUIRED** (ranges, "Dự kiến", case by case): HCM Air rows
  4, 5, 10, 13, 27, 31, 33, 34 (battery variant), 45.
- **Tiered by weight via the note, not the price cell**: HCM Air row 1 (nail polish
  300k / 500k / 700k for 1–5 / 5–22 / 22–30 kg; tier boundaries overlap at exactly 5 and
  22 kg) and row 11 (perfume: same tiers **plus** 50,000/bottle).
- **Route-dependent price**: HCM Air row 41 (meat / egg / dairy / honey) lists 10,000/kg but
  the note says 20,000/kg for all air routes other than AU / UK / SG / USA — Canada is 20,000.
- **Not applicable to Canada**: HCM Air row 44 and HN Air row 8 (plants; EU/UK frozen only).
- **Free**: HN Air row 6 (false eyelashes) — the HAN tariff must not charge the HCM rate.
- **Conflict**: pharmaceuticals (thuốc tây) are "absolutely not carried" on the Air sheet
  notes but priced at 200,000 VND/kg on the surcharge sheet (HN: minimum 1 kg).
- Battery rows: 1–3 kg = 300,000, 4–8 kg = 700,000; nothing defined for 3–4 kg or above 8 kg.
- Price strings mix `.` and `,` thousands separators and shorthand ranges (`300 - 700.000`).

## 6. Data-quality anomalies to confirm with the vendor

- Express zone 2 price **drops** from 15.5 kg to 16.0 kg (HCM and HN; HN Express zone 3
  too); the per-step increment is otherwise constant except at 10.5, 15.5 and 20.5 kg.
- 35 rural BC FSAs have a *lower* Express zone than Ground zone.
- Duplicate FSA K1A (QC and ON).

## 7. How the Package should ingest this

Import from the **workbook**, through a versioned importer with provenance (sheet, row,
cell, file hash, effective date), into tariff tables — not from the JSON. Encode the rules
in section 4 and the semantics in section 5 as structured fields on the rule rows
(basis, scope, tiers, applicability by origin and service, pricing status), with the
anomalies in section 6 flagged for vendor review rather than silently reproduced.
