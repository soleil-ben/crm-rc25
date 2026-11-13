# 11 — Phase 13D completion record: the unified workspace

**Date:** 2026-10-20 · **Branch:** `phase-13-b2c-merge` · **Base:** 05c9aa1 (Phase 13C) ·
**Migration:** none (head stays `c9e5a3b7d2f8`) · **Decisions:** DEC-0197 to DEC-0200 ·
**Scope:** air only (OD-49)

The staff screens for the 13C pricing routes. Nothing is deployed, nothing was pushed or
merged, no notification is sent, and no request goes to the bank or the vendor. Test data only.

## 1. What was built

| Area | Files | What it does |
|---|---|---|
| Masters list | `frontend/src/features/workspace/WorkspaceListPage.jsx` | Every master with state, customers and chargeable weight; a form for a new air master (Air Standard / Air Express, HCM / HAN only) |
| One master | `WorkspacePage.jsx`, `MasterPanels.jsx` | Header and weights (edit, book with vendor), add a customer's shipment by search, cartons editor for the piece fee, the vendor-cost panel (base freight, piece fee, surcharges, total VND, Vietcombank rates with a demo label, cost by customer, blocking and provisional notes) |
| Customer cards | `CustomerCard.jsx`, `FeePicker.jsx` | Items; per item, the searchable fee list (accent-insensitive, the master's own air section only), with quantity, weight or the vendor's price only where the engine reads them; the fees on each item with their vendor cost; the customer's cost share |
| Quote | `QuotePanel.jsx` | Price or re-price; figures and lines (revenue, cost VND and CAD, internal cost-share lines marked); confirm the selling rate (an override needs a reason); finalise, with the server's refusals listed and the below-cost reason field; an out-of-date note when costs moved since pricing |
| Navigation | `AppShell.jsx`, `routes.jsx`, `SessionContext.jsx` | "Workspace" for roles holding `tariff:read` (Operations, Admin) |
| Translations | `i18n/en.js`, `i18n/vi.js` | `workspace.*` in English and Vietnamese, at parity |
| Small API additions | `routes/tariffs.py`, `schemas/tariff*.py`, `pricing_service.py` | Rules carry `above_top_tier`; FX snapshots carry `source_url` and `is_demo`; the estimate carries `piece_fee_vnd` |
| Demo data | `backend/app/seed_pricing.py`, `scripts/workspace_demo_env.py`, `scripts/e2e_env.py` | Sanitized tariff + labelled demo exchange rate (+ an open master with three customers for the demo database); refused outside `.e2e.db` / `.demo.db` databases |

Still configurable and awaiting the owner, as instructed: the pharmaceutical weight basis
(policy scope override), markups (surcharge policies), the $18/kg default and the 2/3 share
(OD-48). The screen shows them as the settings say, in a banner and in the engine's notes.

## 2. Trying it locally

```
backend/.venv/Scripts/python scripts/workspace_demo_env.py --create
```

Then, in PowerShell from the repository root:

```
$env:DATABASE_URL = "sqlite:///C:/solaris-wt/b2c-merge/data/workspace_demo/solaris_workspace.demo.db"; $env:ENVIRONMENT = "development"; backend\.venv\Scripts\python -m uvicorn app.main:app --port 8000 --app-dir backend
npm run dev --prefix frontend
```

Open http://localhost:5173/workspace and sign in as `ops@demo.example.com` /
`SolarisDemo!2026` (Operations; `admin@demo.example.com` works too). Master `MST-000001` is
ready with three customers. The demo rate counts as current for a day; `--refresh-fx` adds a new
one, `--reset` rebuilds everything, `--destroy` removes it. Only that one file under the
git-ignored `data/workspace_demo/` is ever written.

## 3. Evidence

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check` (backend and scripts) | pass |
| Backend | **3,637 passed, 2 failed** (1,088 s); the two are the known environmental pair (`test_e2e_safety.py`, `test_incident_cleanup.py`: this worktree lacks the git-ignored development databases). New: `test_seed_pricing.py` (8) |
| `eslint .` | pass |
| Frontend unit | **567 passed**, 40 files; new `tests/workspace.test.jsx` (28) written by an independent test agent |
| `vite build` | pass |
| Playwright, `npm run e2e` | **300 passed**, 11.2 minutes; new `staffWorkspace.spec.js` (create master → add customer → item → fee "dong ho" → price → confirm → refused finalise → finalise) and two accessibility audits at 1280 and 375 px |
| Alembic, disposable database | pass: up, check, 1 down, 1 up; head `c9e5a3b7d2f8` (no new migration) |
| Verifiers | `verify_decision_log.py` and `verify_owner_decisions.py` pass |
| Live walk-through on the demo database | the full flow above, then quote v1 finalised at CAD 18.00/kg, revenue CAD 290.68 |
| Independent review | 13 findings (1 high, 7 medium, 5 low); all fixed except two gaps recorded as not done (DEC-0200) |

## 4. Not done

Removing a customer from a master and paging past 100 masters (DEC-0200). Customer-facing quote
documents and invoices are Phase 13E.
