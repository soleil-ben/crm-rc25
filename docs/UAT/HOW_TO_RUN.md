# How to run UAT — one page

Synthetic data only, on your own machine. Nothing is sent to anybody and nothing calls the
bank or the vendor. The candidate under test is **RC-UAT-25** (RC-UAT-24 plus the fix pack
for Ben's live UAT of 2026-10-25, OD-113: red asterisks on required fields, the declared value
currency a list of CAD and VND, saved addresses for the recipient, the sign-in email changed by
an Admin only, "Received at warehouse", correcting a recorded or published timeline event, the
blank Financials tab fixed and a Quote and invoice card on the shipment; migration
`a5c7e9b1d3f6`, two new tables; new cases `UAT-BLD-26` to `-33` in `AIR_UAT_PACK.md`,
`UAT-BLD-09` rewritten, `-10` withdrawn; record `docs/b2c_merge/29_BUILD_RC25_RECORD.md`;
baseline `docs/RC_UAT_25_BASELINE.md`, measured at `bccbddf`). Before it: **RC-UAT-24**
(RC-UAT-23 plus Ben's evening
answers of 2026-10-24, OD-112: the legal entity reads Solaris Express Inc. on Settings, the
staff login footer and the demo label sender, and the draft invoice editor says "Tax included
in the price" with the invoice's summary labels; data-only migration `e7a9c1d3f5b6`; new case
`UAT-BLD-25` in `AIR_UAT_PACK.md`; record `docs/b2c_merge/28_BUILD_RC24_RECORD.md`; baseline
`docs/RC_UAT_24_BASELINE.md` (superseded), measured at `f4a04a3`). Before that: **RC-UAT-23** (RC-UAT-22 plus invoices that
follow the Solaris Invoicing desk, OD-111: GST/HST backed out per line at the destination
province's rate, international zero-rated, net lines with a Tax column and summary rows, and
English-only invoice PDFs with the Solaris Express Inc. company block; no migration; new cases
`UAT-BLD-20` to `-24` in `AIR_UAT_PACK.md`; record `docs/b2c_merge/27_BUILD_RC23_RECORD.md`;
baseline `docs/RC_UAT_23_BASELINE.md` (superseded), measured at `3151095`). Before that: **RC-UAT-22**
(RC-UAT-21 plus Admin re-link or close of an account left without a customer after
reinstatement, B-13, on **Customer accounts → Accounts needing a customer**; cases
`UAT-BLD-18` and `-19`; record `docs/b2c_merge/26_BUILD_RC22_RECORD.md`; baseline
`docs/RC_UAT_22_BASELINE.md` (superseded), measured at `61f5c22`). Before that: **RC-UAT-21** (RC-UAT-20 plus
the build Ben asked for on 2026-10-24, OD-110: shipment import and legacy history, password and
sign-in email change (since RC-UAT-25, the Admin's change of a customer's sign-in email (customers cannot change it, RC-UAT-25)), Admin reinstatement, the quote GST/HST line (OD-109 stand-in), Admin quote
soft delete, and retention settings that stay **off**; cases `UAT-BLD-01` to `-17`; record
`docs/b2c_merge/25_BUILD_RC21_RECORD.md`; baseline `docs/RC_UAT_21_BASELINE.md` (superseded),
measured at `be7d2df`). Before that: **RC-UAT-20** (RC-UAT-19 plus Ben's
answers of 2026-10-23, OD-102 to OD-108; cases `UAT-OWN-28` to `-35`; record
`docs/b2c_merge/24_FIXPACK_RC20_RECORD.md`; baseline `docs/RC_UAT_20_BASELINE.md` (superseded), measured at
`98ca88b`). Before that: **RC-UAT-19** (RC-UAT-18 plus the
owner answers of 2026-10-22, OD-91 to OD-101; cases `UAT-OWN-18` to `-27`; baseline
`docs/RC_UAT_19_BASELINE.md` (superseded), measured at `418cf3f`). Before it: **RC-UAT-18** (RC-UAT-17 plus the owner answers of 2026-10-21; cases
`UAT-OWN-01` to `-17`; baseline `docs/RC_UAT_18_BASELINE.md`, measured at `03b943d`). `ENVIRONMENT.md` is the full reference (safety checks, ports, what the
environment cannot show); this page is the short path. Commands are for **PowerShell**,
from the repository root. Git Bash equivalents are in `ENVIRONMENT.md` §3 and §3a.

## 1. Build (once per machine)

**Python.** 64-bit CPython **3.11 to 3.14**: **3.12.10 recommended**, 3.14 tested. **Python
3.15 is not supported yet** (five pinned packages have no 3.15 build; open question P-8): a
3.15 install is refused with a clear message. On the portable UAT package, this lists every
Python on the PC and the one the start script would use, with the reason any other was
skipped:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File uat\uat.ps1 python
```

To force one install, set `UAT_PYTHON` to its full `python.exe` path in the same window first,
for example `$env:UAT_PYTHON = "C:\Program Files\Python312\python.exe"` (an unusable one is
reported and another is looked for). In a repository checkout, create the virtual environment
below with a supported Python (`py -3.12 -m venv .venv` if `python` is another version).

```powershell
cd backend; python -m venv .venv; .venv\Scripts\pip install -e ".[dev]"; cd ..
npm install --prefix frontend
```

No `.env` file is needed for UAT: every setting UAT needs is given on the command line
below.

## 2. Reset the UAT database (before every session)

Stop the backend first if it is running (`Ctrl+C`), then:

```powershell
backend\.venv\Scripts\python scripts\uat_env.py --reset
```

It builds `data/uat/solaris_uat.uat.db` (and nothing else; it refuses any other path),
fills it with the synthetic data of all three packs, clears the captured mail and the
rate-email folder, and ends with a coverage report. **It must end with "Every required
category is present."** Takes about ten seconds. If it stops part-way with an error, run
it again: a half-built database is only ever fixed by another `--reset`.

On a later day than the reset, add a fresh demo exchange rate (one counts as live for a
day):

```powershell
backend\.venv\Scripts\python scripts\uat_env.py --refresh-fx
```

## 3. Start the backend (window 1)

```powershell
$uat = (Resolve-Path data\uat).Path -replace '\\','/'
$env:DATABASE_URL = "sqlite:///$uat/solaris_uat.uat.db"
$env:ENVIRONMENT = "development"
$env:ACCOUNT_EMAIL_TRANSPORT = "capture"
$env:ACCOUNT_EMAIL_CAPTURE_DIR = "$uat/account_mail"
$env:TARIFF_INTAKE_DIR = "$uat/tariff_intake"
$env:CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
$env:TRACKING_BASE_URL = "http://localhost:5173/track"
backend\.venv\Scripts\python -m uvicorn app.main:app --port 8000 --app-dir backend --no-proxy-headers
```

## 4. Start the screens (window 2)

```powershell
npm run dev --prefix frontend
```

Open <http://localhost:5173> for the Staff Portal and <http://localhost:5173/account> for the
Customer Account. Ports busy? `ENVIRONMENT.md` §3, "If the default ports are busy": a
different frontend address also needs `CORS_ORIGINS` and `TRACKING_BASE_URL` changed in §3
(the Customer Account sign-in and the links in captured emails depend on them).

## Sign in

| Who | Address | Password |
|---|---|---|
| Admin (also the tariff approver) | `admin@demo.example.com` | as in `ENVIRONMENT.md` §2 |
| Operations | `ops@demo.example.com` | as above |
| Marketing | `marketing@demo.example.com` | as above |
| Read-only manager | `manager@demo.example.com` | as above |
| Customer A1 (Vietnamese) | `trang.air@example.com`, at `/account/sign-in` | the Customer Account password in `ENVIRONMENT.md` §2 |
| Customer A2 (English) | `emily.air@example.com`, at `/account/sign-in` | as above |

`uat_env.py --check` also prints all of them. To approve tariffs with your own account
instead of the demo Admin, see `ENVIRONMENT.md` §2, "The tariff approver in UAT".

## Where the emails are

Every email the system "sends" is a file in `data\uat\account_mail\`, newest last by name;
the kind is in the file name (`verify_email`, `quote.sent.vi`, `notify.in_transit.en`, …).
Since RC-UAT-18, sending a draft invoice adds `invoice.sent.vi` or `invoice.sent.en` (the
invoice number, total and due date; no lines). There is no mailbox screen. Open the file to
read it or copy a link.

## 5. Run a worker once (window 3, only when a case says so)

Set the same variables as window 1 (paste every line of §3 above the `uvicorn` line: the
`$uat` line and seven settings), then from `backend\`:

```powershell
cd backend
.venv\Scripts\python -m app.workers.notification_worker --once    # queued milestone emails
.venv\Scripts\python -m app.workers.tariff_intake_worker --once   # .eml files in data\uat\tariff_intake
.venv\Scripts\python -m app.workers.retention_worker --once --dry-run   # counts only (UAT-BLD-17)
```

On the portable UAT package, from its folder (`uat\env.ps1` loads the UAT settings and
changes into `backend\`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\uat\env.ps1; .venv\Scripts\python -m app.workers.retention_worker --once --dry-run"
```

**Do not run `app.workers.fx_worker` in UAT**: it calls the bank. Use `--refresh-fx` (§2).
**Run the retention worker only with `--dry-run`**, and never turn retention deletion on in
**Settings → Retention**: the periods are undecided (OD-01, OD-36) and enabling it needs the
owner's written approval. It is off on every reset, so a run without `--dry-run` only prints
"retention deletion is off: nothing was done"; there is still no reason to run one.

## Import templates

The CSV templates for the imports are in `artifacts\sample-imports\`:
`customer-import-template.csv`, `shipment-import-template.csv` and
`legacy-history-template.csv` (the same files download from each import page). Copy one
outside the repository before editing it, keep it UTF-8 (Excel: **Save as → CSV UTF-8**), and
replace the sample customer IDs with real test customers' (`AIR_UAT_PACK.md`, `UAT-BLD`
group).

## Between sessions, and at the end

- Before each pack, or whenever a case says "fresh reset": stop the backend, run §2 again,
  start §3. Cases change the data; a second pass over an un-reset database tests something
  else.
- At the end: `backend\.venv\Scripts\python scripts\uat_env.py --destroy` removes the
  database, the captured mail and the rate-email folder. `git status` must show nothing new
  from UAT.

## Recording results

Fill in the case's own fields in the pack while you test (`UAT_CASES.md`,
`CUSTOMER_ACCOUNT_UAT_PACK.md`, `AIR_UAT_PACK.md`), one defect report per finding
(`DEFECT_TEMPLATE.md`), and the summary sheet (`UAT_SUMMARY.md`). The owner's guided route
through the air pack is `UAT_SCRIPT_FOR_BEN.md`.
