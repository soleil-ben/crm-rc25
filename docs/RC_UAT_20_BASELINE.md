# RC-UAT-20 — the release candidate frozen for UAT of Ben's answers of 2026-10-23

**Identifier:** RC-UAT-20 · **Frozen:** 2026-10-24 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `98ca88b` (`98ca88b107da8936013ab9bc514344f0036a0ec7`), the application commit of
the RC-UAT-20 fix pack · **Supersedes:** RC-UAT-19, measured at `418cf3f`
**Machine-readable:** `docs/RC_UAT_20_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-19 listed are unchanged.

## 1. Why RC-UAT-19 was superseded

Ben answered the RC-UAT-19 follow-ups on 2026-10-23 (OD-102 to OD-108), and the fix pack that
implements them and the RC-UAT-19 UAT findings (`PROJECT_STATUS.md` §60, DEC-0227 to DEC-0229,
record `docs/b2c_merge/24_FIXPACK_RC20_RECORD.md`) changed what a tester sees.

| Category | Changed |
|---|---|
| Screens | Draft invoice GST/HST by route: international auto-fills 0 % (zero-rated), domestic tax included at the destination province's rate (OD-102); new **Settings → GST/HST rates** (Admin edits, audited); Download refused until the GST/HST tick is saved; costume jewellery takes the vendor's VND cost and the customer CAD price (OD-103); payment dates shown as plain dates; vendor provider on the final delivery leg and generic leg labels on staff screens; tariff warnings panel (Settings → Tariffs → Tariff versions → View, 39 for the seeded tariff) |
| Routes | 239 → **242** backend path–method pairs, all staff (213 → 216): `GET /finance/tax-rates`, `PATCH /finance/tax-rates/{province_code}`, `GET /tariffs/versions/{version_id}/warnings`. Customer Account 21, public 2, other 3, unchanged |
| Public contract | `PublicTrackingResult` 25, `AccountShipmentDetail` 26, list item 18, quote 17 — unchanged |
| Permissions | 53, unchanged |
| Schema | Alembic head `e6b1c4a8d2f3` → **`f7c2d9e3a1b5`** (new tables `tax_rates` (seeded), `invoice_draft_tax_route`, `fee_line_manual_prices`; nothing existing altered) |
| UAT seed | A1's `UAT-AIR-A1-1` invoiced at 0 %; for UAT only, three domestic shipments for A2 on master `UAT-DOM-AWB` with drafts at 14 % (NS), 15 % (NB) and one awaiting a rate |
| Dependencies | None. Both lock digests carried from RC-UAT-19 (no change between `418cf3f` and `98ca88b`) |
| UAT packs | `AIR_UAT_PACK.md` 63 → **71** (`UAT-OWN-28` to `-35`; `-18` to `-27` updated). `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-19's files are unchanged. Against this tree they drift on 1 of 10 checks (the Alembic
head), which is the evidence of what the fix pack changed. Its other changes (screens, routes,
the seed) are not hashed by any of the ten checks.

## 2. Evidence

From the fix pack's gates on the application tree (`24_FIXPACK_RC20_RECORD.md` §2):

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean (356 files) |
| Backend, full | **4,622 passed**, 1 skipped, 1 failed — the worktree-only `test_e2e_safety.py` |
| eslint, vitest, vite build | clean; **795 passed**; built |
| Playwright | **319 passed**, run alone |
| Alembic | On a scratch database: upgrade head → `f7c2d9e3a1b5`, check clean, downgrade -1, upgrade |
| Independent tester / reviewer | 11 golden tests (`test_rc20_golden.py`), no product defect; no high finding, the findings fixed; the domestic quote-wording contradiction logged as P-9 |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_19_BASELINE.json` | 1 of 10 drifted: Alembic head `f7c2d9e3a1b5`, expected `e6b1c4a8d2f3` (expected) |
| `verify_uat_blank.py` | pass (49 / 60 / 71) |
| `verify_decision_log.py` | pass (229 records; the next free decision number is 0230) |
| `verify_owner_decisions.py` | pass (108 recorded, 86 answered, 22 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process (no database opened); the same walker over `418cf3f` reproduces RC-UAT-19's 239 |

## 3. Counts

| | RC-UAT-19 | RC-UAT-20 |
|---|---:|---:|
| Backend tests | 4,397 | **4,622** passed (+1 skipped; 1 environmental) |
| Frontend unit tests | 757 | **795** |
| Playwright tests | 319 | 319 |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 239 | **242** |
| Permissions | 53 | 53 |
| Public tracking contract fields | 25 | 25 |
| Customer Account detail / list item / quote fields | 26 / 18 / 17 | 26 / 18 / 17 |
| UAT cases: staff / Customer Account / air | 49 / 60 / 63 | 49 / 60 / **71** |
| Owner decisions recorded (open) | 101 (22) | **108** (22) |
| Decision log records | 226 | **229** |
| Supported Python (UAT) | 3.11 to 3.14 | 3.11 to 3.14 |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* `test_e2e_safety.py` needs the main checkout's gitignored databases.
* Domestic quote wording vs the backed-out tax is open (P-9); domestic shipments cannot be
  quoted on screen (P-10); stand-ins R-1 to R-14 in `19_OWNER_QUESTIONS.md` §000.
* Admin manual delete of retained quotes is not built (OD-107); Python 3.15 waits for the
  pinned packages (P-8).
* Browser Back from an unsaved invoice draft is not intercepted (F-9).
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-19: see `RC_UAT_19_BASELINE.md` §4.

## 5. What the lead runs after committing

Done: application and tests committed as `98ca88b`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `418cf3f` (RC-UAT-19), or do not merge `fix/owner-answers-rc17` past `f90927a`. The
fix pack added one migration and no dependency: rebuild the UAT database from the RC-UAT-19
checkout with `uat_env.py --reset` rather than downgrading one that holds route-tax or
manual-price records.
