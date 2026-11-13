# Method v0.6 (backend only) — record

**Asked:** Louis, 2026-11-03. Apply `cost-quote-method.md` v0.6 (decision log §12, entries 12–25)
and the owner's per-kg rule; backend only; no screens until "go".
**Sources:** `kango_rate_sheet_2026-11-03.xlsx` (sha256 `77111422…`), `rates_2026-11-03.json`,
`cost-quote-method.md` v0.6, `case_study_results_v0.6.csv`. Decisions DEC-0253 to DEC-0259.

## 1. What changed

| Area | Change |
|---|---|
| Switch | `pricing_method` `v0_6` (default) or `rc25`; `v0_5` accepted as an alias (DEC-0253) |
| Schema | Migration `d4f6a8c0e2b4`: `sea_vendor_rates`, `sea_surcharge_rules`, `consolidation_package_notes`, `consolidation_package_members`; nothing altered |
| Rates | 2026-11-03 sheet as a tariff version (`scripts/load_kango_rate_sheet.py`), sanitized fixture committed (DEC-0254) |
| Engine | Piece fee cost only, by the carton's customers (DEC-0255); box bands on OD-50 box weight (DEC-0256); Sea vendor rate + SEA ITEM + MIN (DEC-0257); per-package whole-package fees when packages are recorded (DEC-0258); Express zone-3 reference, never cost |
| Service / API | Sea fee lines (`section: sea_vendor`); package note and member routes; effective-dated sea cost; `default_markup_label` "RC25 method only" |
| Screens | None (step 2) |

## 2. Tests

* `tests/test_method_v06_golden.py`: S1–S7 to the cent against `case_study_results_v0.6.csv`
  (29 rows), rates read from the committed 2026-11-03 sheet; sea minimum, piece fee, Express
  reference, zone 2, Q6.
* `tests/test_method_v06_service.py`: all 180 Soleil-zone cells in the database vs the rates
  JSON; all zones loaded; zone check; origin/service selection and re-pricing; booked master
  keeps the old sheet; sea fee lines; package note/members (service and HTTP); per-kg rule.
* `tests/test_method_v05_golden.py`: kept on the 30-Oct rates (v0.5 JSON still exact); the
  5.1 kg test now follows Q6.

## 3. Open items (none blocking)

* Sea vendor bill rounding / divisor (method §11): Kango rounding and 6000 kept.
* Typed carton weight on a per-box line: kept as typed (OD-59 battery groups), not OD-50 (DEC-0256).
* "Packed as one box" on a master with several packages: one-package only for now.
* HCM 44 and HAN 8 are per kg with a special note and are not in the allocation CSV; both are
  refused as not applying to Canada, so neither prices (corrected in the v0.7 record).
