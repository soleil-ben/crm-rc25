# RC-UAT-19 — the release candidate frozen for UAT of the owner answers of 2026-10-22

**Identifier:** RC-UAT-19 · **Frozen:** 2026-10-22 · **Branch:** `fix/owner-answers-rc17`
**Measured at:** `418cf3f` (`418cf3ff50a5fc6fbb2175e967da64c195018442`), the application commit of
the RC-UAT-19 owner-answer fix pack · **Supersedes:** RC-UAT-18, measured at `03b943d`
**Machine-readable:** `docs/RC_UAT_19_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-18 listed are unchanged.

## 1. Why RC-UAT-18 was superseded

The owner answered the RC-UAT-18 follow-ups on 2026-10-22 (OD-91 to OD-101, Louis Tong on Ben's
behalf), and the fix pack that implements them (`PROJECT_STATUS.md` §59, DEC-0223 to DEC-0226,
record `docs/b2c_merge/23_FIXPACK_RC19_RECORD.md`) changed what a tester sees.

| Category | Changed |
|---|---|
| Screens | Draft invoice: opens at GST/HST 13 % included, a confirmation (totals and mode echoed) required for Save and Send, rate and mode editable (OD-94); customer pages: carrier links under the generic names "Master Tracking" / "Last Mile Tracking", stored labels never shown (OD-91, OD-92); costume jewellery (HCM row 27) priced by a staff-entered amount, finalising blocked until entered (OD-93) |
| Routes | 238 → **239** backend path–method pairs, all staff (212 → 213): `PATCH /shipments/{shipment_id}/fee-lines/{line_id}`. Customer Account 21, public 2, other 3, unchanged |
| Public contract | `PublicTrackingResult` 24 → **25** fields (`carrier_links`); `AccountShipmentDetail` 25 → 26 (`carrier_links`); carrier link models gain `tracking_name_key` |
| Permissions | 53, unchanged |
| Schema | Alembic head `d4f7a2c9e1b8` → **`e6b1c4a8d2f3`** (one new table `invoice_draft_tax`, nothing existing altered) |
| UAT launcher | `START_UAT.bat` finds 64-bit Python **3.11 to 3.14** (prefers 3.12; 3.14 tested; 3.15 not yet) and lists every Python seen on failure (DEC-0226) |
| Dependencies | None. Both lock digests carried from RC-UAT-18 (no change between `03b943d` and `418cf3f`) |
| UAT packs | `AIR_UAT_PACK.md` 53 → **63** (`UAT-OWN-18` to `-27`). `UAT_CASES.md` 49 and the Customer Account pack 60, unchanged |

RC-UAT-18's files are unchanged. Against this tree they drift on 2 of 10 checks (the public
tracking contract field count and the Alembic head), which is the evidence of what the fix pack
changed. Its other changes (screens, the route, the launcher) are not hashed by any of the ten checks.

## 2. Evidence

From the fix pack's gates on the application tree (`23_FIXPACK_RC19_RECORD.md` §3):

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean (346 files) |
| Backend, full | **4,397 passed**, 1 skipped, 3 failed — the worktree-only `test_e2e_safety.py`, and two tests still pinning the public field count at 24 (`test_phase5b_seam_and_contracts`, `test_uat_round_12`), updated to 25 with `carrier_links` named (AS-36, AS-37) and rerun green (189 passed with the register guard) |
| eslint, vitest, vite build | clean; **757 passed**; built |
| Playwright | **319 passed**, run alone (a first run caught `accountQuotes.spec.js` sending without the GST/HST confirmation; fixed and rerun) |
| Alembic | On a scratch database: upgrade head → `e6b1c4a8d2f3`, check clean, downgrade -1, upgrade |
| Python 3.14.9 | venv from the pinned lock; 434-test backend subset passed |
| Independent tester / reviewer | 6 golden tests (`test_rc19_golden.py`), one product defect (row-27 amounts rounding to zero or overflowing) fixed; no high finding, the medium and low findings fixed |

Measured at the freeze:

| Check | Result |
|---|---|
| `verify_rc_baseline.py` | **10 of 10** |
| `verify_rc_baseline.py --baseline docs/RC_UAT_18_BASELINE.json` | 2 of 10 drifted: public tracking contract fields 25, expected 24; Alembic head `e6b1c4a8d2f3`, expected `d4f7a2c9e1b8` (expected) |
| `verify_uat_blank.py` | pass (49 / 60 / 63) |
| `verify_decision_log.py` | pass (226 records; the next free decision number is 0227) |
| `verify_owner_decisions.py` | pass (101 recorded, 79 answered, 22 open) |
| Route, permission and field counts | Walked with the `test_account_boundary.py` route walker in a scratch process (no database opened); the same walker over `03b943d` reproduces RC-UAT-18's 238 |

## 3. Counts

| | RC-UAT-18 | RC-UAT-19 |
|---|---:|---:|
| Backend tests | 4,323 | **4,397** passed (+1 skipped; 1 environmental, 2 count pins fixed and rerun) |
| Frontend unit tests | 747 | **757** |
| Playwright tests | 318 | **319** |
| Accessibility screen states (invocations) | not re-counted | not re-counted |
| Backend path–method pairs | 238 | **239** |
| Permissions | 53 | 53 |
| Public tracking contract fields | 24 | **25** |
| Customer Account detail / list item / quote fields | 25 / 18 / 17 | **26** / 18 / 17 |
| UAT cases: staff / Customer Account / air | 49 / 60 / 53 | 49 / 60 / **63** |
| Owner decisions recorded (open) | 90 (22) | **101** (22) |
| Decision log records | 222 | **226** |
| Supported Python (UAT) | 3.11 to 3.13 | **3.11 to 3.14** |

## 4. Known risks carried

* Accessibility counts are not re-measured.
* `test_e2e_safety.py` needs the main checkout's gitignored databases.
* GST/HST rate and mode on drafts are stand-ins pending Louis (P-1, P-2); the manual Issue
  invoice path (no draft) still adds tax on top (P-6).
* A carrier link whose host names the vendor stays hidden (P-5); the Vietnamese tracking names
  await review (P-4).
* Admin manual delete of retained quotes is not built (P-7); Python 3.15 waits for the pinned
  packages (P-8).
* Browser Back from an unsaved invoice draft is not intercepted (F-9).
* No vendor mailbox and no production email provider; the FX worker is not run in UAT.
* `openpyxl` and `et_xmlfile` are not audited by a tool.
* Unchanged from RC-UAT-18: see `RC_UAT_18_BASELINE.md` §4.

## 5. What the lead runs after committing

Done: application and tests committed as `418cf3f`; the SHA is in the JSON and this header.
Commit these documents and scripts on top (the freeze), then:

`backend/.venv/Scripts/python scripts/verify_rc_baseline.py` — 10 of 10.

## 6. Rollback

Roll back to `03b943d` (RC-UAT-18), or do not merge `fix/owner-answers-rc17` past `8b954e4`. The
fix pack added one migration and no dependency: rebuild the UAT database from the RC-UAT-18
checkout with `uat_env.py --reset` rather than downgrading one that holds draft-invoice tax records.
