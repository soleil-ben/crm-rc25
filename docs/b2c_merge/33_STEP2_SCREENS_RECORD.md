# Step 2 — screens for the confirmed method — record

**Asked:** owner GO for step 2 on v0.7 (commit 4ead11b), 2026-11-04. Decisions DEC-0267 to
DEC-0270. Rules kept: every RC25 function stays; pricing numbers do not change (S1–S7 still
match `case_study_results_v0.7.json` to the cent).

## Screens (EN + VI; all figures are the server's)

| Item | Where | What |
|---|---|---|
| (a) origin + service | Workspace → New master; master edit form | Service Air Standard / Air Express / UPS / Sea, origin HCM / HAN, with a note on which base rate each selects |
| (b) cost vs quote | Workspace → master → "Cost vs quote" | Master, each package (kiện, with the customers inside) and each customer: VND cost, CAD cost, CAD quote, profit, surcharge margin; negative profit in red; "not reconciled" warning; engine warnings; "How each figure was worked out" |
| (c) manual Express / UPS | Workspace → master (Air Express / UPS only) | Vendor cost per kg *or* total, selling CAD/kg, reason; Kango Express zone price shown for reference only |
| (d) method settings | Settings → Pricing method | Every method setting with a hint; editable with `settings:manage`, read-only otherwise; only changed fields are sent. Settings → Pricing labels the old 2 % default markup "RC25 method only" |
| (e) packed as one box | Workspace → master → "Packages" | Checkbox on one-package masters only (disabled with the reason otherwise); short customer note per package; customer → package on multi-package masters |
| (f) dated sea cost | Settings → Pricing method → "Sea vendor cost" | Rate in force, history, add a rate with its effective date |
| (g) Kango rate sheets | Settings → Kango rate sheets | Upload → draft → diff (FX, warehouse zone, piece fees, zones, surcharges, air rates by origin / product / zone / kind, excluded non-Canada rows) → confirm or discard; history with rollback of a superseded version; approvers list |

## Approver permission (DEC-0268)

`tariff:approve` is a per-account grant (table `staff_permission_grants`). It takes effect
with the Admin role. The migration seeds it **for Ben only**; no address for Louis is seeded
or hard-coded. (It can only seed an account that exists when the migration runs; if Ben's
account is created later, an Admin gives him the grant on the screen below. The UAT reset
seeds the demo Admin, as RC25's demo approver list did.) To add Louis once his CRM account
exists, either:

- Settings → Kango rate sheets → "Give the permission to" → choose his account → Give
  permission (Admin with `staff:manage`); or
- one line in PowerShell from the UAT folder (see README_LOUIS.md §6):
  `powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\uat\env.ps1; .venv\Scripts\python ..\scripts\grant_tariff_approver.py <his CRM login email>"`
  (`--revoke` takes it away).

## Other changes

- DEC-0267: version-neutral names (`cost_method.py`, `pricing_method.py`,
  `uses_confirmed_method`, stored value `confirmed`, estimate key `method_detail`); migration
  `f8b0d2e4a6c8`; old snapshots still readable.
- DEC-0269: the phase-15 leak scan no longer trips on random ids containing "fx".
- Workspace: a wide table no longer pushes its card under the vendor-cost column.

## Tests

Backend: `test_staff_permission_grants.py` (grant / revoke routes, two approvers, ops is not
an approver, legacy list sync, migration seeds Ben only); method tests updated to the
neutral names. Frontend: `tests/step2Screens.test.jsx` (17 tests over every panel) and the
four-service test in `workspace.test.jsx`.

## Open

- The staff portal has no language switch (RC25 as received): the VI strings exist and pass
  the parity test, but staff see English until a switch is added.
- Louis's approver grant waits for his confirmed CRM account.
