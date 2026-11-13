# Method v0.5, step 1 (backend only) — record

**Asked:** Louis, 2026-11-02. Build on RC-UAT-25 as the real system, no second CRM, every existing
function kept working. Step 1, no screens: settings migration, per-package "packed as one box for
Kango" flag, per-surcharge allocation class, engine, golden tests S1–S5, full suite.
**Sources:** `cost-quote-method.md` v0.5 (Louis, all decisions confirmed; source of truth where it
differs from earlier ODs), `method/case_study_results.json`, `data/surcharge_allocation_rules.csv`,
`method/solaris_mockup_v0.5.html`. Decisions DEC-0248 to DEC-0252.
**Update 2026-11-03:** v0.5 switched on as the default (DEC-0252, migration `c2e4a6b8d0f1`); see §4.

## 1. What changed

| Area | Change |
|---|---|
| Switch | `pricing_method_settings.pricing_method`: `v0_5` (default since DEC-0252) or `rc25`. Under `rc25` nothing prices differently and snapshots keep their keys (DEC-0248) |
| Schema | Migration `b8d1f3a5c7e9` (revises `a5c7e9b1d3f6`): five new tables, nothing altered (DEC-0249). Migration `c2e4a6b8d0f1`: data only, sets the row to `v0_5` (DEC-0252) |
| Engine | `app/pricing/method_v05.py` (new, pure). `engine.py`: four optional dataclass fields with defaults (`RuleView.allocation_class`, `FeeLineInput.box_ref/box_kg`, `PackageInput.packed_as_one_box`, `Estimate.method/v05`); no RC-UAT-25 logic changed |
| Service | `pricing_method_service.py` (new): settings read/validate/audit, allocation classes, package flags, manual pricing, UPS bands. `pricing_service.py`: `estimate_for` dispatches on the switch; Sea priced through `KSN-SEA-CAD-PURO` under v0.5; per-customer default rate (`member_default_rate`); `replace_cartons` accepts `packed_as_one_box`; `estimate_dict` adds `method` and `v05` only for v0.5 |
| Data | `data/surcharge_allocation_rules.csv` (115 lines → 70 Kango rows), also in `app/pricing/allocation_classes.py` for databases built without Alembic |
| Routes / screens | None (step 2) |

## 2. Defaults (Louis, 2026-11-02)

FX Kango fixed 19,500 VND/CAD for cost and quote · leftover base freight spread by weight · per-box
fee cost per small box (band on the box weight), packed package once (band on the package weight,
split by weight) · per-box quote: each trigger the full fee, band on its own rounded weight ·
whole-package / whole-master: 2/3 rule, quoted with the same share · markup none, 0 · Air Standard
CAD 18/kg at or above 21 kg of the customer's own rounded CW, CAD 19/kg below · Sea CAD 8/kg ·
Air Express cost and sell manual per master · UPS: five placeholder bands, manual until rates
arrive · vendor bill weight by Kango's rounding (> 20.5 kg up to the whole kg).

## 3. Tests

* `tests/test_method_v05_golden.py`: S1–S5 reproduced to the cent (every customer row and every
  master row of `case_study_results.json`), plus quote-figure consistency, packed vs per-box,
  threshold basis, triggers-only option, unallocated option, markups, Vietcombank source, Kango
  rounding, the 5.1 kg box edge.
* `tests/test_method_v05_service.py`: switch default, the case study on the repository tariff,
  confirm + finalise under Kango FX, packed flag through `replace_cartons`, Express/Sea settings,
  settings validation, CSV load, migration up / check / down.
* `test_migrations_phase13f.py`: head pin moved to `c2e4a6b8d0f1` (the established per-RC update).

## 4. v0.5 on by default (DEC-0252, 2026-11-03)

The 24 existing test files that touch pricing were updated to the v0.5 expectations (36 tests),
and tests about an RC-UAT-25-only mechanism now pin `rc25` explicitly with a v0.5 counterpart.
The differences are the method's intended changes:
CAD 19 instead of 18 under 21 kg (54.00 → 57.00 on a 3 kg quote), Kango 19,500 instead of
Vietcombank (a stale bank rate no longer blocks), no OD-74 2 % default markup, non-triggers billed
their 2/3 share, Air Express cost manual, HCM row 41 (meat) per item kg per the CSV instead of the
full carton (DEC-0222), the piece fee shown as its own line.

## 5. Open questions for Louis (nothing blocking; stand-ins in force)

M-1 Case-study base rates (249,000 VND/kg C50; 1,577,138.1 C17) are not the 2026-10-12 workbook
in this repository (243,000; 1,515,006.4): which Kango rate file? · M-2 Cent rounding: golden =
round each + residual to the largest cost, not largest remainder (DEC-0250) · M-3 HCM row 41
(meat): CSV says item kg, DEC-0222 said full carton · M-4 Piece fee at exactly 21 kg (doc ">21",
OD-62 "21 and over") and whether it is quoted to the customer (mockup: yes) · M-5 OD-74 2 % default
markup retired under v0.5? · M-6 Box band at x.1 kg: cost reads 0.1 kg (DEC-0192), quote uses
OD-50 (5.1 kg box: cost 500k, quote 300k) · M-7 Masters with several packages need a
customer-to-package record · M-8 Sea: piece fee (<15 kg) not in the imported tariff; sea fee
lines cannot be attached (DEC-0195) · M-9 Express manual cost replaces Kango's AIR-CAD EXPRESS
table? · M-10 Kango fixed rate is a setting, not read from the rate file · M-11 Booked masters keep
their OD-50 stored weight, not Kango rounding · M-12 Fixed-CAD markup counts lines per customer.
