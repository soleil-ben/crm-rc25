# 01 — Handoff audit: what Louis's bundle contains and what v1.5 really does

Read-only audit of `CRM handoff from Louis/Solaris_B2C_CRM_Claude_Fable_Handoff_Bundle_v1.6.zip`
(SHA-256 of every entry matches the bundle's own `06_CHECKSUMS.md`). The v1.5 app was
extracted to `CRM/Solaris_B2C_CRM_dev/` (git baseline `9de8de8`) and run once under its own
`server.py` on port 8765; the audit below is from reading the code and from running its
fee parser in Node against all 85 surcharge rows. Nothing in the handoff folder was changed.

## 1. Bundle contents

| Entry | Size | Role |
|---|---|---|
| `01_MASTER_PROMPT/…Master_Prompt_v1.6.md` | 69 KB | Requirements and owner decisions (13 confirmed, 9 open) |
| `02_LATEST_APP_BASELINE/Solaris_B2C_CRM_Full_Review_v1.5.zip` | 225 KB | The code: 3 HTML files, 1 JS data file, 1 JSON, `server.py`, `START_CRM.bat` |
| `03_VENDOR_TARIFF/KANGO-CANADA RATES APPLY 12OCT 2026.xlsx` | 953 KB | Vendor tariff, effective 2026-10-12 (see `02_KANGO_WORKBOOK_AUDIT.md`) |
| `04_ORIGINAL_APPROVED_FEE_UX/Solaris_B2C_CRM_MVP_v0.7.zip` | 145 KB | Older calculator; the approved "search → applicable kg/qty → Add Fee" interaction |
| `05_HISTORICAL_REFERENCE/` | 139 KB | v1.0 implementation prompt, discovery questionnaire (.docx), tracking prototype (.xlsx) |

## 2. What v1.5 is

A **browser-only prototype**: three static HTML pages with inline vanilla JavaScript, all
persistence in one `localStorage` key (`solaris_b2c_crm_v01`) as a single JSON document, and
a Python standard-library server whose only API is `GET /api/fx` (Vietcombank CAD cash-buy
rate, polled every 300 s while the process runs). No users, no roles, no database, no tests.

| File | Purpose | Lines of note |
|---|---|---|
| `app/index.html` | CRM shell: Dashboard, Customers, Smart Quotation, Shipments, Batches, Finance, Reports, Settings, Allocation Studio, backup/restore, embeds the cost calculator in an iframe | 70 KB; loads the store once and never re-reads it |
| `app/workspace.html` | **Unified Calculator v1.5**: master booking → N customer cards → items → searchable Kango fee → Add Fee → COST / QUOTE / profit → save → print quote | 33 KB; the part worth keeping, as behaviour |
| `app/cost_calculator.html` | Older Kango vendor COST calculator (multi-box, FSA zone, beyond area, fee preview) | 322 KB, of which 294 KB is the embedded JSON a third time |
| `app/kango_data.js`, `app/kango_reference.json` | Snapshot of the workbook: 6 rate tables, 1,674 FSAs, 16,200 beyond postal codes, 8 beyond rates, 85 surcharges, FX 19,500 | Byte-identical copies |
| `server.py` | Static host + VCB cash-BUY watcher | Serves `/api/fx` only; never parses the SELL rate |

Observed on first load of `workspace.html`: an uncaught `TypeError` in `renderCustomers`
(reading `map` of undefined) from the bootstrap `addCustomer()` call. The page renders but
the console error is real; it was not chased further because the code is not being adopted.

## 3. The business logic worth carrying over (behaviour, not code)

These are the parts of v1.5 that encode owner-approved behaviour and should be re-implemented
server-side in the Package:

1. **Unified entry**: one master vendor booking, many customer shipments, each with items,
   fees and its own confirmed selling rate; staff never re-enter the same data on another tab.
2. **Fee UX**: searchable fee list (accent-insensitive, filtered to the selected origin and
   service tariff) → pick one → enter applicable kg or units → **Add Fee** → a separate
   breakdown line. Product names may *suggest* a fee; nothing is charged automatically.
3. **Chargeable weight**: `max(actual, L×W×H / divisor)`, divisor 6000 by default.
4. **Master base cost allocation**: by child chargeable-weight share.
5. **Full-master fee allocation** (owner decision 7): one triggering customer → that
   customer carries 2/3 of the vendor COST, the other 1/3 is split equally among the others;
   two or more triggers → COST split among triggers by CW; the customer *surcharge revenue*
   is billed only to triggering customers (fully to one, by CW among several).
6. **Air Standard selling rate** defaults to CAD 18/kg for every customer; staff must
   confirm; any other value needs a reason; editing weight, rate or fees revokes confirmation.
7. **FX**: vendor COST VND→CAD at Vietcombank **cash buying**; customer surcharge VND→CAD at
   Vietcombank **selling**. Surcharge markup is not configured (0) and is an open decision.
8. **Customer documents** show revenue only, never vendor cost or profit.

## 4. The implementation facts that argue against adopting the code

| Finding | Where | Consequence |
|---|---|---|
| Three independent pricing engines write the same collections | `index.html` Smart Quotation (CAD rate cards), `index.html` Allocation Studio (3 hard-coded VND rules), `workspace.html` `compute()` (parsed tariff) | Competing ledgers; `masterFees` rows from the two engines use different field names (`buy/sell` vs `fxBuy/fxSell`) and `kind` vocabularies |
| Whole-document overwrite, no re-read in `index.html` | `save()` | Two tabs open → the last writer silently discards the other's shipments and can reissue the same IDs |
| Shipments form cannot be saved at all | `index.html` `hookForms.shipForm` validates a `revenue` field the form does not have → always throws | Core page broken in the supplied baseline |
| Non-Air-Standard masters cannot be saved | `workspace.html` `compute()` raises a blocking issue for UPS / Air Express / Sea | Only one service works end to end; a quote can still be *printed* for an unsaveable master |
| Fee parser misprices rules written as `N/1kg` or `N/1 Kiện` as **1 VND** | `parseRule`: ids 48, 59, 60, 61, 67 | Silent under-charging; no warning |
| `Dự kiến >…` estimates priced as fixed; perfume per-bottle component dropped; SEA "full của kiện" notes ignored | `parseRule`, `ruleMeta` | Wrong amounts on ids 4, 10, 11, 63–72 |
| Surcharges billed below cost by construction | cost at BUY, revenue at SELL, markup 0 | Every pass-through surcharge loses `(sell−buy)/sell` |
| `Air Standard` saved as `Air Cargo`; `Sea` vs `Sea Parcel`; `UPS` unknown to the shell | `saveWorkspace`, `index.html` selects | Inconsistent service taxonomy |
| Child shipment saved as one box (`pieces:1`) with one weight and one set of dims | `saveWorkspace` | No per-box model |
| Dimensional divisor 6000 in workspace and calculator, 5000 in shell settings; shell multiplies dims by pieces | `cweight`, `boxCW`, `cw()` | Same shipment → different chargeable weight by page |
| `/api/fx/cad` and `/api/fx/cad/full` requested, only `/api/fx` served; SELL never parsed | `fx()`, `server.py` | Live FX never works in the workspace; manual entry with no plausibility bounds |
| `rateConfirmedBy` is a hard-coded string | `saveWorkspace` | No identity, no audit |
| Crafted backup JSON is installed as the whole store with a key-presence check only; several `innerHTML` sites take raw values from it | `restore()`, `reports()` | Injection vector |
| Dead code: the v0.5 automatic fee engine, several helpers | `cost_calculator.html` | Noise |

The full function inventory, store schema and per-function notes are preserved in the
audit transcript; the table above is what matters for the merge decision.

## 5. Conclusion

Adopt v1.5's **behaviour** (section 3) and its **data** (the workbook, re-imported from the
source file, not the JSON). Do not adopt its code: the Package already has the persistence,
identity, roles, audit, privacy guards and tests that v1.5 lacks, and v1.5's own financial
engine has defects (section 4) that a port would carry across.
