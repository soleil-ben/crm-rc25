# Solaris Express CRM — UAT package RC-UAT-25

For Louis. This folder runs the release candidate **RC-UAT-25** (application commit
`bccbddf`; what changed is in §5a below and in `docs\b2c_merge\`) on your own Windows PC,
with **synthetic test data only**. No real customer data, no `.env`, no live database, no production endpoint. Email is
never sent: every message is written as a file on this PC.

## 1. Prerequisites (install once)

| Tool | Version | Notes |
|---|---|---|
| Windows | 10 or 11 | Windows PowerShell 5.1 (built in) |
| Python | **3.12.10, 64-bit** recommended; **3.11 to 3.14** accepted (3.14.9 tested). **3.15 is not supported yet** | python.org "Windows installer (64-bit)"; tick *Add python.exe to PATH* and keep the *py launcher* |
| Node.js | **24.11.1 LTS** (npm **11.6.2**; Node 20.19+ / 22.12+ accepted) | nodejs.org installer |
| Internet | first start only | downloads the pinned Python and npm packages (`backend/requirements.lock.txt`, `frontend/package-lock.json`) |

Ports **8000** (backend) and **5173** (frontend) must be free.

### If START_UAT.bat says no usable Python was found

The launcher looks in the `py` launcher's list (`py -0p`), the standard install folders
(`%LOCALAPPDATA%\Programs\Python\Python3xx`, `%LOCALAPPDATA%\Python\pythoncore-3.xx-64`,
`%ProgramFiles%\Python3xx`) and `PATH`. It skips the Microsoft Store `python.exe` aliases in
`WindowsApps` (they open the Store instead of running Python). When it finds nothing usable it
prints every Python it saw, with its version and path and why it was refused, plus the fix steps.

* See what it sees, without starting anything: in this folder run
  `powershell -NoProfile -ExecutionPolicy Bypass -File uat\uat.ps1 python`.
* **Python 3.15 installed?** Keep it and install 3.12.10 (or 3.14) alongside: five pinned
  packages (httptools, MarkupSafe, pydantic_core, PyYAML, watchfiles) have no Python 3.15 build yet.
* **Python installed but not found?** Point the launcher at it, in the same Command Prompt
  window: `set UAT_PYTHON=C:\full\path\to\python.exe` (no quotes needed, even with spaces), then
  `START_UAT.bat`.
* After changing Python, a `backend\.venv` built with the old one is rebuilt automatically.

## 2. Steps

1. Extract the zip to a short path, e.g. `C:\UAT\Solaris_CRM_UAT_RC25`.
2. Double-click **`START_UAT.bat`**. The first run creates `backend\.venv`, installs the
   frontend packages, builds the UAT database and takes a few minutes; later starts take
   about 20 seconds. The browser opens at <http://localhost:5173>.
3. Keep the START window open while you test. Press **Enter** in it to stop the servers
   (or run **`STOP_UAT.bat`**).
4. Optional: with the servers running, **`SMOKE_UAT.bat`** runs a quick HTTP check
   (health, every sign-in, the seeded data, captured emails).
5. **`RESET_UAT.bat`** rebuilds the UAT database from scratch and starts again. Use it
   before each pack, or whenever a case says "fresh reset".

| Address | What |
|---|---|
| <http://localhost:5173> | Staff Portal |
| <http://localhost:5173/account> | Customer Account (Vietnamese first; English switch at the top) |
| <http://localhost:5173/track> | Public tracking |

## 3. Logins

Passwords: as in **`docs\UAT\ENVIRONMENT.md` §2** (demo-only accounts, synthetic).

| Who | Email |
|---|---|
| Admin (also the tariff approver in UAT) | `admin@demo.example.com` |
| Operations | `ops@demo.example.com` |
| Marketing | `marketing@demo.example.com` |
| Read-only manager | `manager@demo.example.com` |
| Customer A1 (Vietnamese), at `/account/sign-in` | `trang.air@example.com` |
| Customer A2 (English), at `/account/sign-in` | `emily.air@example.com` |

## 4. Where the emails are

Every email the system "sends" is a file in:

```
<this folder>\data\uat\account_mail\
```

Open the folder in Explorer and open a file with Notepad (or any text editor). The newest
is last by name; the kind is in the file name (`verify_email`, `quote.sent.vi`,
`invoice.sent.vi` / `.en` (sent from a draft invoice), `notify.in_transit.en`, …). Links inside point to `http://localhost:5173`. `RESET_UAT.bat`
clears the folder.

Rate emails for the tariff cases are `.eml` files in `data\uat\tariff_intake\`.

## 5. What to test, and how to record it

* Start with `docs\UAT\HOW_TO_RUN.md` (one page) and `docs\UAT\README.md` (process).
* Packs: `docs\UAT\AIR_UAT_PACK.md` (53 air cases: workspace, quotes, Customer Account
  acceptance, finance, pricing, tariffs, milestone emails, and the new `UAT-OWN-01` to `-17`
  for your 2026-10-21 answers), `docs\UAT\UAT_CASES.md` (49 staff
  and public cases), `docs\UAT\CUSTOMER_ACCOUNT_UAT_PACK.md` (60 cases).
* The owner's guided route: `docs\UAT\UAT_SCRIPT_FOR_BEN.md`.
* Record results in the pack's own fields, one `docs\UAT\DEFECT_TEMPLATE.md` per finding,
  and `docs\UAT\UAT_SUMMARY.md`.
* Open owner questions (cases test the current stand-ins): `docs\b2c_merge\19_OWNER_QUESTIONS.md`.

`HOW_TO_RUN.md` describes the same steps as manual PowerShell commands. In this package the
`.bat` files do them for you: same database path (`data\uat\solaris_uat.uat.db`), same
settings (`uat\uat.env`), same ports.

## 5a. New in RC-UAT-21 (Ben's build direction of 2026-10-24)

| Feature | Where to see it |
|---|---|
| Shipment import and legacy history baseline | Staff import screen: CSV upload, dry run with a per-row report first, then commit; templates in `artifacts\sample-imports\` |
| Change password (customer and staff), customer email change, Admin reinstatement | Customer Account → Profile; staff user menu; Admin on the deactivated customer account |
| Quote tax wording (pending Ben, P-9) | Domestic quotes: "Giá đã bao gồm HST/GST n %" at the destination province's rate; international: "Thuế suất 0 (0 %)" |
| Admin soft delete of old quotes; retention machinery (off by default) | Workspace quote history (Admin); Settings → Retention (periods undecided, OD-01/OD-36) |

## 5a-bis. New in RC-UAT-20 (Ben's answers of 2026-10-23)

| Answer | Where to see it |
|---|---|
| GST/HST by route | International shipments zero-rated (0 %); domestic drafts include HST/GST at the destination province's rate (ON 13, NS 14, NB/NL/PE 15, others 5 % GST); Settings → GST/HST rates (Admin) |
| Costume jewellery | Staff enter both the vendor's VND cost and the customer price |
| Payment date, draft Download, legs, tariff warnings | Payment dates stay as entered; Download waits for the tax tick; "Theo dõi chặng chính" / "Theo dõi chặng cuối" on staff and customer views; Settings → Tariffs → View shows the 39 warnings |

## 5b. New in RC-UAT-19 (your answers of 2026-10-22)

| Answer | Where to see it |
|---|---|
| GST/HST on draft invoices (OD-94, pending your confirmation P-1/P-2) | A draft opens at **13 %, included in the price** (backed out of the all-in total). Tick "I have checked the GST/HST on this invoice" before **Save** or **Send**; changing a line, the rate or the mode clears the tick. Rate 0/5/13 % and "included" / "added on top" can be changed. PDFs say "Prices include GST/HST 13 %" |
| Tracking links and names (OD-91, OD-92) | Public tracking and the Customer Account show the carrier links (UPS, Canada Post …) under **Master Tracking** / **Last Mile Tracking** (Vietnamese "Theo dõi chặng chính" / "Theo dõi chặng cuối", proposed, P-4); never the vendor's name |
| Costume jewellery (OD-93) | Adding HCM row 27 asks for the vendor's quoted amount (VND); finalising is blocked until it is entered; item kg no longer matters |
| START_UAT.bat finds Python | 3.11 to 3.14 found wherever installed (3.15 refused with the reason); see §1 "If START_UAT.bat says no usable Python was found" |

Cases `UAT-OWN-18` to `-27` cover these (`docs\UAT\AIR_UAT_PACK.md`). New open questions:
`docs\b2c_merge\19_OWNER_QUESTIONS.md` §00 (P-1 to P-8).

## 5c. New in RC-UAT-18 (your answers of 2026-10-21)

| Answer | Where to see it |
|---|---|
| Booked master locks items and fees (OD-88) | Workspace → a booked master: "Items and fees locked" badge; item and fee controls disabled. As Admin: **Unlock for edits** (reason required, audited); **Lock again** (Admin or Operations). Finalising a member's quote locks it again by itself |
| Acceptance creates a draft invoice (OD-89, OD-90) | After the customer accepts in the Customer Account: Workspace "Review draft invoice", or Finance → Accepted, not invoiced. On the draft: **Edit**, **Save** (required first: Send and Download stay disabled while edits are unsaved), **Download** (PDF with a DRAFT watermark; the browser saves it to its Downloads folder), **Send** (asks for confirmation, assigns the INV- number, writes the `invoice.sent` email file) |
| Quote expiry (OD-89) | Approve a new tariff version (Settings → Tariff updates, as Admin): quotes whose goods are not yet received expire ("Expired: re-quote on the new rate"; the customer sees "Đã hết hạn"); received goods never expire |
| No vendor name customer-side (OD-84) | Customer Account, printed quote, invoice PDFs and emails show neutral labels ("Phụ phí" / "Surcharge"); staff screens keep the vendor wording |
| Express 16 kg step, meat surcharge, per-kg bases (OD-81 to OD-83) | Settings → Tariffs → the version's import report: 3 owner-confirmed price steps and 39 warnings; HCM meat surcharge 20,000 VND/kg |

Cases `UAT-OWN-05` to `-07` need a fresh reset (`RESET_UAT.bat`) before you start them.
Follow-up questions created by your answers (stand-ins in force, nothing blocked) are in
`docs\b2c_merge\19_OWNER_QUESTIONS.md` §0 (F-1 to F-10, Q-P1, Q-P2).

## 6. Running a worker once (only when a case says so)

From PowerShell in this folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\uat\env.ps1; .venv\Scripts\python -m app.workers.notification_worker --once"
powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\uat\env.ps1; .venv\Scripts\python -m app.workers.tariff_intake_worker --once"
```

(`uat\env.ps1` loads the UAT settings and changes into `backend\`.)

Rate-sheet approver (DEC-0268): only Ben holds it after the reset. To give it to another Admin
account (for example Louis, once his CRM login is confirmed), use Settings → Kango rate
sheets → "Give the permission to", or one line:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\uat\env.ps1; .venv\Scripts\python ..\scripts\grant_tariff_approver.py <staff login email>"
```

Add `--revoke` to take it away.

A newer demo exchange rate (when testing on a later day than the reset):
`backend\.venv\Scripts\python scripts\uat_env.py --refresh-fx`. **Never run
`app.workers.fx_worker`**: it calls the bank.

## 7. Good to know

* **Configuration.** No `.env` is used. `uat\uat.env` holds the UAT-safe settings (capture
  email, Vietnamese + English, local origins). On first start `uat\uat.local.env` is
  generated with a random `SECRET_KEY` for this PC only. `backend\.env.example` and
  `frontend\.env.example` are the documented templates; do **not** create `backend\.env`
  (the launcher refuses to start if one exists).
* **Logs**: `data\uat\logs\backend.log` and `frontend.log`.
* **Not in this package**: the git history, `node_modules`, the Python venv (created on first
  start), any database (built on first start). The full source of `backend\` and
  `frontend\` is included, with the test suites (`backend\tests`, `frontend\tests`).
* **Clean up**: stop, then delete the folder. Nothing is installed outside it except the
  pip and npm download caches.
* `MANIFEST.txt` lists every file with its SHA-256 and the commits it came from.
