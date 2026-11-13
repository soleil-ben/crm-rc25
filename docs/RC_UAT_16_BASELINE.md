# RC-UAT-16 — the release candidate frozen for UAT round 13

**Identifier:** RC-UAT-16 · **Frozen:** 2026-10-19 · **Branch:** `fix/uat-round-12`
**Measured at:** `58f2039` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-15, measured at `b81ad85`
**Machine-readable:** `docs/RC_UAT_16_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-15 listed are unchanged.

## 1. Why RC-UAT-15 was superseded

UAT round 12 (`PROJECT_STATUS.md` §43, the owner's answers to §42.4) changed a screen, a
response field, request validation and an API default. No route, migration or dependency
changed.

| Category | Changed |
|---|---|
| Screens | The shipment page shows **Booking reference** as the first fact under "Where it is", at phone and desktop width, "Not recorded" when there is none (DEC-0163). Registration refuses a misshapen Canadian or United States postal code beside the field and in the summary before anything is sent (DEC-0165) |
| API | `AccountShipmentDetail` gains `booking_reference` (25 fields; Public Tracking stays 24). A typed Canadian (`A1A 1A1`, space optional, any case) or US (`12345`, `12345-6789`) postal code must have that shape, at registration and in the profile address proposal; blank is always allowed and other countries are unchecked (DEC-0165). `billing_same_as_shipping` defaults to `true` (DEC-0166) |
| Wording | The two postal code sentences, with "billing" for the billing block; the ZIP hint "For example 10001 or 10001-1234" |
| Confirmed, unchanged | A cancelled package's reference finds its shipment, own shipments only (DEC-0164) |
| UAT pack | Still 60 cases; CA-REG-01, CA-SHP-05, CA-SHP-06, CA-SHP-20 and CA-XP-01 updated |

There are still 139 path–method pairs, and the Alembic head and both lock digests carry
over. RC-UAT-15's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_15_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 329 files |
| Backend | **3,043 passed, 2 failed**, 784 s, at `58f2039`. The two failures are environmental, as at RC-UAT-13 to RC-UAT-15: the worktree lacks the gitignored `data/solaris_crm.db` and `data/uat/solaris_uat.uat.db` that `test_e2e_safety.py` and `test_incident_cleanup.py` inspect. To be confirmed in the main checkout |
| `eslint .` | clean |
| Frontend unit | **538 passed**, 39 files, at `fc83f16` |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`, ports 8160/5360) | **295 passed**, 0 failed, one worker, retries 0, 11.0 minutes, at `fc83f16`, second full run. Scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py` (60 Customer Account cases), `verify_owner_decisions.py`, `verify_decision_log.py` pass |

`58f2039` adds one backend test and one paragraph of DEC-0165 to `fc83f16` and nothing
else, so the frontend and Playwright results measured at `fc83f16` hold for it; the whole
backend suite was re-run at `58f2039`.

No defect was found in the application. In the tests: the first full Playwright run failed
one new test on its own locator ("Cancelled" is both a cancelled package's status pill and
its flag); it now reads the flag. And the profile address proposal was found to share the
new postal check, untested; `58f2039` adds that test.

## 3. Counts

| | RC-UAT-15 | RC-UAT-16 |
|---|---:|---:|
| Backend tests | 2,971 | **3,045** (3,043 passing here) |
| Frontend unit tests | 506 | **538** |
| Playwright tests | 289 | **295** |
| Accessibility screen states (invocations) | 64 (127) | 64 (127) |
| Backend path–method pairs | 139 | 139 |
| Public tracking contract fields | 24 | 24 |
| Customer Account list item fields | 18 | 18 |
| Customer Account detail fields | 24 | **25** |
| Customer Account list filters | 5 | 5 |
| UAT cases: staff / Customer Account | 49 / 60 | 49 / 60 |
| Decision log records | 162 | **166** |

## 4. Known risks carried

* A client that omits `billing_same_as_shipping` but sends a billing address is refused
  with the conflict sentence (§43.4 point 1).
* ZIP+4 needs the hyphen; the Canadian check excludes no letters (§43.4 point 2).
* The postal shapes also apply, server-side, to the customer's address-change proposal;
  Staff Portal address forms are unchecked (§43.4 point 3).
* The detail is the public 24 plus the booking reference, no longer at parity (§43.4
  point 4).
* Two backend tests need the main checkout's gitignored databases (§43.2).
* Unchanged from RC-UAT-15: DEC-0155's lockout and the Canada default (DEC-0157), English
  only (OD-39, DEC-0154), and the rest of RC-UAT-15 §4.

## 5. Rollback

Roll back to `b81ad85` (RC-UAT-15), or revert the merge of `fix/uat-round-12`. No
migration, no dependency step, and no data to undo: every postal code accepted under the
new check is one RC-UAT-15 also accepts, the detail field writes nothing, and the API
default changes only what an omitted flag means.
