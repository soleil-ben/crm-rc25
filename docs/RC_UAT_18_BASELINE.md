# RC-UAT-18 — the release candidate frozen for UAT of the owner answers

**Identifier:** RC-UAT-18 · **Frozen:** 2026-10-22 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `03b943d` (`03b943d3429eca005bddd4d914edf850ab508e41`), the application commit of the
owner-answer fix pack · **Supersedes:** RC-UAT-17, measured at `911965b`
**Machine-readable:** `docs/RC_UAT_18_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-17 listed are unchanged.

## 1. Why RC-UAT-17 was superseded

The owner answered the RC-UAT-17 questions on 2026-10-21 (OD-81 to OD-90, Louis Tong on Ben's
behalf), and the fix pack that implements them (`PROJECT_STATUS.md` §58, DEC-0219 to DEC-0222,
record `docs/b2c_merge/22_FIXPACK_RC18_RECORD.md`) changed what a tester sees.

| Category | Changed |
|---|---|
| Screens | Workspace: a booked master's lock badge, Admin unlock with a reason, relock (OD-88); a draft invoice screen with Save, Send (with confirmation), Download (PDF, DRAFT watermark) and Edit (audited diff), created on acceptance (OD-89, OD-90); customer-facing surcharge labels naming a vendor read "Phụ phí" / "Surcharge" (OD-84) |
| Routes | 228 → **238** backend path–method pairs, all staff (202 → 212): master unlock and relock, invoice drafts (list, read, save, PDF, send, withdraw, by shipment), the issued invoice PDF. Customer Account 21, public 2, other 3, unchanged |
| Permissions | 52 → **53**: `master:unlock` (Admin) |
| Schema | Alembic head `c5e8a1f3d7b9` → **`d4f7a2c9e1b8`** (three new tables, nothing existing altered) |
| Behaviour | Quotes for goods not yet received expire when a new tariff is activated (draft withdrawn); staff-typed customer text naming a vendor is replaced on output; draft lines naming a vendor are refused on save |
| Dependencies | None. Both lock digests carried from RC-UAT-17 (no change between `911965b` and `03b943d`) |
| UAT packs | `AIR_UAT_PACK.md` 36 → **53** (the `UAT-OWN` group, 17). `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-17's files are unchanged. Against this tree they drift on 1 of 10 checks (the Alembic
head), which is the evidence of what the fix pack changed. Its other changes (screens, routes,
permissions) are not hashed by any of the ten checks.

## 2. Evidence

From the fix pack's gates on the application tree (`22_FIXPACK_RC18_RECORD.md` §3):

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean (343 files) |
| Backend, full | **4,323 passed**, 1 skipped, 2 failed — the worktree-only pair (`test_e2e_safety.py`, `test_incident_cleanup.py`) that needs the main checkout's gitignored databases |
| eslint, vitest, vite build | clean; **747 passed**; built |
| Playwright | **318 passed**, run alone (a first run caught `accountQuotes.spec.js` not passing the new Send confirmation; fixed and rerun) |
| Alembic | On a scratch database: upgrade head → `d4f7a2c9e1b8`, check clean, downgrade -1, upgrade |
| Independent tester / reviewer | 6 end-to-end golden tests (`test_rc18_golden.py`), no product defect; no high finding, six medium and the low findings fixed |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_17_BASELINE.json` | 1 of 10 drifted: Alembic head `d4f7a2c9e1b8`, expected `c5e8a1f3d7b9` (expected) |
| `verify_uat_blank.py` | pass (49 / 60 / 53) |
| `verify_decision_log.py` | pass (222 records; the next free decision number is 0223) |
| `verify_owner_decisions.py` | pass (90 recorded, 68 answered, 22 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process (no database opened); the same walker over `911965b` reproduces RC-UAT-17's 228 |

## 3. Counts

| | RC-UAT-17 | RC-UAT-18 |
|---|---:|---:|
| Backend tests | 4,214 | **4,323** passed (+1 skipped, 2 environmental) |
| Frontend unit tests | 734 | **747** |
| Playwright tests | 316 | **318** |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 228 | **238** |
| Permissions | 52 | **53** |
| Public tracking contract fields | 24 | 24 |
| Customer Account detail / list item / quote fields | 25 / 18 / 17 | 25 / 18 / 17 |
| UAT cases: staff / Customer Account / air | 49 / 60 / 36 | 49 / 60 / **53** |
| Owner decisions recorded (open) | 80 (22) | **90** (22) |
| Decision log records | 218 | **222** |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* Two backend tests need the main checkout's gitignored databases.
* Browser Back from an unsaved invoice draft is not intercepted (F-9).
* The follow-ups F-1 to F-10, Q-P1 and Q-P2 (`19_OWNER_QUESTIONS.md` §0) carry stand-ins; none
  blocks UAT.
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-17: see `RC_UAT_17_BASELINE.md` §4.

## 5. What the lead runs after committing

Done: application and tests committed as `03b943d`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `911965b` (RC-UAT-17), or do not merge `fix/owner-answers-rc17`. The fix pack added
one migration and no dependency: rebuild the UAT database from the RC-UAT-17 checkout with
`uat_env.py --reset` rather than downgrading one that holds draft invoices or lock records.
