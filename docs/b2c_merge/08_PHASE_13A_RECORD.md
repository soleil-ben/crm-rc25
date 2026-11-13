# 08 — Phase 13A completion record: tariff and FX foundation

**Date:** 2026-10-19 · **Branch:** `phase-13-b2c-merge` · **Base:** RC-UAT-16 (`d2802e1`) ·
**Migration:** `f53efaa7773e` (head), from `6af30fcdd3a8` · **Decisions:** DEC-0167 to DEC-0173

Backend only. No screen changed, no public or Customer Account route changed, no frontend
file changed. Nothing is deployed. No request was made to the vendor or the bank by this
build or its tests.

## 1. What was built

| Area | Files | What it does |
|---|---|---|
| Workbook reader | `backend/app/pricing/kango_workbook.py` | Reads the vendor's `.xlsx` into typed rows with the sheet and cell each came from. Anchored on header text (the Hà Nội sheet sits one row higher than HCM). Never opens the staff-directory sheet. Flags anomalies instead of fixing them |
| Reviewed semantics | `backend/app/pricing/kango_semantics.py` | A strict price-text parser that refuses ranges, estimates, compounds and unknown units; a curated table (24 rows) for meanings that live in the vendor's notes, each citing its cell; the accessorial fees and per-product rules written in prose |
| Models | `backend/app/models/tariff.py`, `backend/app/models/fx.py` | Twelve tables: vendors, versions, products, rate brackets, FSA zones, beyond postal codes and rates, accessorials, surcharge rules and tiers; FX snapshots and attempts |
| Importer | `backend/app/services/tariff_import_service.py` | Draft version per file, SHA-256 uniqueness, provenance per row, pricing status per rule, `no_rate` for beyond code 180, import report, audited activation that supersedes and never deletes |
| Exchange rates | `backend/app/services/fx_service.py`, `backend/app/workers/fx_worker.py` | Vietcombank CAD cash buying, transfer and selling; guarded fetch (HTTPS, exact host, no redirects, bounded); plausibility refusals; append-only snapshots; every attempt recorded; `--once` and continuous worker |
| Routes | `backend/app/api/v1/routes/tariffs.py`, `backend/app/schemas/tariff.py` | 11 staff routes: versions (list, detail with report, import, activate), products, surcharges (fee-picker catalogue with Canada-only and section filters and a name search), accessorials, beyond rates, FX latest and history |
| Permissions | `backend/app/core/permissions.py` | `tariff:read` (Operations, Admin), `tariff:manage` (Admin) |
| Migration | `backend/alembic/versions/f53efaa7773e_…` | Additive; up, `alembic check`, down, up verified on a scratch database and in tests |
| Fixture and tooling | `backend/tests/fixtures/kango_canada_rates_2026-10-12_sanitized.xlsx`, `kango_reference_v15.json`, `scripts/sanitize_kango_workbook.py` | The vendor's workbook with the staff sheet removed and the contact header blanked; the prototype's JSON as an independent oracle |
| Dependency | `backend/pyproject.toml`, `backend/requirements.lock.txt` | `openpyxl` 3.1.5, `et_xmlfile` 2.0.0 |

## 2. What the import of the 12 October 2026 workbook yields

| Table | Rows |
|---|---:|
| products | 10 |
| rate brackets | 616 |
| FSA zones | 1,674 |
| beyond postal codes | 16,200 |
| beyond rates | 9 (8 priced + code 180 as `no_rate`) |
| accessorials | 16 |
| surcharge rules | 85 |

Surcharge rules by status: 70 priced, 2 tiered (nail polish, perfume), 8 unpriced for vendor
review, 2 conflict (pharmaceuticals on both air tariffs: refused on the rate sheets, priced
on the surcharge sheet; V-12), 2 not applicable to Canada (plants), 1 free (Hà Nội false
eyelashes). A row the engine may not price never carries a unit price. 24 rows take their meaning from the curated table, 61 from the
parser. Import time about 1.5 s.

Anomalies reported: 35 FSAs with Express zone below Ground zone; 3 price cells where 16.0 kg
is cheaper than 15.5 kg (Express zone 2, HCM and HN; HN zone 3); 1 duplicate FSA (K1A, ON
kept); 1 beyond code without a rate (180, 123 postal codes); trucking pallet fees not
imported (2 sheets). Every one is a vendor question in `05_OPEN_DECISIONS.md`.

## 3. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean |
| `verify_decision_log.py`, `verify_owner_decisions.py` | pass |
| New tests | `test_tariff_workbook.py` (equality with the prototype's snapshot: 612 rate cells, zones, postal codes, beyond rates, 85 surcharge texts; anomalies; staff-sheet skip; strict parser table incl. issue register H-01, H-02, H-03), `test_fx_service.py` (parsing, plausibility refusals, transport guard, snapshots, freshness, worker exit codes), `test_tariff_import.py` (import, golden rows H-01 to H-09, duplicate refusal, activation, HTTP routes per role, upload bounds, FX routes, privacy of public and account schemas and routers), `test_migrations_phase13a.py` (empty, populated Phase 10, down and up, foreign keys) |
| Adjusted tests | `test_migrations_phase10.py`: four tests now target the Phase 10 revision explicitly, because head moved |
| Full backend suite | **3,189 passed, 2 failed**, 919 s; the two failures are the environmental pair every worktree run shows (gitignored development databases absent) |
| Independent review | one subagent review of the uncommitted change set; 12 findings, all applied: pharmaceuticals consistent across origins, refusal of unreadable rows between bands and of gaps in the zone and postal lists, `ondelete` on all 12 foreign keys, port check on the bank fetch, duplicate-row-number refusal, wording of the disk and staff-sheet claims, privacy scan widened to every schema module, unused schemas removed, inline imports lifted |
| Frontend | unchanged; not re-run |
| Alembic | 9 up, check clean, 1 down, 1 up on a scratch database |

## 4. Issue register rows closed by this phase

H-01, H-02, H-03 (parser), H-06 (one divisor per product, stored), H-07 (beyond 180),
H-08 (meat/egg/dairy at 20,000 for Canada, flagged V-14), H-09 (plants excluded, Hà Nội
eyelashes free), M-05 (both FX rates, worker process), M-06 (plausibility bounds), M-08 and
L-05 (anomalies reported), L-06 (staff sheet never read). H-04 (surcharge below cost at the
selling rate) and H-05, M-01 to M-04, M-07 belong to 13B–13D.

## 5. Not done, and why

* No pricing. The engine (13C) consumes these tables; nothing prices a shipment yet.
* No worker scheduled. Whether and where `fx_worker` runs is an operations decision.
* No owner-decision records added. D-01 to D-13 and V-01 to V-19 stay in
  `05_OPEN_DECISIONS.md` until the owner or vendor answers; the register's verifier requires
  complete records, and a question is not yet a record.
* No RC freeze. A release candidate is cut when a UAT round needs one; this phase changed
  no screen a tester sees.
* The vendor's original workbook stays in the handoff folder; only the sanitized copy is
  committed.

## 6. Next

13B — consolidation (master) entity with child memberships, payer party, commodity line
items, and master-to-child tracking inheritance. Schema and migration only; the pricing
engine follows in 13C.
