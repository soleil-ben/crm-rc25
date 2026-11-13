# 04 — Issue register (handoff code and data)

Defects found in the v1.5 baseline and the tariff snapshot. None of these is a Package
defect; they are listed so the merge does not import them and so golden tests cover them.
Severity: **H** mis-prices money or loses data; **M** blocks a workflow; **L** hygiene.

| ID | Sev | Where (v1.5) | Defect | Merge consequence |
|---|---|---|---|---|
| H-01 | H | `workspace.html` `parseRule` | Rules written `N/1kg` or `N/1 Kiện` parse as rate **1 VND** (surcharge ids 48, 59, 60, 61, 67) | Structured rule rows with explicit `unit_price`, `basis`; golden test per id |
| H-02 | H | `parseRule` | `Dự kiến >700.000` and `>100.000` priced as fixed (ids 4, 10) | `pricing_status = UNPRICED` blocks finalisation |
| H-03 | H | `parseRule`, `ruleMeta` | Perfume (id 11) per-bottle 50,000 dropped; nail polish / perfume weight tiers only partly implemented; SEA "full của kiện" (full-box) scope ignored (ids 63–72) | Tier table and `scope ∈ {item_kg, full_carton, full_master, per_unit, per_shipment}` on the rule |
| H-04 | H | `compute()`, `index.html allocFeeForm` | Surcharge revenue converted at VCB SELL, cost at BUY, markup 0 → every pass-through surcharge is billed **below cost** | Markup policy is owner decision D-04; engine must show revenue − cost per fee line and refuse negative margin unless overridden with a reason |
| H-05 | H | `index.html save()` | Whole-document overwrite, store read once, no `storage` listener → second tab silently loses shipments and can reissue IDs | Not applicable once persistence is server-side |
| H-06 | H | `index.html` vs `workspace.html` | Dimensional divisor 5000 vs 6000; shell multiplies dims by `pieces` | One divisor per tariff version (6000 air / sea Purolator, 5000 trucking), stored with the quote snapshot |
| H-07 | H | tariff snapshot | Beyond code **180** (123 postal codes) has no rate; vendor formula yields 0 | `beyond_rate = NULL` → "refer to vendor", quote cannot finalise for those postal codes |
| H-08 | H | tariff | HCM Air row 41 (meat / egg / dairy) listed 10,000/kg; note says Canada = 20,000/kg | Importer applies route-specific price; owner / vendor confirm (D-09) |
| H-09 | H | tariff | Plants (HCM 44, HN 8) are EU/UK-only; HN false eyelashes free | `applies_to_routes` on the rule; HAN tariff must never charge HCM rates |
| M-01 | M | `index.html hookForms.shipForm` | Validates a `revenue` field the form lacks → Shipments form can never save | Discarded with the shell |
| M-02 | M | `compute()` → `saveWorkspace` | UPS / Air Express / Sea raise a blocking issue → only Air Standard masters can be saved; a quote can still be printed | Service taxonomy with per-service tariff availability; "no tariff on file" is an explicit state |
| M-03 | M | `saveWorkspace` | `Air Standard` saved as `Air Cargo`; `Sea` vs `Sea Parcel`; `UPS` unknown to shell | Canonical service enum (D-02) with explicit vendor product mapping |
| M-04 | M | `saveWorkspace` | Child saved as one box (`pieces:1`), one weight, one set of dims | Package-level model exists in the Package already (`shipment_packages`) |
| M-05 | M | `fx()`, `server.py` | Requests `/api/fx/cad`, `/api/fx/cad/full`; server serves `/api/fx` only and never parses SELL | New FX job stores BUY, TRANSFER, SELL, bank timestamp, retrieval time, status |
| M-06 | M | `workspace.html` | Manual FX fields have no plausibility range | Range check (server already uses 1,000–100,000 VND/CAD) |
| M-07 | M | `index.html Allocation Studio` | Hard-codes 3 fees; nail polish only priced ≤ 5 kg (`NaN` otherwise) | Discarded |
| M-08 | M | tariff | Express zone 2 price drops at 16.0 kg (HCM and HN); HN Express zone 3 too | Importer flags non-monotonic columns for vendor review (D-07) |
| L-01 | L | `index.html restore()`, `reports()`, `tlink()` | Arbitrary JSON installed as the store; raw values into `innerHTML`; `'` in IDs escapes attribute strings | Not applicable |
| L-02 | L | `index.html message` listener | Checks `e.source`, not `e.origin`; iframe posts to `'*'` | Not applicable |
| L-03 | L | `saveWorkspace` | `rateConfirmedBy` is a hard-coded string | Confirmation is an audited action by a signed-in staff user |
| L-04 | L | `cost_calculator.html` | Dead v0.5 auto-fee engine; JSON embedded a third time; `esc()` misses `'` | Discarded |
| L-05 | L | tariff | Duplicate FSA K1A (QC / ON); 35 BC FSAs with Express zone < Ground zone; unrounded float prices | Importer reports; vendor review (D-07) |
| L-06 | L | workbook | Vendor staff directory with personal phone numbers | Importer must skip that sheet; never store or log it |
| L-07 | L | `workspace.html` first load | Uncaught `TypeError` in `renderCustomers` from bootstrap `addCustomer()` | Discarded |
