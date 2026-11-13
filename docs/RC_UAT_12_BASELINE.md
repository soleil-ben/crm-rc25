# RC-UAT-12 — the release candidate frozen for UAT round 9

**Identifier:** RC-UAT-12 · **Frozen:** 2026-10-17 · **Branch:** `fix/uat-round-8`
**Measured at:** `3d46044` (the application commit; the commits after it change only
documents and scripts) · **Supersedes:** RC-UAT-11, measured at `e74b388`
**Machine-readable:** `docs/RC_UAT_12_BASELINE.json`, checked by `scripts/verify_rc_baseline.py`

**Pre-release. Not production-ready.** The launch blockers RC-UAT-11 listed are unchanged.

## 1. Why RC-UAT-11 was superseded

UAT round 8 (`PROJECT_STATUS.md` §39) changed every category of the convention except
routes, migrations and dependencies:

| Category | Changed |
|---|---|
| Screens | Registration asks for the shipping address first, then billing behind "Billing address is the same as shipping address", and has a **Confirm password** field (DEC-0145, DEC-0146). The reset page shows its errors beside the fields. Audit access shows **Changes** (old → new) for an approved change request (DEC-0148). The consent history's **By** column names the customer's account (DEC-0149) |
| Schemas | Requests: `billing_same_as_shipping` on registration; `password_confirmation` on registration and reset, refused when missing or different. Responses: `changes` on audit rows; `recorded_by_account` on consent events |
| Behaviour | The server copies the shipping address to billing when ticked and requires a billing street when unticked with a shipping address (DEC-0145). Applied values are not drift (DEC-0147). The approval's `customer.update` row carries old and new values, address-only approvals included (DEC-0148). Customer events carry the actor `customer_account:CA-…` (DEC-0149) |
| Wording | The new form text, the server's confirmation and billing sentences, and EN/VI staff strings |

No route, migration or dependency changed: 139 path–method pairs, the Alembic head and both
lock digests carry over. RC-UAT-11's files are unchanged and still verify 10 of 10 with
`--baseline docs/RC_UAT_11_BASELINE.json`.

## 2. Evidence

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean, 321 files |
| Backend | **2,874 passed**, 0 failed, 794 s |
| `eslint .` | clean |
| Frontend unit | **471 passed**, 35 files |
| `vite build` | succeeds |
| Alembic, disposable database | 8 up, check clean, 8 down, 8 up, check clean; head `6af30fcdd3a8` |
| Playwright (`npm run e2e`) | **278 passed**, 0 failed, one worker, retries 0, 10.6 minutes. Second full run: the first failed one new test on its own assertion, fixed before the application commit; scratch removed |
| Verifiers | `verify_rc_baseline.py` 10 of 10; `verify_uat_blank.py`, `verify_owner_decisions.py`, `verify_decision_log.py` pass |

## 3. Counts

| | RC-UAT-11 | RC-UAT-12 |
|---|---:|---:|
| Backend tests | 2,857 | **2,874** |
| Frontend unit tests | 455 | **471** |
| Playwright tests | 272 | **278** |
| Accessibility screen states (invocations) | 64 (127) | 64 (127) |
| Backend path–method pairs | 139 | 139 |
| Frontend routes: staff / Customer Account | 17 / 15 | 17 / 15 |
| Public tracking contract fields | 24 | 24 |
| UAT cases: staff / Customer Account | 49 / 59 | 49 / 59 |
| Decision log records | 144 | **149** |

## 4. Known risks carried

* The Customer Account is English only (OD-39); the new registration and reset wording has
  no Vietnamese. Owner question, §39.4 q1.
* Unticking the billing box with a shipping address makes a billing street required
  (DEC-0145). Owner question, §39.4 q2.
* Audit access shows values for one row type, the approved change request (DEC-0148).
* Security and unauthenticated events still read `system` (DEC-0149). Owner question,
  §39.4 q3.
* Unchanged: a linked customer's email changes only after deactivation (DEC-0142); no
  shipment email exists (DEC-0143); evidence references may contain a typed name
  (DEC-0141); the profile screen is audited at desktop width only; the react-router
  advisories; the unexplained intermittent failure class.

## 5. Rollback

To `e74b388` (RC-UAT-11), or revert the merge of `fix/uat-round-8`. No migration and no
dependency step. Billing addresses copied under RC-UAT-12 are ordinary data under RC-UAT-11;
audit rows written with `changes` and a customer actor stay as written.
