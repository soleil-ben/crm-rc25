# The UAT environment — start, reset, shutdown, cleanup

> **Synthetic data only.** Every record is fictional. No real customer information, no
> provider credentials, and no external request. If anything in this environment looks
> like a real customer, stop and report it — that is a defect, not a coincidence.

---

## 1. What this environment is

| | |
|---|---|
| Database | `data/uat/solaris_uat.uat.db` — **separate**, git-ignored, disposable |
| Build | `scripts/uat_env.py` |
| Candidate under test | `RC-UAT-25`: RC-UAT-24 plus the fix pack for Ben's live UAT of 2026-10-25 (OD-113; DEC-0240 to DEC-0247; `docs/b2c_merge/29_BUILD_RC25_RECORD.md`; migration `a5c7e9b1d3f6`, two new tables, `customer_account_email_changes` and `shipment_event_revisions`, nothing existing altered): a red `*` beside each required label instead of "(required)", staff portal and Customer Account (DEC-0240); the booking's declared value currency is a list, —, CAD, VND, enforced by the server and the shipment import (DEC-0241); the recipient card offers the customer's saved addresses (DEC-0242); the customer can no longer change the sign-in email — an Admin does, with **Change sign-in email** on the staff account screen (DEC-0243); "Received at warehouse" replaces "Received at Solaris" (DEC-0244); Admin and Operations can **Edit** a recorded or published timeline event, with a reason and revision history, never emailing (DEC-0245); the blank Financials tab is fixed at its cause, a recorded-amount currency that was not three letters, and every shipment tab sits in an error boundary (DEC-0246); the Financials tab opens with a **Quote and invoice** card and the header gains **Quote & invoice** (DEC-0247). Stand-ins RC25-A1 to A8, RC25-B1 to B13 and RC25-C1 to C7 (`19_OWNER_QUESTIONS.md` §000000). The reset seeds nothing new: `UAT-BLD-26` to `-33` start from a fresh reset; `UAT-BLD-09` is now the Admin's change and `UAT-BLD-10` is withdrawn. Baseline **in force**: `docs/RC_UAT_25_BASELINE.md`, measured at the application commit `bccbddf`; `scripts/verify_rc_baseline.py` checks it by default |
| Previous candidate | `RC-UAT-24`: RC-UAT-23 plus Ben's evening answers of 2026-10-24 (OD-112; DEC-0236 to DEC-0239; `docs/b2c_merge/28_BUILD_RC24_RECORD.md`; data-only migration `e7a9c1d3f5b6`, no table or column changed): the legal entity reads **Solaris Express Inc.** on **Settings → Brand and tracking → Legal entity**, the staff login footer (English and Vietnamese) and the demo label sender (I-10; the migration renames a settings row still holding exactly "Soleil Global Transportation Inc." and leaves any other value alone); the draft invoice editor says "Tax included in the price: subtotal before tax …" with the invoice's summary labels (I-11); I-1 (English-only invoice PDF, names without accents) and I-12 (the cent nudge) confirmed as built; the held items stay unbuilt. The reset seeds nothing new beyond the label sender's name: `UAT-BLD-25` starts from a fresh reset. Baseline `docs/RC_UAT_24_BASELINE.md` (superseded), measured at the application commit `f4a04a3`; check it with `scripts/verify_rc_baseline.py --baseline docs/RC_UAT_24_BASELINE.json` |
| Earlier candidate | `RC-UAT-23`: RC-UAT-22 plus invoices that follow the Solaris Invoicing desk (OD-111, Ben, 2026-10-24; OD-109 confirmed; DEC-0235; `docs/b2c_merge/27_BUILD_RC23_RECORD.md`; **no migration**): domestic courier lines back GST/HST out per line at the destination province's rate from **Settings → GST/HST rates**, international Air Freight is zero-rated, issued invoices show each line at its net with a Tax column and summary rows (the total still the all-in total), and invoice PDFs are English only, without accents, with the Solaris Express Inc. company block, Terms: Due on receipt, the E-transfer and BMO wire lines and the desk's footer; quotes keep their inclusive wording; the manual Issue invoice keeps tax added on top; invoices issued before are untouched (stand-ins I-1 to I-13, `19_OWNER_QUESTIONS.md` §00000). The reset seeds nothing new: `UAT-BLD-20` to `-24` start from a fresh reset (the seeded domestic drafts and the existing invoices); `uat_smoke.py` checks the per-line rule. Baseline `docs/RC_UAT_23_BASELINE.md` (superseded), measured at the application commit `3151095`; check it with `scripts/verify_rc_baseline.py --baseline docs/RC_UAT_23_BASELINE.json` |
| Earlier candidate | `RC-UAT-22`: RC-UAT-21 plus the build of B-13 (DEC-0234; `docs/b2c_merge/26_BUILD_RC22_RECORD.md`; migration `d4f6b8c0e2a5`, one new table, nothing existing altered): Admin re-links an account left without a customer after reinstatement (history previewed and acknowledged, the single email rule, audited) or closes it (reversible deactivation), on **Customer accounts → Accounts needing a customer** (stand-ins B-15 to B-20); the Playwright harness binds both servers to `127.0.0.1`; `test_e2e_safety` passes in worktrees. The reset seeds nothing new: `UAT-BLD-18` and `-19` follow on from `UAT-BLD-13`, which leaves A1's account without a customer. Baseline `docs/RC_UAT_22_BASELINE.md` (superseded), measured at the application commit `61f5c22`; check it with `scripts/verify_rc_baseline.py --baseline docs/RC_UAT_22_BASELINE.json` |
| Earlier candidate | `RC-UAT-21`: RC-UAT-20 plus the build Ben asked for on 2026-10-24 (OD-110; DEC-0230 to DEC-0233; `docs/b2c_merge/25_BUILD_RC21_RECORD.md`; migrations `a1c3e5f7b9d2`, `b2d4f6a8c1e3`, `c3e5a7b9d2f4`, new tables only): shipment CSV import and the legacy history baseline, the customer's and the staff member's own password change, the customer's sign-in email change, Admin reinstatement of a deactivated account, the customer quote's GST/HST line (OD-109 stand-in, pending Ben), Admin soft delete of old quote versions, and the retention machinery, **off** (dry run only in UAT, §3d). The reset seeds nothing new: the `UAT-BLD` cases create their own data, the imports from the templates in `artifacts\sample-imports\`. Baseline `docs/RC_UAT_21_BASELINE.md` (superseded), measured at the application commit `be7d2df`; check it with `scripts/verify_rc_baseline.py --baseline docs/RC_UAT_21_BASELINE.json` |
| Earlier candidate | `RC-UAT-20`: RC-UAT-19 plus the fix pack for Ben's answers of 2026-10-23 (OD-102 to OD-108: GST/HST on the draft invoice by route — international 0 %, domestic included at the destination province's rate from **Settings → GST/HST rates** —, costume jewellery with both the VND cost and the customer price, and the RC-UAT-19 findings fixed; `docs/b2c_merge/24_FIXPACK_RC20_RECORD.md`; migration `f7c2d9e3a1b5`; DEC-0227 to DEC-0229). The reset now invoices A1's `UAT-AIR-A1-1` at 0 % (zero-rated), so `--check` expects **2** invoice tax choices (0 and 5 %); it also adds, **for UAT only**, three domestic shipments for A2 on their own master `UAT-DOM-AWB` (domestic shipments cannot be quoted on screen), with unsent drafts at 14 % (NS), 15 % (NB) and one awaiting a rate, each a `--check` category; quotes accepted: 5. Baseline `docs/RC_UAT_20_BASELINE.md` (superseded), measured at the application commit `98ca88b`; check it with `scripts/verify_rc_baseline.py --baseline docs/RC_UAT_20_BASELINE.json` |
| Earlier candidate | `RC-UAT-19`: RC-UAT-18 plus the fix pack for the owner answers of 2026-10-22 (OD-91 to OD-101: GST/HST 13 % included and checked on the draft invoice, generic tracking names for customers, costume jewellery by amount; `docs/b2c_merge/23_FIXPACK_RC19_RECORD.md`; migration `e6b1c4a8d2f3`; DEC-0223 to DEC-0226). Baseline `docs/RC_UAT_19_BASELINE.md` (superseded), measured at the application commit `418cf3f`; check it with `scripts/verify_rc_baseline.py --baseline docs/RC_UAT_19_BASELINE.json` |
| Earlier candidate | `RC-UAT-18`: RC-UAT-17 plus the fix pack for the owner answers of 2026-10-21 (OD-81 to OD-90, DEC-0219 to DEC-0222; `docs/b2c_merge/22_FIXPACK_RC18_RECORD.md`). Baseline `docs/RC_UAT_18_BASELINE.md` (superseded), measured at the application commit `03b943d`; check it with `scripts/verify_rc_baseline.py --baseline docs/RC_UAT_18_BASELINE.json` |
| Superseded, preserved unchanged | `RC-UAT-1` to `RC-UAT-17` — each still verifiable with `--baseline`. Some still title themselves "in force"; they are not. They are left byte-identical on purpose, because a superseded baseline that acquires new text stops being evidence |
| Test packs | `UAT_CASES.md` — 49 staff and public cases; `CUSTOMER_ACCOUNT_UAT_PACK.md` — 60; `AIR_UAT_PACK.md` — 104 cases (36 from Phase 17, 17 `UAT-OWN` from RC-UAT-18, 10 `UAT-OWN` from RC-UAT-19, 8 `UAT-OWN` from RC-UAT-20, 17 `UAT-BLD` from RC-UAT-21, 2 `UAT-BLD` from RC-UAT-22, 5 `UAT-BLD` from RC-UAT-23, 1 `UAT-BLD` from RC-UAT-24, 8 `UAT-BLD` from RC-UAT-25; `UAT-BLD-10` withdrawn in RC-UAT-25, heading kept). **All unexecuted** |
| Python | 64-bit CPython **3.11 to 3.14** (**3.12.10 recommended**, 3.14 tested). **3.15 is not supported yet**: httptools, MarkupSafe, pydantic_core, PyYAML and watchfiles have no 3.15 build at the pinned versions (open question P-8). See §2 |
| Quick start | `HOW_TO_RUN.md` (one page); the owner's walk-through is `UAT_SCRIPT_FOR_BEN.md` |

It is not the development database and cannot be pointed at it. The build script refuses,
in this order:

1. `ENVIRONMENT=production` — refused outright;
2. a path that does not end in `.uat.db` — refused;
3. a path outside `data/uat/` — refused;
4. the development database, or whatever `DATABASE_URL` currently points at — refused by
   resolved path, so a relative path or a symlink cannot slip past.

Each refusal exits 2 and names the reason.

---

## 2. Build it

**Which Python.** The virtual environment `backend/.venv` must be built with 64-bit CPython
3.11 to 3.14; 3.12.10 is the reference and is recommended, 3.14 is tested. Python 3.15 is
**not supported yet** (no 3.15 build of five pinned packages; `pydantic_core` would need a
Rust build), and the portable package's start script refuses it with that message. On the
portable package, this lists every Python the PC offers and the one the start script would use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File uat\uat.ps1 python
```

To make it use a particular install, set `UAT_PYTHON` to that `python.exe`'s full path in the
same PowerShell window before starting (`$env:UAT_PYTHON = "C:\Program Files\Python312\python.exe"`);
if that one is not usable (too old, 3.15, 32-bit) it says so and looks for another. In a
repository checkout, `py -3.12 -m venv backend\.venv` picks the version explicitly.

```bash
backend/.venv/Scripts/python scripts/uat_env.py --reset
```

This destroys any existing UAT database, migrates a new one to head, seeds the synthetic
data, adds the workflows the seed leaves empty, adds the **air dataset** of Phase 17
(`scripts/uat_seed_phase13.py`: the sanitized tariff, demo exchange rates, five air masters
at different stages (and, for UAT only, a sixth with three domestic shipments), quotes, an acceptance, invoices, payments in CAD and VND, a refund,
vendor bills, a closed month, two linked Customer Accounts, milestone emails and two vendor
rate emails — `AIR_UAT_PACK.md` lists it all), and prints a coverage report. **Exit
status 1 means a required category is missing** — do not hand the environment to a tester
in that state.

The report ends with the UAT accounts. All five use the same password and all five sit on
reserved domains, which is what stops them working in production:

| Role | Account |
|---|---|
| Admin | `admin@demo.example.com` |
| Operations | `ops@demo.example.com` |
| Marketing | `marketing@demo.example.com` |
| Read-only manager | `manager@demo.example.com` |

Password for every account: `SolarisDemo!2026`

The Phase 17 air dataset adds two **Customer Accounts**, signed in at `/account/sign-in`,
used only by `AIR_UAT_PACK.md` (the Customer Account pack creates its own):

| Customer | Account |
|---|---|
| A1, Phạm Thị Thu Trang (Vietnamese) | `trang.air@example.com` |
| A2, Emily Carter (English) | `emily.air@example.com` |

Password for both: `SolarisUatCustomer!2026`

These credentials are written down here deliberately. They are safe to write down because
they cannot be used against production: the application **refuses to start** in production
while an account on a reserved domain is active, and `authenticate` refuses the address
before it checks the password. See `backend/app/core/demo_identity.py`.

### The tariff approver in UAT, and how the owner adds himself

The air dataset sets the tariff **Approvers** list to `admin@demo.example.com` only, so a
tester signed in as the demo Admin can approve. No real address is seeded. In production the
default approver is the owner (OD-76). To approve with his own account in UAT, the owner:

1. signs in as `admin@demo.example.com` (an approver);
2. creates a staff account for himself under **Settings → Staff and permissions**, role
   **Admin** (approving needs the tariff-manage permission, which only Admin holds);
3. opens **Settings → Tariff updates → Approvers**, adds that address, and saves;
4. signs in with his own account. The change is audited, and `--reset` removes it.

---

## 3. Start the stack

> ### WARNING - on Windows, `$PWD` will silently give you an empty database
>
> Every `DATABASE_URL` below is written `sqlite:///$PWD/...`. In **Git Bash** `$PWD`
> expands to a POSIX path (`/c/Users/...`), and SQLite does not resolve that to a Windows
> path. It creates a **new, empty** database somewhere else instead. The backend starts,
> `/health` answers `200`, and the first real request fails with
> `no such table: shipments` - which reads like a migration problem and is not one.
>
> **Set it to the absolute Windows path, with forward slashes:**
>
> ```bash
> DATABASE_URL="sqlite:///C:/path/to/Solaris_CRM_Claude_Package/data/uat/solaris_uat.uat.db"
> ```
>
> Confirm before testing anything - this prints the path actually in use:
>
> ```bash
> backend/.venv/Scripts/python -c "import sys; sys.path.insert(0,'backend'); from app.core.config import settings; print(settings.database_url)"
> ```
>
> In **PowerShell** `$PWD` is already a Windows path, but set the variable with
> `$env:DATABASE_URL = "..."` on its own line - PowerShell has no inline env-var prefix.


Two processes. Neither is started by Playwright, and neither should be started with a
production configuration.

```bash
DATABASE_URL="sqlite:///$PWD/data/uat/solaris_uat.uat.db" ENVIRONMENT=development \
  backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000 --app-dir backend --no-proxy-headers
```

```bash
npm run dev --prefix frontend
```

Then open <http://localhost:5173>.

### If the default ports are busy

They often are — a development stack may already be running. **Do not change the
production defaults to work around it.** Override them for the session instead:

```bash
DATABASE_URL="sqlite:///$PWD/data/uat/solaris_uat.uat.db" ENVIRONMENT=development \
  backend/.venv/Scripts/python -m uvicorn app.main:app --port 8010 --app-dir backend --no-proxy-headers
```

```bash
VITE_API_TARGET=http://127.0.0.1:8010 npm run dev --prefix frontend -- --port 5183 --strictPort --host 127.0.0.1
```

In PowerShell:

```powershell
cd frontend; $env:VITE_API_TARGET = 'http://127.0.0.1:8010'; npm run dev -- --port 5183 --strictPort --host 127.0.0.1
```

`npm run dev` runs the repository's own installed Vite (`frontend/node_modules`); do not use
`npx`, which may download a different one.

**On any frontend address other than `http://localhost:5173`, start the backend with two more
settings**, or the Customer Account will not sign in and captured email links will point at
the wrong place:

* `CORS_ORIGINS` — the frontend's exact origin, for example `http://127.0.0.1:5183`. The
  Customer Account refuses a request whose `Origin` is not listed (sign-in fails).
* `TRACKING_BASE_URL` — for example `http://127.0.0.1:5183/track`. Links in captured emails
  (verification, quotes) are built from it, with `/track` replaced by `/account`; by default
  they point at `http://localhost:5173`.

Two notes, both learned the hard way during this phase:

* **Vite binds IPv6 by default.** Started without `--host`, it serves `localhost:5183`
  but *not* `127.0.0.1:5183`. Pass `--host 127.0.0.1` when anything needs the IPv4
  address, and use whichever address you bound.
* **`--strictPort` is deliberate.** Without it Vite silently picks the next free port, and
  a tester ends up on a page served by a different stack than the one they think they are
  testing.

### Do not run the Playwright suite against this stack as started above

The commands above deliberately use the **production** rate limits, because a human tester
should meet the limits a customer meets. The automated end-to-end suite must not: it
replays every public lookup from one loopback address, and at the production defaults —
30 public lookups per 60 s and 8 sign-ins per 300 s — it throttles *itself* and reports
failures on lookups that have nothing wrong with them.

`docs/OPERATIONS.md` section 8 is the authority for that run, and it raises both:

```bash
DATABASE_URL="sqlite:///$PWD/data/uat/solaris_uat.uat.db" ENVIRONMENT=development \
  PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS=200 LOGIN_RATE_LIMIT_ATTEMPTS=100 \
  backend/.venv/Scripts/python -m uvicorn app.main:app --port 8010 --app-dir backend --no-proxy-headers
```

Nothing in the limiter changes; `zzRateLimit.spec.js` still exhausts whatever limit is
configured and proves it engages. This note exists because the pre-UAT gate review made
exactly this mistake and spent two full suite runs diagnosing self-inflicted 429s.

To confirm which stack you are on before testing anything:

```bash
curl -s -o /dev/null -w "backend %{http_code}\n" http://127.0.0.1:8010/health
```

---

## 3a. The Customer Account, and its mail (RC-UAT-4)

The 60 cases in `CUSTOMER_ACCOUNT_UAT_PACK.md` need two things section 3 does not give
you: a transport that writes mail somewhere you can read it, and the knowledge that the
seed's only Customer Accounts (A1 and A2, section 2) belong to `AIR_UAT_PACK.md`. For the
Customer Account pack a tester creates an account by registering, and a staff reviewer
approves it — which is the first journey the pack asks for, and is why it is `CA-REG-01`.

The air pack needs the same capture transport (quote and milestone emails are written
there) and one more folder: `TARIFF_INTAKE_DIR`, the rate-email intake folder, which in UAT
is `data/uat/tariff_intake`. The command below sets both. **Use it for every UAT pass.**

Since the 2026-10-14 fix pack the seed does supply the *customer* side: the test people
P1–P5, P1's cancelled and rebooked shipments, a 28-shipment customer for paging, and one
non-demo shipment on `STCA-000001` so an account linked to it has a list to open (demo
records are excluded from the Customer Account by rule). Verification and reset links now
carry their token in the URL **fragment** (`#token=…`), so copy the whole link including
the part after `#`.

### Start the backend with the capture transport

The default transport is `null`: it records that a send was requested and produces
nothing. Registration will appear to work and no verification link will ever exist. Start
the backend like this instead:

```bash
DATABASE_URL="sqlite:///$PWD/data/uat/solaris_uat.uat.db" ENVIRONMENT=development \
  ACCOUNT_EMAIL_TRANSPORT=capture ACCOUNT_EMAIL_CAPTURE_DIR="$PWD/data/uat/account_mail" \
  TARIFF_INTAKE_DIR="$PWD/data/uat/tariff_intake" \
  backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000 --app-dir backend --no-proxy-headers
```

The `$PWD` warning in section 3 applies to `ACCOUNT_EMAIL_CAPTURE_DIR` and
`TARIFF_INTAKE_DIR` as well — give them the absolute Windows path with forward slashes in
Git Bash. `HOW_TO_RUN.md` gives the same command for PowerShell.

The capture directory is deliberately `data/uat/account_mail` and not the development
default of `data/account_mail`. It sits beside the UAT database so that
`uat_env.py --reset` and `--destroy` throw the mail away with everything else. A captured
verification link is a live credential for whatever account it was issued against, and
yesterday's links must not be readable during today's pass.

### Read the mail

There is no mailbox screen, in this environment or any other, and there will not be one.
`docs/OPERATIONS.md` section 15 is the authority. Each message is one JSON file:

```
data/uat/account_mail/260921T142233451234-verify_email-newcustomer@example.co.json
```

Newest last when sorted by name. The template key is in the middle of the filename, so
the file you want is usually obvious without opening anything:

```bash
ls -1 data/uat/account_mail | tail -5
```

The six account keys are `verify_email`, `registration_attempt_notice`,
`password_reset`, `password_changed`, `approved` and `rejected`. Since Phases 13F and 13G
two more kinds land here: `quote.sent.<language>` (a quote staff sent; no amount in it) and
`notify.<milestone>.<language>` (a milestone email). Since RC-UAT-18 (owner decision 9a),
**Send invoice** on a draft invoice adds `invoice.sent.vi` or `invoice.sent.en`, in the
customer's language: the invoice number, the total and the due date, no line and never a
vendor name. The UAT reset sends A1's seeded draft without an email, so none is captured
at reset. Open the file and copy the URL out of the body.

### Two behaviours that look like faults and are not

* **A resend invalidates the previous link.** The older file is still on disk and the link
  in it no longer works. Use the newest file for an address, always.
* **Registering twice with the same address sends no second verification message.** It
  sends a `registration_attempt_notice` to the address that already has an account, and
  the response a tester sees is word-for-word identical to the first one. That is the
  anti-enumeration behaviour `CA-REG-02` exists to check, not a lost message.

### The approval half

`CA-APR-*` needs a staff reviewer. Sign in at the Staff Portal as `ops@demo.example.com`
or `admin@demo.example.com` and open **Customer accounts**. Marketing and the read-only
manager hold neither `customer_account:review` nor `customer_account:approve`, see no
navigation entry, and are refused by the route and by the server — which two of the cases
ask you to confirm on purpose.

The approval preview writes a disclosure audit row every time it is read. That is
intended, and it is why the review screen loads its three panels one after another rather
than at once.

### The Customer Account is Vietnamese first

Since 2026-10-20 (OD-71, which replaced the English-only release of OD-39) every Customer
Account screen opens in **Vietnamese**, with a **Tiếng Việt / English** switch at the top
of every screen. A signed-in customer's saved language applies when they sign in; nothing
about the choice is stored in the browser. The Vietnamese wording has been checked for
completeness only, not by a native speaker (`19_OWNER_QUESTIONS.md` #6): record wording
findings as S5. `REVIEW_customer_account_copy.md` reviews the English copy. The Staff Portal
approval screens are bilingual too — screens 26 to 30 of `REVIEW_vietnamese_ui.md`.

### The profile and notification screens exist

`CA-PRF-01` through `CA-PRF-04` were out of scope at Phase 12. **Hồ sơ của tôi** / My
profile (fix pack 2) and **Thông báo** / Notifications (Phase 13F) now exist, so the four
cases are run like any other.

---

## 3b. Data for two Customer Account cases (UAT round 3)

### CA-REG-07 — an expired verification link

The verification link lives 24 hours. Rather than wait, the operator ages it:

```bash
backend/.venv/Scripts/python scripts/expire_account_link.py newcustomer.tl1015@example.com
```

Use the address the tester registered. This sets the **outstanding** verification link for
that address to have expired a minute ago (moving its issue time back by the same amount),
through the application's models, and records a `customer_account.link_aged_for_testing`
audit event naming the account reference. It never prints or changes the link itself: the
link in the newest captured message is the one the tester opens, and the server now refuses
it as expired. `--purpose password_reset` ages a reset link instead; `--purpose all` both.

It works on the running stack's database — SQLite lets it write while the backend is up —
and it refuses, exit status 2, unless all of these hold:

1. `ENVIRONMENT` is `development` or `uat` (unset counts as `development`, as it does for
   the application). `production`, `e2e`, `test` and anything else are refused;
2. the database already exists — it never creates one;
3. it is not an `.e2e.db`, not in `data/e2e/` and not under `backups/`;
4. it is a `.uat.db` inside `data/uat/` (the default is `data/uat/solaris_uat.uat.db`), or
   the development database `data/solaris_crm.db` **and only with**
   `ENVIRONMENT=development`. Any other path is refused;
5. the address is on a reserved test domain (`example.com` and the others in
   `app.core.demo_identity`).

Exit status 1 means nothing changed: no account has that address, or its link was already
used, superseded or expired.

### CA-SHP-10 — a booking late in the evening, Toronto time

The seed gives `STCA-000001` a second **non-demo** shipment, booking reference
`UAT-CA-SHP-10`, booked at **23:30 Toronto time ten local days before the reset**. In UTC
that is 03:30 (summer) or 04:30 (winter) on the *next* date, which is what makes the case
able to tell a local-day filter from a UTC-day one. Link the tester's account to
`STCA-000001` at approval and it appears on `/account/shipments`; the booked date on screen
is the Toronto date. `--check` reports it:

```
  ok      late-evening Toronto booking for the first customer  1   (CA-SHP-10: 23:30 Toronto time, stored on the next UTC date)
```

The date moves with every reset, because it is counted back from the day the seed ran.
Read the shipment's booked date on the Staff Portal before filtering.

---

## 3c. Registration closed — CA-REG-09

`CA-REG-09` needs registration **gated**, the way production is while no email provider is
selected (OD-34). Production cannot be reproduced locally — it refuses to start on the UAT
database's reserved-domain accounts, by design — so the backend has a setting that applies
the production gate, and nothing else of production, outside production:
`ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER=true`. With it, registration, resend and password
reset answer `503` and the Customer Account shows **Accounts are not open yet**; sign-in
and every Staff Portal and Public Tracking screen keep working. It can only close
registration, never open it, and its default is `false`.

### Switch to it

Stop the backend (`Ctrl+C`) and start it again with the setting added. The rest of the
command is the section 3a one, unchanged:

```bash
DATABASE_URL="sqlite:///$PWD/data/uat/solaris_uat.uat.db" ENVIRONMENT=development \
  ACCOUNT_EMAIL_TRANSPORT=capture ACCOUNT_EMAIL_CAPTURE_DIR="$PWD/data/uat/account_mail" \
  ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER=true \
  backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000 --app-dir backend --no-proxy-headers
```

In PowerShell, set it on its own line before starting, and remove it afterwards:

```powershell
$env:ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER = "true"
```

The frontend needs no restart. Confirm it took effect before testing — this prints `503`:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Content-Type: application/json" \
  -d '{"email":"probe@example.com"}' http://127.0.0.1:8000/api/v1/account/password/forgot
```

### Switch back

Stop the backend and start it with the **section 3a command exactly as written**, without
the setting. In PowerShell, clear it first:

```powershell
Remove-Item Env:ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER
```

The same `curl` now prints `200`. Every other `CA-REG-*` case needs registration open, so
switch back before running any of them — and run `CA-REG-09` last, or on its own. Nothing
is written to the database while the gate is closed, so no reset is needed in either
direction.

---

## 3d. The workers, run once (`--once`)

Four background workers exist. None runs by itself in UAT; run one when a case says so,
in a third window, with the **same** `DATABASE_URL`, `ENVIRONMENT`,
`ACCOUNT_EMAIL_TRANSPORT`, `ACCOUNT_EMAIL_CAPTURE_DIR` and `TARIFF_INTAKE_DIR` as the
backend (`HOW_TO_RUN.md` §5 has them ready to paste). Each processes what is waiting and
exits.

| Worker | Command (from `backend/`) | In UAT |
|---|---|---|
| Milestone emails | `.venv/Scripts/python -m app.workers.notification_worker --once` | Sends anything still **Queued** in Settings → Customer notifications to the capture folder. A milestone recorded on a screen is normally sent at once; the worker picks up what was not |
| Vendor rate emails | `.venv/Scripts/python -m app.workers.tariff_intake_worker --once` | Reads every `*.eml` in `data/uat/tariff_intake/`, then moves it to `processed/` or `failed/`. Copies of the two seeded emails are in `samples/` |
| Exchange rate | `.venv/Scripts/python -m app.workers.fx_worker --once` | **Do not run it in UAT.** It calls Vietcombank's public rate page, which is an external request. Use `scripts/uat_env.py --refresh-fx` instead (from the repository root): it adds a demo reading, labelled demo, with no network. A reading counts as live for a day, so run it at the start of any session on a later day than the reset |
| Retention (RC-UAT-21) | `.venv/Scripts/python -m app.workers.retention_worker --once --dry-run` | **Dry run only** (`UAT-BLD-17`): prints one line of counts per record class and changes nothing. On the portable package, from its folder: `powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\uat\env.ps1; .venv\Scripts\python -m app.workers.retention_worker --once --dry-run"`. Retention deletion is **off** on every reset and must stay off: never type the enabling phrase in **Settings → Retention** (periods undecided, OD-01, OD-36; owner approval required). There is no scheduler |

The import templates (customers, shipments, legacy history) are in
`artifacts/sample-imports/`; copy one outside the repository before editing it, so nothing new
appears in `git status`.

---

## 4. Reset between runs

**If a reset fails part-way** (it prints a traceback and does not end with "Every required
category is present"), run `--reset` again. A half-built database is not repaired by a
second run of the air dataset, which skips once its first master exists. `--path` may name
another `.uat.db` file only directly inside `data/uat/`; a sub-directory is refused, because
the mail and rate-email folders sit beside the database.


```bash
backend/.venv/Scripts/python scripts/uat_env.py --reset
```

**Reset before each full pass.** The environment is repeatable by construction, and the
staff workflows write rows: bookings, events, imports, merges and suppressions all
accumulate. The reset also deletes every captured Customer Account message in
`data/uat/account_mail`, so no stale verification or password-reset link survives into the
next pass, and the rate-email folder `data/uat/tariff_intake`, which it then fills again
with the two seeded emails. A second pass over an un-reset database is testing a different dataset than
the first, and a case that depended on a record another case changed will fail for a
reason that has nothing to do with the product.

Stop both processes first — SQLite will not let the file be replaced while the backend
holds it open.

To check coverage without rebuilding:

```bash
backend/.venv/Scripts/python scripts/uat_env.py --check
```

---

## 5. Shut down

Stop the frontend, then the backend, with `Ctrl+C` in each terminal. Nothing needs
draining: the integration worker is a separate process that is not part of UAT, and label
PDFs are generated inside the request that asked for them.

Confirm nothing is still listening before you rebuild:

```bash
netstat -ano | grep -E ":8000|:5173|:8010|:5183"
```

---

## 6. Clean up

```bash
backend/.venv/Scripts/python scripts/uat_env.py --destroy
```

Removes the UAT database and its `-wal`/`-shm` files, deletes every captured Customer
Account message and the rate-email intake folder, and removes `data/uat/` if it is then
empty. It will only delete a path that passed every safety check in section 1.

### What must not be committed

`data/` is git-ignored in full, and so is every `*.db`, `*.db-wal` and `*.db-shm`. Before
finishing a UAT session, confirm nothing escaped:

```bash
git status --porcelain
```

Nothing generated during UAT belongs in the repository — not the database, not exported
CSVs, not label PDFs (which encode a tracking URL), not uploaded import files, and not a captured message (each one contains a working
verification or password-reset link).

---

## 7. What this environment cannot show a tester

Recorded here so no case is marked passed against a screen that does not exist.

| | |
|---|---|
| **Return *shipment records*** | **Not implemented, and now an open owner decision (OD-22).** `shipments.is_return` and `return_of_shipment_id` exist in the schema and are read by reports and exports, but nothing in the application sets either one — no service, no schema, no route. The dataset contains no returns because manufacturing the rows would fabricate a feature. Any case that depends on a return **record** is **blocked pending OD-22**, not failed. One consequence a tester will actually see: the shipment-status report's **Returns** row reads `0`, which is correct. As of RC-UAT-3 that row carries **no drill-through link at all** and says so in a short note — the dead `returns_only` link was removed rather than left in an RC handed to human testers. The absent link is deliberate; do not raise it as a defect. See `docs/RETURNS_REQUIREMENT_MATRIX.md`. |
| **Return *statuses*** | **Implemented, and testable.** This is a different thing from the row above. `Return in progress` and `Returned` are recordable shipment events, and they appear on the shipment list filters, the shipment detail page, the exceptions report, and the public tracking page in both English and Vietnamese. Treat them as ordinary states. |
| **Provider synchronization** | Out of scope by DEC-0075. `connected_api` is refused, the adapter registry is empty, both resource allowlists are empty, and integration health is `not_configured`. It is not an available workflow and must not appear in any executed case. |
| **The public help link** | `PUBLIC_HELP_URL` is empty (OD-06), so the "Contact Solaris Express" link is correctly **omitted**. Under the owner-authorised RC-UAT disposition the omission is the behaviour **under test**: confirm the optional link is cleanly absent and record the case as `Pass`, not `Blocked`. The public tracking page must still be usable and must not show a broken, empty, placeholder, or invented contact link. OD-06 remains open for production. |
| **MFA** | Not implemented and not decided (OD-17). Authentication and session cases can be executed, but the security section **cannot be signed off** until the owner decides. If MFA is later added, every authentication and session-expiry case must be re-run. |
| **A real printed label** | No label has ever been printed or scanned. The physical protocol is a separate human gate. |
| **Customer Account profile and notification screens** | **Built** since this table was first written (fix pack 2; Phase 13F). `CA-PRF-01` … `CA-PRF-04` are executable. |
| **A vendor mailbox** | **None is connected** (`19_OWNER_QUESTIONS.md` #11). Rate emails arrive by upload or through the intake folder; that is the behaviour under test, not a gap. |
| **A live exchange rate** | The bank is never called in UAT. Every reading is a demo one, labelled demo; `uat_env.py --refresh-fx` adds one. |
| **Real delivery of Customer Account mail** | The six messages are composed and written to `data/uat/account_mail` as files. **Nothing is sent to any address**, no provider is selected (OD-34), and no production transport exists — selecting one fails at startup on purpose. Whether a real inbox would receive, render or spam-filter these messages is untestable here. |
| **Approved terms and privacy text** | Both versions are placeholders that name themselves as placeholders, and the registration screen says so (OD-37). Do not raise the placeholder as a defect; do raise it if the screen ever stops admitting it. |
| **Vietnamese on the Customer Account** | **Vietnamese first** since OD-71, with an English switch on every screen. No native speaker has reviewed it (`19_OWNER_QUESTIONS.md` #6). |
| **Screen readers** | No screen reader has been run against this application. Automated axe results are not human validation. |

---

## 8. Carrier links in UAT

`PUBLIC_CARRIER_LINK_HOSTS` retains its nine shipped hosts so external-link tracking can be
exercised. This is a **provisional UAT disposition, not production approval** (OD-07).

During testing: exercise allowed carrier-link construction and display, and the rejection
of lookalike, suffix-confusion, user-info, non-HTTPS, malformed, local, private and
unlisted hosts. **Do not navigate to a carrier site, and do not make any external network
request.** Use the synthetic tracking references in the dataset, or the ones `UAT-OWN-23`
and `-24` add (and `UAT-OWN-33`, since RC-UAT-20). Since RC-UAT-19 (OD-91, OD-92) customers
read a link under a generic name, "Master Tracking" or "Last Mile Tracking", never the stored
carrier label; the Vietnamese names "Theo dõi chặng chính" / "Theo dõi chặng cuối" were
approved on 2026-10-23 (OD-104).

The two provider integration resource allowlists remain empty and must stay empty.
