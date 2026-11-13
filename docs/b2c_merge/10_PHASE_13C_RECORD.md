# 10 — Phase 13C completion record: pricing engine, fee lines, versioned quotes

**Date:** 2026-10-20 · **Branch:** `phase-13-b2c-merge` · **Base:** c925e75 (Phase 13B) ·
**Migration:** `c9e5a3b7d2f8` (head), from `b8d4f2a6c1e7` · **Decisions:** DEC-0184 to DEC-0196 ·
**Owner decisions:** OD-46 to OD-63 · **Scope:** air only (OD-49)

Backend only. No public or Customer Account route or schema changed; no frontend file
changed. Nothing is deployed. No request was made to the vendor or the bank. Nothing was pushed
or merged.

## 1. What was built

| Area | Files | What it does |
|---|---|---|
| Pure pricing engine | `app/pricing/engine.py` | Vendor cost per consolidation: base freight from the product's per-bill bands (under 21 kg) or the matching per-kg band (21 kg and over, OD-51), zoned at L5A 3K6 (OD-46); the under-12 kg piece fee from recorded cartons (OD-62); surcharges by rule (priced, tiered, free, manual quote); full-master rules charged once and split two thirds to a single trigger (OD-48, configurable); largest-remainder allocation at 0.01; cost at Vietcombank cash buying, customer surcharges at selling (OD-54); per-rule markup (OD-44); blocking and provisional issues |
| Weight rounding | `app/pricing/chargeable_weight.py` | The owner's rule for every weight (OD-50, DEC-0191); divisor 6000 (OD-52) |
| Surcharge semantics | `app/pricing/kango_semantics.py`, `app/core/enums.py` | `manual_quote` status for nine HCM air rows (OD-56); non-overlapping nail polish / perfume tiers with the top tier above 30 kg (OD-57); one battery rule with the owner's groups (OD-59); pharmaceuticals priced at 200,000 VND/kg (OD-58) |
| Settings and policies | `app/models/pricing.py`, `app/services/pricing_service.py` | `pricing_settings` ($18/kg Air Standard default, 2/3 trigger share, flagged pending owner confirmation, OD-48; delivery postal code L5A3K6); `surcharge_rule_policies` (markup, scope override) |
| Fee lines | same | Staff attach air surcharge rules to items (sea refused, OD-49); a manual-quote line may carry the vendor's quoted price |
| Master cartons | same, `consolidation_cartons` | Replaced as a set; drive the piece fee (DEC-0194) |
| Quotes | same | Versioned: one open draft, rate confirmation with an input fingerprint, override with reason (OD-45), finalisation refused on any blocking issue, missing or stale confirmation, or unexplained negative margin; finalised versions frozen with their snapshot |
| Routes | `app/api/v1/routes/pricing.py`, `app/schemas/pricing.py` | 14 staff routes behind `tariff:read`, the financial permissions and `settings:manage` |
| Migration | `alembic/versions/c9e5a3b7d2f8_phase_13c_pricing_quotes.py` | Six new tables; nothing existing altered (DEC-0181) |

## 2. The owner's answers of 2026-10-19 and what they changed

The first 13C draft blocked pharmaceuticals (OD-47), left nine HCM air rules unpriced, flagged
the half-kilogram convention and did not evaluate the piece fee. The owner then answered vendor
questions V-01 to V-19 and set the scope to air only. Each answer is an OD record and is in
force:

| Question | OD | Effect in the engine |
|---|---|---|
| Scope, V-14, V-15 | OD-49 | Sea sections refused on fee lines; no sea tests |
| V-01, V-02 | OD-50 | One rounding rule for every weight; half-kg flags removed |
| V-03 | OD-51 | Band matching the rounded weight; no minimum bill |
| V-04 | OD-52 | Divisor 6000 |
| V-05 | OD-46 | Vendor cost at L5A 3K6 only |
| V-06 | OD-53 | Recorded; not reached (L5A 3K6 is not beyond-area) |
| V-07 | OD-54 | Vietcombank cash buying / selling, no fixed 19,500 |
| V-08, V-09 | OD-55 | Vendor data used as provided |
| V-10 | OD-56 | Manual quote, prefilled minimum, flagged until the vendor's price is entered |
| V-11 | OD-57 | Tiers without overlap; perfume +50,000 per bottle; above 30 kg the top tier |
| V-12 | OD-58 | 200,000 VND/kg; the OD-47 block removed (OD-47 marked disabled) |
| V-13 | OD-59 | Battery groups; above 8 kg needs the vendor's price |
| V-16 | OD-60 | VND amounts not rounded to whole dong |
| V-17 | OD-61 | Effective from 12 Oct 2026, no end date |
| V-18 | OD-62 | Piece fee per carton under 12 kg on lots of 21 kg and over |
| V-19 | OD-63 | Manual tracking events stay |

One reading was needed where two answers meet: the battery groups put 3.6 kg in the 4–8 kg group,
which half-kilogram rounding would undo, so surcharge tiers read the carton weight to 0.1 kg
(DEC-0192).

## 3. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | pass |
| Backend | **3,629 passed, 2 failed** in one run (1,200 s). The two failures are the known environmental pair (`test_e2e_safety.py`, `test_incident_cleanup.py`): this worktree lacks the gitignored development databases. New: `test_quotes.py` (29), `test_pricing_golden.py` (201, written independently from the owner's rules by a subagent), `test_migrations_phase13c.py` (3) |
| `eslint .` | pass |
| Frontend unit | **538 passed**, 39 files (no frontend file changed) |
| `vite build` | pass |
| Playwright, `npm run e2e` | **295 passed**, 11.7 minutes, ports 8190/5390; scratch removed |
| Alembic, disposable database | pass: up, check, 1 down, 1 up; head `c9e5a3b7d2f8` |
| Verifiers | `verify_decision_log.py` (DEC-0184 to DEC-0196 added) and `verify_owner_decisions.py` (63 records) pass |
| Independent golden tests | one engine defect found (per-bill prices carried the workbook's float tail, 884913.6000000001); fixed |
| Independent review | 8 findings (4 medium, 4 low), all applied with regression tests (DEC-0196); one left for the owner, below |

## 4. Still open

**For the owner to confirm.** Pharmaceuticals follow the surcharge sheet footer (per-kg
surcharges on the full carton, V-20), so one pharmaceutical line in a 30 kg master is charged
30 × 200,000 = 6,000,000 VND once on the master, shared two thirds to the trigger. If OD-58
meant the item's own kilograms, a per-rule scope override (`item_weight`) applies it without a
release. Also: with the default pass-through markup, every direct surcharge bills slightly below
cost (selling rate above cash buying), so those quotes need a negative-margin reason until
markups are set (OD-44).


**OD-48** (the $18/kg default and the two-thirds share) is implemented as flagged defaults and
blocks production until the owner confirms it. **V-20** (per-kg surcharges on the item's own
weight versus the full carton) stays open: the engine follows the full carton, and a per-rule
scope override applies the other reading without a release. **D-07** and **D-09** (vendor) are
unchanged.

## 5. Next

Phase 13D, the unified workspace UI, on top of these routes: master header, customer cards,
items, the fee picker with manual prices, carton entry, cost / quote / profit panels, rate
confirmation and finalisation.
