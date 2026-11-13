# Operations

Backups, restore, secret rotation, retention, monitoring, and the gates that must close
before a production release.

**Nothing is deployed.** No hosting, domain, provider account, or paid service has been
purchased or activated. Costs below are marked as unverified where they are estimates.

---

## 1. Backup

SQLite in WAL mode keeps recently committed data partly in the `-wal` file, so copying
`solaris_crm.db` with `cp` while the application runs can produce a torn or stale
database. Always use the online backup API.

From the repository root:

```bash
python scripts/backup_db.py --keep 30
```

The script opens the source read-only, uses `sqlite3.Connection.backup`, then runs
`PRAGMA integrity_check` on the copy and deletes it if the check fails. A backup that
does not report `integrity_check ok` did not happen.

Recommended schedule once deployed: hourly during business hours and nightly otherwise,
retained 30 days locally plus an off-server copy. `backups/` is git-ignored.

### Restore

1. Stop the application.
2. Move the current database aside — do not delete it: `mv data/solaris_crm.db data/solaris_crm.db.broken`.
3. Copy the chosen backup into place as `data/solaris_crm.db`.
4. Run `python -m alembic upgrade head` from `backend/`.
5. Start the application and verify: sign in, open a customer, confirm the dashboard counts.

**A restore that has never been rehearsed is not a backup.** Rehearsing a restore into a
scratch directory is a production gate (section 6).

---

## 2. Secrets and rotation

Secrets live only in environment variables or a secret store, never in the repository.
`backend/.env` and `frontend/.env` are git-ignored; only `.env.example` placeholders are
committed.

| Secret | Where | Rotation |
|---|---|---|
| `SECRET_KEY` | backend env | Rotate on suspicion of exposure and on staff offboarding with access to it. Not currently used to sign session tokens (sessions are opaque random values stored as digests), so rotation does not invalidate sessions — revoke sessions explicitly. |
| Staff passwords | Argon2 hashes in `users` | Rehashing happens automatically on sign-in when parameters change. Deactivating an account revokes its sessions immediately. |
| Provider credentials (Phase 4) | backend env | Not yet issued. Never returned by the API; the settings UI will show a masked indicator and a rotation action only. |

`get_settings` refuses to start in production when `SECRET_KEY` is the development
default, `COOKIE_SECURE` is false, or `ALLOW_DEMO_SEED` is true.

### Revoking access

- Deactivate a staff account: Settings → Staff and permissions. Sessions are revoked in
  the same transaction, and the change is audited.
- Revoke your own sessions everywhere: `POST /api/v1/auth/revoke-all`.

---

## 3. Monitoring

Phase 1 exposes:

- `GET /health` — liveness, returns the environment name.
- The audit log (`Settings → Audit access`, admin and read-only manager) — every material
  change with actor, action, entity, and a redacted detail payload.

Not yet built: structured log shipping, uptime alerting, error tracking, and the
integration-health panel (Phase 4, which needs a real provider connection to be honest).

What to watch once deployed:

| Signal | Why |
|---|---|
| `database is locked` in logs | Writer contention; the retry helper masks brief spikes but sustained locking means it is time for the PostgreSQL gate |
| Disk free on the database volume | SQLite plus WAL plus backups |
| Failed sign-ins per IP and per email | The limiter is in-process; a spike still deserves a look |
| Backup job exit status | A silent backup failure is the classic root cause of a bad restore |
| `shipment.confirm` audit entries with a high `id_generation_attempts` | One or two is normal. A sustained rise would mean the identifier space is being exhausted, which at 32^12 would be extraordinary and worth investigating rather than ignoring |
| `shipment.label_generate` volume | Labels are generated inside the request; an unexpected spike is worth a look before it becomes a latency complaint |

---

## 4. Retention and privacy

`CRM.md` section 11 requires configurable retention guidance, restricted export, and a
documented access, correction, and deletion process.

**Implemented now**

- Consent history is append-only; suppression is global to a channel and address and
  survives merges and re-imports.
- Suppression release is admin-only and audited.
- Archiving hides a customer without touching shipment history; `ON DELETE RESTRICT` on
  `shipments.customer_id` prevents cascade deletion.
- Exports are permission-gated, audited, and escape spreadsheet formula injection.
- Audit entries redact secrets (`[redacted]`) and personal values (`[changed]`).
- The CRM does not collect birthdates, identity documents, or payment card details.
- Shipment address snapshots are copies taken at booking time, so a correction to the
  address book does not silently rewrite shipping history — and an access request must
  therefore cover both the address book and the shipments.
- A cancelled shipment keeps its Solaris ID and its snapshots. That is deliberate: the ID
  may be on paperwork a carrier or customer still holds, and reusing it would make two
  different parcels answer to one identifier.

**Process to follow (manual until a retention job exists)**

1. *Access request.* Export the customer record and its interactions, tasks, consent
   history, and shipments. Do not include internal notes about other customers.
2. *Correction request.* Edit the record. The change is audited.
3. *Deletion request.* Archive first. Before deleting anything, confirm which records must
   be retained for tax, customs, or carrier-dispute reasons — that retention period is a
   **business and legal decision that has not yet been made**, and the CRM does not assume
   one. Suppression entries should survive a deletion so the address is not re-contacted.

**Not built:** automated retention expiry, a self-service data-subject request flow, and
any CASL-specific legal logic. `CRM.md` section 11 is explicit that legal conclusions must
not be guessed; verify against official CRTC guidance before campaigns are implemented.

---


## 4a. Label printing operations

Labels are generated on demand by the API and streamed as a PDF. Nothing is stored, and
generation is deterministic — regenerating the same packages produces byte-identical
output, which is why the recorded `document_sha256` is a usable check that a reprint is
the same label.

**What the system knows.** That a PDF was generated and downloaded, by whom, for which
package references, and whether it was a reprint. `label_print_jobs` records this.

**What the system does not know.** Whether a printer produced anything. No print system
reports back, so no page of this documentation, no audit entry, and no screen says a label
was printed.

**Print settings that matter.** 4 × 6 in, portrait, 100% scale, browser headers and
footers off. "Fit to page" shrinks the barcode below the module width it was designed for
and is the most likely cause of a label that will not scan.

**The embedded font.** `backend/app/assets/fonts/` holds Roboto Regular and Bold under the
Apache License 2.0, with provenance and SHA-256 digests in the README beside them. They are
embedded in every PDF because Vietnamese diacritics would otherwise print as blank boxes.
Replacing them requires re-running `backend/tests/test_labels.py`, which asserts the
codepoint coverage.

**Regenerating the samples.** From the repository root:

```bash
python scripts/render_sample_labels.py
```

This writes `artifacts/sample-labels/*.pdf` and reports page geometry plus, when the
optional `verify` extra is installed, the decoded barcode and QR payloads at 203 and
300 dpi. It says explicitly when decoding was not attempted rather than passing quietly.

---

## 5. Scaling: when to leave SQLite

SQLite here is a **single-server** architecture. Do not run multiple independently
writing application replicas against a database file, and never place it on shared
network storage.

Move to PostgreSQL when any of these becomes true:

| Threshold | Reason |
|---|---|
| More than one application process needs to write | SQLite has a single writer; WAL does not change that |
| A second **integration worker** is needed | Same reason. The job claim is correct under concurrency and has been demonstrated under two sessions on separate connections — **not** under two processes, and this project does not claim it (section 9) |
| Sustained `database is locked` retries under normal load | Writer contention is no longer brief |
| High availability or failover is required | A single file on a single host cannot provide it |
| Horizontal scaling or a second region is planned | Same |
| Analytical queries start to interfere with operational writes | Read replicas are the answer, and SQLite has none |

The migration is kept practical: no PostgreSQL-only column types, no SQLite-only SQL in
service code (the dashboard buckets dates in Python for exactly this reason), Alembic
migrations for all schema changes, and connection setup isolated in `app/core/db.py`.

Also required before horizontal scaling: move rate limiting out of process memory
(DEC-0006) and decide how sessions are shared, which they already are — sessions live in
the database, not in memory.

---

## 6. Production gates

None of these are closed. Each must be verified, not assumed.

**Infrastructure**

- [ ] Hosting chosen and costs confirmed with the provider. No costs are quoted here.
- [ ] TLS terminated; `COOKIE_SECURE=true`; `SameSite` reviewed for the final domain layout
- [ ] `SECRET_KEY` generated and stored in a secret store
- [ ] `CORS_ORIGINS` set to the exact production origin
- [ ] `ALLOW_DEMO_SEED=false` and the production database confirmed to contain no `is_demo_record` rows
- [ ] Reverse proxy chosen; the ASGI server told to trust **only that proxy's** address, and `TRUST_PROXY_HEADERS=true` set. Both halves or neither (DEC-0007, DEC-0048)
- [ ] Server started with `--no-proxy-headers` until that is done (DEC-0048)
- [ ] **Reverse-proxy access logs redact the tracking reference from the request path** (DEC-0057, section 8)
- [x] Fonts self-hosted rather than fetched from Google Fonts — done in Phase 3 (DEC-0020, DEC-0046)
- [ ] Database volume backed up off-server; **a restore rehearsed end to end**

**Application**

- [ ] Rate limiting moved to a shared store if more than one process runs (DEC-0006)
- [ ] Real staff accounts created; every demo account removed
- [ ] MFA evaluated — `CRM.md` section 11 prefers MFA-capable authentication and it is not built
- [ ] Lifecycle thresholds and role assignments confirmed by the owner (DEC-0008, DEC-0015, DEC-0016)

**Phase-dependent**

- [ ] **Phase 10 — Admin reinstatement of a rejected account.** `STATE_MACHINES.md`
      transition 9 exists and no route reaches it, so a rejected applicant has no path back
      other than a database change. Not a permanent ban by design; a gap by scope. Decide
      whether release 1 needs it.
- [ ] **Phase 10 — suspend, reinstate and deactivate have no route.** The services exist
      from Phase 9 and are still routeless, so suspending a live account during an incident
      is a database change today (`DATA_MODEL.md` section 8 permissions 3 to 5).
- [x] **Phase 10 — a merged customer keeps its account link.** Closed on 2026-09-20 by
      **OD-40**: the merge is refused outright while either side holds an active link, with
      the conflict code `customer_account_link_present`. The definition of an effective link
      is `app/services/customer_account_link_policy.py`; the guard is central, in
      `customer_service.merge_customers`.
- [ ] **Phase 10 — no merge-with-account reconciliation workflow.** The consequence of
      OD-40: a duplicate involving an account holder **cannot be merged at all** until a
      workflow exists that does a fresh duplicate review, shows a disclosure preview, takes
      an acknowledgement, handles the session and makes an explicit owner-approved link
      transition. Staff hitting this see a conflict that names which side blocked; there is
      no operational workaround short of the owner deciding to revoke the link first, and
      no route exists to do that either. OD-40 defers the workflow to a later phase.
- [ ] **Phase 10 — no Staff Portal screen.** The approval queue is API-only. Phase 12 builds
      the screen; until then approving an account means calling the API.
- [ ] **Phase 2 — physical label print and scan.** The generated PDFs are verified in
      software: exact 288 × 432 pt pages, and both the Code 128 and the QR decode from a
      rasterized page at 203 and 300 dpi. **No label has been printed or scanned on real
      hardware.** Before launch, print `artifacts/sample-labels/*.pdf` at 100% scale on
      the actual thermal printer and scan every symbol with the actual handheld, including
      the long-Vietnamese-name sample. Software decoding is evidence that the symbols are
      well formed; it is not evidence that the printer reproduces them.
- [ ] **Phase 2 — confirm the tracking base URL.** `TRACKING_BASE_URL` currently points at
      a development host, so the QR codes on any label printed today point there. The
      proposed `track.solarisexpress.ca` does not exist. Set this before printing labels
      that reach a customer.
- [ ] **Phase 2 — confirm the label branding.** The label prints a text wordmark. Replace
      it with an approved asset at `backend/app/assets/brand/solaris-logo.png` when one
      exists; the layout already uses it automatically if the file is present.
- [x] **Phase 3 — public tracking privacy, rate limits, and no-index.** Verified in software:
      69 live public responses inspected recursively against 105 private values read out of
      the demo database, with no forbidden field name and no leaked value; invalid and
      unknown references returning byte-identical bodies and headers; the rate limit
      engaging with `Retry-After` and surviving a forged forwarded header; `no-store`,
      `no-referrer`, and `noindex` on every public response including failures; no
      third-party request from the page. **Still open below.**
- [ ] **Phase 3 — confirm the public help/contact URL.** `PUBLIC_HELP_URL` is empty, so the
      page shows no contact link at all. An exception callout currently tells a customer to
      contact Solaris Express without giving them a way to do it.
- [ ] **Phase 3 — confirm the public carrier-link allowlist.** `PUBLIC_CARRIER_LINK_HOSTS`
      ships nine plausible carrier hosts that nobody has reviewed. Check each one is the
      host that carrier actually serves public tracking from.
- [ ] **Phase 3 — review the public copy.** Both catalogues were written by the
      implementation, not by the business. The Vietnamese in particular should be read by a
      native speaker who knows how Solaris talks to its customers.
- [ ] **Phase 3 — decide whether staff must write public updates in Vietnamese** for
      Vietnamese-speaking customers. Update text is shown verbatim and is not translated
      (DEC-0054).
- [ ] Phase 4: ShipStation product, version, entitlements, and webhook types verified against current official documentation, with a real test event received or fetched. **Do not describe the integration as live until that happens.**
- [ ] **Phase 9 — select a production email provider (OD-34).** No provider is selected and
      no adapter is written. `ACCOUNT_EMAIL_TRANSPORT=production` **fails at startup** because
      there is nothing behind it, and `=capture` fails at startup in production because it
      would write verification links to a directory while customers waited for mail. With
      neither, `/api/v1/account/register`, `/verification/resend` and `/password/forgot`
      refuse at the route with a 503. Selecting one needs: verified provider documentation,
      data residency confirmed, the sending domain authenticated (SPF, DKIM, DMARC), bounce
      and complaint handling defined, and credentials in a secret store named by
      `credential_ref`. **Customer registration cannot launch until this is closed.**
- [ ] **Phase 9 — supply approved terms and privacy text with version identifiers (OD-37).**
      `ACCOUNT_TERMS_VERSION` and `ACCOUNT_PRIVACY_VERSION` ship as values that name
      themselves placeholders, and production registration refuses while either still does.
      An acknowledgement recorded against a placeholder is an acknowledgement of nothing.
      **Customer registration cannot launch until this is closed.**
- [ ] **Phase 9 — review the customer-facing English copy (OD-39).** The four account
      messages and every generic security sentence were written by the implementation, not by
      the business. They are the wording that must not disclose, so they need reading with
      that in mind. Vietnamese customer-account wording stays **disabled** until a qualified
      reviewer approves the UI, the verification and reset messages, the privacy and terms
      wording, and the operational notification wording.
- [ ] **Phase 9 — customer rate limits tuned against real traffic.** The values in
      `ACCOUNT_*_ATTEMPTS` are starting points, not measurements. They are configuration
      rather than constants so they can move without a release.
- [ ] **Phase 9 — the capture directory is not served and must not become served.** Captured
      mail contains live verification and reset links in plaintext. It lives under the
      git-ignored development data directory, no HTTP route returns it, and a test walks the
      whole route table to keep it that way. If a deployment ever puts a static file server
      in front of the data directory, that test stops being the whole control.

---

## 7. Proposed hosting requirements

Requirements only. Nothing has been selected, priced, or purchased.

| Need | Note |
|---|---|
| Application host | One small Linux instance runs both processes. Persistent disk is mandatory — ephemeral filesystems lose the database. |
| Database | The SQLite file on that persistent disk. No managed database service until the PostgreSQL gate. |
| Worker | Phase 4 adds one low-volume worker process on the same host. |
| Object storage | Not needed. Label PDFs are generated on demand inside the request and streamed; nothing is stored. Generation is deterministic, so a reprint reproduces the same bytes. |
| Email | Not needed in Phase 1; no messages are sent. Operational email is a later decision. |
| Tracking provider | Phase 4. Entitlements and cost must be verified against the actual account. |
| TLS and domain | The proposed `track.solarisexpress.ca` host does **not** exist yet and must not be assumed. |

Verify every cost with the provider before quoting it to the business. Do not promise a
free production system.

---

## 8. Running the public tracking page (Phase 3)

The public page shares one process and one build with the staff portal. It has its own
API prefix, its own rate-limit buckets, and its own response headers.

### The run command, and why the flags are not optional

```bash
python -m uvicorn app.main:app --port 8000 --app-dir backend --no-proxy-headers
```

**`--no-proxy-headers` is load-bearing.** Uvicorn enables `--proxy-headers` by default and
trusts `127.0.0.1`, which means it rewrites the peer address from `X-Forwarded-For` before
the application sees it. Without this flag, anyone who can reach the server on loopback
gets a fresh public rate-limit bucket per request by changing one header — which is to
say, no rate limit.

The application defends itself as well as being run correctly (DEC-0048): while
`TRUST_PROXY_HEADERS` is false, every request carrying a forwarding header shares one
bucket, so the limit holds whatever the server did to the scope. Both mechanisms should be
in place. Neither is a substitute for the other.

### Public configuration

| Setting | Default | Notes |
|---|---|---|
| `PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS` | `30` | Per client key, per window |
| `PUBLIC_TRACKING_RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window |
| `TRUST_PROXY_HEADERS` | `false` | See above. Change only with the proxy configured |
| `PUBLIC_HELP_URL` | *(empty)* | Empty means the contact link is omitted, never invented |
| `PUBLIC_CARRIER_LINK_HOSTS` | nine carrier hosts | Empty means no carrier link is ever shown |
| `TRACKING_BASE_URL` | `http://localhost:5173/track` | What the label QR encodes. **The path must stay `/track`** |

### Rate limiting: what it is and what it is not

The public limiter is a sliding window in **process memory**, keyed by the directly
observed client address (or the shared forwarded bucket). Its buckets are pruned on an
amortized sweep and capped at 20,000 entries, because the public key space is "every
address that has ever called" and an unbounded dictionary would grow for the life of the
process (DEC-0056).

**It is suitable only for the documented single-process deployment.**

| Limitation | Consequence | Gate |
|---|---|---|
| Per-process counters | Two workers means two allowances; N workers means N times the limit | Move to a shared store before running more than one worker |
| Resets on restart | A restart clears every bucket | Acceptable at this scale; note it when reading abuse metrics |
| Keyed by address | A NAT or a campus shares one bucket | Watch for legitimate users being limited before raising the number |

Public buckets are prefixed `public_track:ip:` and are **separate from** `login:ip:` and
`login:email:`, so a busy tracking page cannot consume a staff member's sign-in allowance
and a login attack cannot lock customers out of checking their parcels.

### Access-log redaction — a production requirement, not a suggestion

A tracking reference travels in the request **path**:

```text
GET /api/v1/public/track/SX-CAV-7K9D2M4R8T6W-01
```

The application never writes that reference to a log. It records an outcome category and a
keyed HMAC digest instead (DEC-0057). **A reverse proxy will write the full path to its
access log by default**, and that log is often shipped somewhere and retained for months.
A tracking reference is privacy-sensitive (`CRM.md` section 10), so the proxy must be
configured to redact it before the application is exposed.

nginx, for example:

```nginx
# Replace the reference in the logged path with a placeholder.
map $request_uri $safe_request_uri {
    "~^(?<prefix>/api/v1/public/track/).*$"  "${prefix}[redacted]";
    default                                   $request_uri;
}

log_format solaris '$remote_addr - $remote_user [$time_local] '
                   '"$request_method $safe_request_uri $server_protocol" '
                   '$status $body_bytes_sent "$http_referer" "$http_user_agent"';

access_log /var/log/nginx/solaris.log solaris;
```

The same applies to any CDN, load balancer, or WAF in front of the application, and to
anything that samples request URLs for metrics. Whatever sits in front of this
application, check what it does with the path before pointing a customer at it.

### Public response headers

Set by the route handler and repeated by middleware for every response under
`/api/v1/public`, including failures raised before the handler runs:

| Header | Value | Why |
|---|---|---|
| `Cache-Control` | `no-store, no-cache, must-revalidate, private` | A tracking result must not sit in a shared or browser cache |
| `Pragma` | `no-cache` | For older intermediaries |
| `Referrer-Policy` | `no-referrer` | The URL contains the reference; it must not travel to any link the customer follows |
| `X-Robots-Tag` | `noindex, nofollow, noarchive` | Tracking results must never be indexed |
| `X-Content-Type-Options` | `nosniff` | |
| `X-Frame-Options` | `DENY` | |
| `Permissions-Policy` | `geolocation=(), camera=(), microphone=(), interest-cohort=()` | The page needs none of these |

`index.html` additionally carries `noindex, nofollow, noarchive` and `no-referrer` meta
tags, and a constant document title that never contains a reference.

**No `Set-Cookie` is ever issued on a public response**, and the browser sends none: the
public fetch uses `credentials: 'omit'`, so a signed-in staff member opening the tracking
page in the same browser does not send their session with it.

### Third-party resources: none

Neither shell requests anything from another host. Poppins and Inter are self-hosted under
`/fonts` (DEC-0046). There is no analytics, no error tracker, no social widget, no
advertising pixel, and no embedded map. A tracking reference is never placed in an
analytics payload because there is no analytics.

This is enforced rather than intended: a unit test fails if `index.html` regains any
absolute `http(s)` URL, and the end-to-end suite records every browser request and fails
on any non-first-party host.

### Demo data on the public page

A demo record returns the same generic not-found response in production
(`ENVIRONMENT=production`), so a synthetic row can never be mistaken for real tracking. In
development it returns `data_mode: "demo"` and the page shows a persistent warning.

### Running the end-to-end suite

**One command. There is no second step and no variable to remember.**

```bash
npm run e2e --prefix frontend
```

That is `frontend/scripts/run_e2e.mjs`, and it owns the whole run (DEC-0112). It mints a
random run identifier, builds an isolated database at `data/e2e/<id>/solaris.e2e.db`,
migrates and seeds it, starts a backend and a Vite dev server that belong to that database
alone, passes both origins explicitly, applies the rate limits below, runs Playwright, and
removes everything it created. A failed run keeps its own directory and prints the path.

**Do not run `playwright test` directly.** It used to be the documented second step, and on
2026-09-20 it wrote 314 rows into `data/solaris_crm.db` across four runs: the suite opened
`http://localhost:5173`, a development backend was already listening there, and the staff
specs wrote into whatever database that backend was serving. The suite now refuses to start
without proof that the backend belongs to this run -- `tests/e2e/globalSetup.js` presents the
run identifier and `app.api.e2e` confirms it against both its own environment and a marker
row inside the database it is serving -- so the mistake fails loudly instead of succeeding
quietly. `docs/incidents/2026-09-20-e2e-wrote-to-the-development-database.md` is the record.

#### What the harness guarantees

| | |
|---|---|
| **Database** | A fresh `.e2e.db` per run, inside `data/e2e/` and nowhere else. The backend refuses at startup to serve the development database, the UAT database, a backup, a production path, or anything resolving outside that directory -- symlinks and Windows junctions are resolved *before* the check (`app.core.e2e_guard`). |
| **Process** | A backend and dev server this run started. An occupied port is a clear failure or a controlled move to another port, never a silent reuse of whatever is listening. |
| **Rate limits** | `PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS=200` and `LOGIN_RATE_LIMIT_ATTEMPTS=100`, applied automatically by `scripts/e2e_env.py`. No application default changes, and nothing is written to a `.env`. |
| **Proxy headers** | `--no-proxy-headers`, plus `TRUST_PROXY_HEADERS=false` and an empty `TRUSTED_PROXY_HOSTS` (DEC-0048), so no test can choose its own limiter bucket. |
| **Artifacts** | Traces, screenshots, diagnostics and both process logs land in the run's own directory under `data/`, which `.gitignore` excludes at any depth. |
| **Cleanup** | A passing run removes its own directory and nothing else. A failing run keeps its own and names it. |

The limits are not a weakening. The suite runs entirely from loopback against a
process-local limiter, so one browser project replaying a few dozen tracking lookups
exhausts a production-sized window and the next project's assertions fail as "element not
found" -- which is really "Too many lookups". About five public-tracking tests failed that
way before this was applied automatically. The tests that exist to *exercise* the limiter --
`zzRateLimit.spec.js` and the backend's `test_account_rate_limits.py` -- still set their own
explicit values against a window they chose, so the staff and Customer Account limiters stay
independently testable.

#### When a run fails

The directory it names holds the scratch database, both process logs, and Playwright's
traces and screenshots. It is synthetic data only. Remove it when you are done:

```bash
backend/.venv/Scripts/python scripts/e2e_env.py --destroy --run-id <the id it printed>
```

`--list` shows every preserved run and its size. Nothing else removes them, and nothing
sweeps the directory automatically -- another run's evidence is not this run's to delete.

#### Options

* `E2E_OCCUPIED_PORT_POLICY=fail` -- stop rather than move to another port. Set this in CI,
  so a port collision is a red build rather than a quietly different run.
* `npm run e2e --prefix frontend -- --project=staff` -- everything after `--` is passed to
  Playwright unchanged.

The rate-limit spec deliberately exhausts the limiter and runs last, in its own Playwright
project. A global setup waits for the window to drain before the first test, so a run
started soon after another one does not begin against a consumed window.

Screenshots are a separate script and assert nothing:

```bash
node frontend/scripts/capture_public_screenshots.mjs
```

---

## 9. The integration worker (Phase 4A)

**No provider is connected, so there is nothing for the worker to do.** A pass against a
production installation reclaims nothing, claims nothing, and reports that. Run it anyway
if you like — it is safe, bounded, and honest — but it is not yet part of the operating
routine, and **no unattended service was started during this build**.

> **Deferred by owner decision (DEC-0075, 2026-09-10).** Provider synchronization is
> scheduled for the final phase of the project. Until then the worker stays out of the
> operating routine by design rather than by omission: there is no provider to poll, the
> resource allowlist is empty, and the health panel reports `not_configured`. Nothing in
> this section needs to change when the deferral ends — the worker was built
> provider-neutral and is already correct. See `docs/INTEGRATIONS.md` section 10.

### One bounded pass

```bash
backend/.venv/Scripts/python -m app.workers.integration_worker --once
```

Options: `--batch-size N` (default `INTEGRATION_WORKER_BATCH_SIZE`, 20), `--worker-name`
(default `integration-worker-1`).

`--once` is the deterministic mode: it reclaims expired leases, claims up to the batch
size, runs each job, writes a heartbeat, and exits with status 0. It is what the tests and
this runbook use, and it is the right shape for a scheduled task.

Expected output on an installation with no provider:

```text
integration_worker pass_complete claimed=0 succeeded=0 failed=0 reclaimed=0
```

### Continuous mode, and shutting it down

```bash
backend/.venv/Scripts/python -m app.workers.integration_worker --poll-seconds 15
```

Continuous mode loops, sleeping `--poll-seconds` when it finds nothing. It installs
handlers for `SIGINT` and `SIGTERM` and **finishes the job in hand before exiting**, then
writes a heartbeat with `stopped_at` set — so a stopped worker is distinguishable from a
dead one in the health panel.

Killing it mid-job is survivable: the lease expires and the next worker reclaims the job.
Survivable is not the same as clean, though, and an operator restarting a worker should not
have to wait out a lease to know the queue is idle.

### Run exactly one worker

SQLite is single-writer. The claim is correct under concurrency — a conditional `UPDATE`
whose `WHERE` clause is the guard, evaluated by the database — and it has been demonstrated
under **two sessions on separate connections**. It has **not** been demonstrated under two
operating-system processes, and this project does not claim it.

Two workers against one database file would serialize on the write lock and mostly work;
"mostly" is not a basis for a production decision. **Run one.** Running more is a gate that
belongs with the move to PostgreSQL in section 5.

### What to watch

| Signal | Where | What it means |
|---|---|---|
| `oldest_pending_job_age_seconds` | health API, Settings panel | **The number that reveals a stopped worker.** Pending counts look the same whether work is flowing or frozen; this does not |
| `jobs_requiring_review` | same | Terminal failures waiting for a person |
| `inbox_awaiting_verification` | same | Unsigned notifications waiting for an authenticated read |
| `inbox_rejected` | same | Deliveries refused on arrival: oversized, wrong content type, unparseable, or **forged** |
| worker heartbeat | same | Absent means no worker has ever run. Not an error today |

### Failed-job review

A job that fails terminally sets `requires_review` and releases its deduplication claim, so
it does not block a later legitimate enqueue. Review it in Settings →
**Integration infrastructure**, or through `GET /api/v1/integrations/jobs?review_only=true`.

An operator retry (`integration:manage`) is **audited**, adds exactly one attempt, and
**preserves the failure history**: `attempt_count` keeps counting, the error code and
summary stay until the next attempt overwrites them, and `manual_retry_count` records that
a person intervened. A retry that wiped the history would make the second failure look
like the first.

A retry buys one attempt, not a fresh automatic loop. A person deciding to try again is a
reason to try once.

### Backoff and `Retry-After`

| Failure | Behaviour |
|---|---|
| Retryable — timeout, connection reset, server error | Exponential backoff with **full jitter**, `INTEGRATION_RETRY_BASE_SECONDS` (30) doubling to `INTEGRATION_RETRY_MAX_SECONDS` (3600) |
| Rate limited | The provider's `Retry-After` used **exactly**, bounded by the same ceiling |
| Authentication | Bounded to `INTEGRATION_AUTH_MAX_ATTEMPTS` (2), then terminal |
| Malformed payload, mapping, permanent | **Terminal on the first attempt** |

Full jitter rather than none, because otherwise every failed job retries in lockstep and a
provider that has just come back up is hit by the whole backlog at once. A provider
`Retry-After` is not jittered: the provider said when to come back.

**A failed refresh never replaces a known status with "unknown".** Nothing is written on
the failure path, so a delivered parcel stays delivered through an outage.

### What reaches a log

Job id, job type, provider key, attempt count, outcome, error **category**, worker name.
Nothing else. No payload, no credential, no tracking reference, no customer detail, and no
complete provider URL — a URL keeps only its scheme, host, and a digest.

`error_code` is always an application category (`retryable`, `rate_limited`,
`authentication`, `malformed_payload`, `mapping`, `permanent`), never a provider status
code. `error_summary` is a short phrase the adapter chose, redacted again on the way to the
database.

If a log line ever contains a tracking reference or a secret, that is a bug, and
`backend/tests/test_integration_privacy.py` is where to add the case that catches it.

### Configuration

None of these configures a provider; they are the bounds the infrastructure operates
under. **A missing API key never prevents the CRM from starting** (`CRM.md` section 3), and
nothing here is required.

| Variable | Default | Purpose |
|---|---:|---|
| `INTEGRATION_WEBHOOK_MAX_BYTES` | 262144 | Larger deliveries are **refused**, and stored as a digest with no body |
| `INTEGRATION_WEBHOOK_CONTENT_TYPES` | `application/json` | Anything else is rejected rather than parsed |
| `INTEGRATION_JOB_LEASE_SECONDS` | 300 | How long a worker may hold a job before the lease can be reclaimed |
| `INTEGRATION_JOB_MAX_ATTEMPTS` | 5 | Before a retryable job reaches the review queue |
| `INTEGRATION_AUTH_MAX_ATTEMPTS` | 2 | Deliberately far lower |
| `INTEGRATION_RETRY_BASE_SECONDS` | 30 | First backoff step |
| `INTEGRATION_RETRY_MAX_SECONDS` | 3600 | Backoff ceiling, and the cap on a provider `Retry-After` |
| `INTEGRATION_WORKER_BATCH_SIZE` | 20 | Jobs per pass |
| `INTEGRATION_WORKER_POLL_SECONDS` | 15 | Continuous-mode sleep |
| `INTEGRATION_RESOURCE_ALLOWED_HOSTS` | **empty** | Hosts a provider resource URL may use. **Keep empty until documentation and the account confirm them** |
| `INTEGRATION_RESOURCE_ALLOWED_PATH_PREFIXES` | **empty** | Same |

An empty resource allowlist means nothing is ever fetched, which is the correct behaviour
for a provider nobody has verified. A test fails if a guess is added.

### Seeing it work

```bash
backend/.venv/Scripts/python scripts/integration_worker_demo.py
```

Seven scenarios against a deterministic **fake** adapter and throwaway scratch databases: a
verified notification applied, a duplicate producing no second effect, a forged event
refused, an unsigned notification answered by an authenticated read rather than believed, a
provider outage leaving a delivered parcel delivered, a crashed worker's lease reclaimed,
and a pass with no adapter configured.

The adapter is `tests.fakes.FakeProviderAdapter`. Its provider key is `fake`, its statuses
are invented words no carrier uses, and **it is not ShipStation**. The production registry
is untouched and stays empty.

### Supervision: prepared, not activated (Phase 5B)

**No unattended service was started, installed, or enabled.** `deploy/` holds two systemd
unit **templates**, both disabled, both full of `@PLACEHOLDER@` values, neither installed.

They are templates rather than units for three reasons: no production host has been
chosen, so claiming systemd compatibility would be claiming something nobody has decided;
they contain no credentials and no machine-specific paths, so they cannot run unedited by
design; and there is nothing for the worker to do until a provider is verified, so
supervising it now would mean running a service whose correct behaviour is to do nothing.

| Question | Answer |
|---|---|
| **Exact command** | `backend/.venv/bin/python -m app.workers.integration_worker --poll-seconds 15 --worker-name <name>` |
| **One worker only** | SQLite has a single writer. The claim is correct under concurrency and demonstrated under two *sessions*; **not** under two *processes*, and this project does not claim it. The templates deliberately avoid systemd's instantiated (`@.service`) form, which is how a second worker starts by accident |
| **Startup ordering** | `After=solaris-crm-api.service`, as ordering only. The worker claims jobs from the database, not from the application process, so it is safe to start in either order |
| **Restart behaviour** | `Restart=on-failure`, `RestartSec=30`, bounded by `StartLimitBurst=5` in 600 s. Bounded on purpose: a configuration error will never resolve itself, and an unbounded loop turns a readable failure into a blur |
| **Graceful shutdown** | `SIGTERM`; the worker finishes the job in hand, then writes a heartbeat with `stopped_at` set. `TimeoutStopSec=120` is generous because killing it mid-job, while survivable, is not clean |
| **Lease expectations** | A claimed job carries a lease of `INTEGRATION_JOB_LEASE_SECONDS` (300 s). A crashed worker's job is reclaimed after it expires — survivable, but an operator should not have to wait out a lease to know the queue is idle |
| **Heartbeat expectations** | Written every pass. Absent means no worker has ever run — **not an error today**. A heartbeat with `stopped_at` is a clean stop, which is why it exists |
| **Detecting a stuck worker** | `oldest_pending_job_age_seconds`. Pending *counts* look identical whether work is flowing or frozen; the age does not |
| **Detecting a duplicate worker** | More than one distinct `worker_name` heartbeating. Also suspect it when leases are being reclaimed repeatedly |
| **One bounded pass** | `--once` — reclaims, claims up to the batch size, runs, writes a heartbeat, exits 0. Deterministic, and the right shape for a scheduled task |
| **Stopping safely** | `systemctl stop`, or `SIGTERM`. Never `SIGKILL` unless it has already failed to stop |
| **Inspecting failed work** | `GET /api/v1/integrations/jobs?review_only=true`, or Settings → Integration infrastructure. Both show job id, type, provider key, attempt count and an **error category** — never a payload, a credential, or a tracking reference. Do not go around this by reading the raw row |

**What changes with PostgreSQL or multiple workers.** The one-worker constraint exists
because of SQLite's single writer, not because of the queue design — the claim is a
conditional `UPDATE` and is already correct under concurrency. Moving to PostgreSQL lifts
the constraint, and at that point: run more than one worker, give each a distinct
`--worker-name` so heartbeats stay distinguishable, move rate limiting out of process
memory (DEC-0006), and re-check the lease duration against real provider latency. The
worker code itself needs no change. See `docs/HOSTING.md`.

### Phase 4A production gates

Added to section 6:

| Gate | Status |
|---|---|
| A provider adapter verified against the real account | **Open.** `docs/INTEGRATIONS.md` section 9 lists the nine questions |
| Resource-fetch allowlist filled from documentation | **Open**, and empty on purpose |
| Worker supervised — systemd, a scheduled task, or similar | **Open.** Nothing runs unattended today |
| Worker heartbeat monitored, alerting on `oldest_pending_job_age_seconds` | **Open** |
| One worker only, until PostgreSQL | **Standing constraint** |
| Credentials in a secret store; `credential_ref` names the entry, never the value | **Open** |

---

## 10. Reporting, export, and import (Phase 5A)

### Running the tests and the migration

```bash
# Lint and format the WHOLE repository, from the repository root.
backend/.venv/Scripts/python -m ruff check .
backend/.venv/Scripts/python -m ruff format --check .
cd backend && .venv/Scripts/python -m pytest -q
```

> **Run these from the repository root, not from `backend/`.** Ruff resolves its
> configuration from the checked file's ancestors, and `scripts/` is a sibling of
> `backend/`, not a child. Until Phase 5B's closure review added `ruff.toml` at the root,
> `ruff check scripts` silently used Ruff's **built-in defaults** instead of this
> project's rules — reporting fifteen findings that are not project rules and missing
> several that are. There is now one configuration for every Python file in the
> repository, and nothing is excluded from it.

```bash
# Migrations, always against a scratch database. Never against data/solaris_crm.db.
DATABASE_URL="sqlite:///$TMP/empty.db" backend/.venv/Scripts/python -m alembic upgrade head
DATABASE_URL="sqlite:///$TMP/empty.db" backend/.venv/Scripts/python -m alembic downgrade 9d7dc78dd25c
DATABASE_URL="sqlite:///$TMP/empty.db" backend/.venv/Scripts/python -m alembic upgrade head
```

To rehearse the upgrade against real data, copy the development database **through
SQLite's online backup API** rather than with `cp`. A file copy of a database something
else is writing can be torn; the backup API cannot, and opening the source read-only means
the rehearsal cannot modify the original:

```python
import sqlite3

source = sqlite3.connect("file:data/solaris_crm.db?mode=ro", uri=True)
target = sqlite3.connect("/tmp/rehearsal.db")
source.backup(target)
```

### The end-to-end suite now has staff workflows

The public suite is unchanged. Phase 5A adds a `staff` project covering reports, export,
import preview, import commit, and retry, plus a `staff-setup` project that signs in once —
login is rate limited by client address, and every test arrives from loopback, so signing
in per spec would consume the allowance and fail for a reason unrelated to the code.

Run it with the one command in section 8:

```bash
npm run e2e --prefix frontend
```

**The instructions that used to be here were three commands, two exported variables, and a
`$DEMO_DB` the reader had to set for themselves.** They were correct, and they were followed
most of the time; the four times they were not, the staff specs wrote 314 rows into the
development database. Section 8 now describes a harness that does all of it, and this
section no longer repeats a procedure a person can half-perform.

A `public-drain` project waits for the public rate-limit window between the desktop and
mobile projects. Both replay the same lookups from the same loopback address, so without it
the first exhausts the shared limiter and the second begins against a consumed window. It
weakens nothing: `zzRateLimit.spec.js` still proves the limiter engages.

The staff specs write. That is what they are for, and it is why the harness -- not the
reader -- now decides where.

### Operating the CSV import

An import is staged and only the last step writes. Nothing an operator does before the
confirmation dialog creates, changes, or merges a record, and cancelling is free.

| Stage | Permission | Writes |
|---|---|---|
| Download template | `import:template` | no |
| Field contract | `import:preview` | no |
| Preview a file | `import:preview` + `duplicate:review` | **no** |
| Commit | `import:commit` + `customer:create` | yes |
| Batch history | `import:preview` | no |

**All five are Admin-only today** (DEC-0082). `CRM.md` section 11 does not say who may
bulk-import a customer list, and that is one of two operations that move the whole database
across a boundary in a single action. Widening the permission later is a settings change;
narrowing it after staff have been trained on it is a support incident. The final
Operations and Marketing permission set is an open business decision.

**Limits.** 2 MiB, 5,000 rows, 60 columns, 1,000 characters per cell, 10 seconds of
parsing. Every one is a refusal, never a truncation — a truncated import silently loses
people.

**What is refused, and why the message says so.** Archives and compressed files, `.xlsx`
and legacy `.xls` workbooks, PDFs, images, SQLite databases, files containing NUL bytes,
anything not UTF-8, malformed quoting, and two headings that mean the same field. The check
is on the leading bytes, not the filename.

**Conflict policy.** `skip` leaves an existing record untouched. `fill_blanks` writes only
where a field is empty and audits the field *names*, never the values. There is no
overwrite policy, because nobody reads five hundred rows to notice that one was changed.

**Retry safety.** Idempotency is `(source_system, source_record_id)`, enforced by a unique
index. Importing the same file twice creates the customers once; the second run reports
them as already imported. If the file has no key column, one is derived from the row's
normalized identity.

**Consent is never imported.** There is no code path for it. Imported contact details are
not marketing eligible until consent is recorded in the CRM with its evidence.

**Privacy.** The uploaded file is parsed in memory and never written to disk. The batch
tables hold counts, outcomes, row numbers, and reason codes — no name, email, phone, or
address. The preview audit entry records how many rows were seen and a digest of the file;
the commit audit entry records counts and the conflict choice. No cell value reaches an
audit payload or an application log.

### Operating the exports

| Export | Permission | Also requires |
|---|---|---|
| Customers | `export:customers` | `customer:read` |
| Shipments | `export:shipments` | `shipment:read` |
| Packages | `export:shipments` | `shipment:read` |
| Segment audience | `export:marketing_segment` | `segment:read` |
| Report results | `export:reports` | `report:read` |

`export:shipments` and `export:reports` are Admin-only today, for the same reason as the
import permissions. `export:customers` remains Admin-only as it was in Phase 1;
`export:marketing_segment` remains with Marketing.

Every export carries the filters the list screen is showing, streams rather than
materializing, is audited by type / filters / row count / actor, and never writes a file to
disk. A free-text search term is recorded as `[provided]` rather than verbatim, because a
search term can be a customer's name.

A marketing audience omits ineligible contacts from the file rather than flagging them.
Suppressed, withdrawn, unknown-consent, do-not-contact, and archived records do not appear.

### What reports will not tell you, and why

* **No comparison with a previous period, no trend arrow, no percentage change.** A change
  figure needs a comparable prior period; inventing one is worse than omitting it.
* **No carrier freshness, last-update, or last-successful-sync figure.** No provider is
  connected, so no such value exists (DEC-0075).
* **No combined currency total.** No exchange rate has been recorded.
* **A share over an empty denominator is blank, not zero.** A share of nothing is unknown.

### Phase 5A production gates

Added to section 6:

| Gate | Status |
|---|---|
| `tzdata` present in the production image | **Required.** It is a declared dependency and startup fails without it, which is the intended behaviour |
| Final Operations / Marketing permissions for import and export | **Open.** Admin-only until the owner decides |
| Vietnamese staff copy reviewed by a Vietnamese-speaking staff member | **Open.** The catalogue is complete and at key parity; the wording is unverified |
| Import limits confirmed against a real customer list | **Open.** 5,000 rows and 2 MiB are engineering defaults, not a measured requirement |
| Retention periods | **Still open.** No retention deletion is implemented, deliberately |

---

## 11. Schema drift: `alembic check` (Phase 7 follow-up)

### What the command is for

`alembic check` compares the schema in a database against the schema
`app.models.Base.metadata` describes, and fails if they differ. It is the only automated
statement that a deployed database is the database the code expects. Run it against a
database that is **at head**; against anything else it reports the difference the pending
migrations were going to make anyway.

```bash
cd backend && .venv/Scripts/python -m alembic check
```

`No new upgrade operations detected.` and exit status 0 is the pass. Any other output is
drift, and drift is a fault to investigate before deploying — not a line to scroll past.

### The one table it deliberately does not compare

`role_merge_provenance` is **owned by migration `a1c7f4d92b30`** and mapped by no model, on
purpose (DEC-0088, DEC-0089). The migration creates it on upgrade, records in it the role
each account held before the role merge, reads it back on downgrade to restore those roles
exactly, and drops it. Nothing in the running application reads or writes it; it holds staff
identifiers, and a model would be a handle on them outside the controls that protect
`users`.

Autogeneration cannot know any of that. It saw a table with no model and proposed dropping
it, on every run, which made the check fail permanently and therefore say nothing.
`backend/alembic/autogenerate_policy.py` now excludes it from the comparison, and excludes
nothing else:

* exactly the literal name `role_merge_provenance` — not a prefix, not a pattern, not
  "tables no model maps";
* only when the table is reflected from the database and has **no** counterpart in the model
  metadata. Map it one day and it is compared like anything else from that commit onward;
* nothing about columns, types, indexes or constraints on the tables the application does
  own.

**Everything else still fails the check**, and is meant to:
`backend/tests/test_alembic_autogenerate_exclusion.py` introduces another unmapped table,
four near-miss names including `role_merge_provenance_backup`, an added column and a dropped
column, and asserts each one is reported.

The cost, stated plainly: while the table is unmapped, a change *inside* it would not be
reported either. Its shape is asserted column by column in
`backend/tests/test_migrations_role_merge.py` instead, including the columns it must never
grow.

### Rules for whoever writes the next migration

1. **Keep `alembic check` green.** Every schema phase from here ends with the check passing
   against a database at head. Make the models and the schema agree; do not add a name to
   the exclusion.
2. **Do not drop, rename, map or reuse `role_merge_provenance`.** It belongs to
   `a1c7f4d92b30`. If a generated migration proposes touching it, the generation was run
   against a tree where the hook was missing — discard it and regenerate.
3. **A second migration-owned table needs a decision, not an edit.** `MIGRATION_OWNED_TABLES`
   is a one-element set, and a test asserts that it is. Widening it means writing down why
   the application will never map the new table, the same way DEC-0089 does.
4. **Never run a generated migration unread.** Autogeneration proposes; it does not decide.

### Checking a database that is not at head

```bash
# Always a scratch copy. Never data/solaris_crm.db.
DATABASE_URL="sqlite:///$TMP/scratch.db" backend/.venv/Scripts/python -m alembic upgrade head
DATABASE_URL="sqlite:///$TMP/scratch.db" backend/.venv/Scripts/python -m alembic check
```

To check a copy of a real database, copy it through SQLite's online backup API as section 10
shows. A file copy of a database something else is writing can be torn.

---

## 12. Running the Customer Account surface (Phase 9)

**Registration cannot launch in production.** Two owner decisions gate it, both enforced by
the application rather than by this document: OD-34 (no email provider) and OD-37 (no approved
legal text). Section 6 carries them as gates; this section is how to run and diagnose the
surface in development, and what an operator sees in production while those gates are open.

### 12.1 Configuration

| Variable | Default | What it does |
|---|---|---|
| `ACCOUNT_EMAIL_TRANSPORT` | `null` | `null` records a send and produces nothing; `capture` writes local files; `production` **fails at startup**, because none is written |
| `ACCOUNT_EMAIL_CAPTURE_DIR` | `<repo>/data/account_mail` | Where the capture writes. Git-ignored |
| `ACCOUNT_REHEARSE_NO_EMAIL_PROVIDER` | `false` | Development and UAT: applies the production no-provider gate (section 12.3) outside production, for UAT case `CA-REG-09`. Can only close registration, never open it. `docs/UAT/ENVIRONMENT.md` section 3c |
| `ACCOUNT_TERMS_VERSION` | `PLACEHOLDER-terms-unapproved` | Recorded on every acknowledgement. Production registration refuses while it is a placeholder |
| `ACCOUNT_PRIVACY_VERSION` | `PLACEHOLDER-privacy-unapproved` | Same |
| `ACCOUNT_SESSION_IDLE_MINUTES` | `60` | Shorter than the staff 480: a customer session is often on a shared or mobile device |
| `ACCOUNT_SESSION_ABSOLUTE_HOURS` | `24` | |
| `ACCOUNT_VERIFICATION_TOKEN_HOURS` | `24` | |
| `ACCOUNT_PASSWORD_RESET_TOKEN_HOURS` | `1` | One hour since the 2026-10-14 fix pack (DEC-0121). The reset message states the lifetime, so changing this changes the sentence the customer reads |
| `ACCOUNT_MIN_PASSWORD_LENGTH` | `12` | Length only; no composition rules |
| `ACCOUNT_*_ATTEMPTS` / `_WINDOW_SECONDS` | see `.env.example` | Ten `account:*` buckets. Starting values, not measurements |
| `ACCOUNT_LOCKOUT_*` | `10` / `15` / `15` | Failures, window minutes, lockout minutes. Bounded and never permanent |
| `ACCOUNT_MAX_BODY_BYTES` | `16384` | Far below the global request bound; none of these endpoints takes a file |

The cookie names are **not** configurable, and that is deliberate: `solaris_account_session`
and `solaris_account_csrf` differing from the staff names is a security property, not a
preference, and a deployment that could set them to the staff names could create exactly the
confusion the separate realm exists to prevent.

### 12.2 Reading captured mail in development

```bash
ACCOUNT_EMAIL_TRANSPORT=capture python -m uvicorn app.main:app --reload --port 8000 --no-proxy-headers
```

Messages land as JSON in `data/account_mail/`, one file per message, named
`<timestamp>-<template key>-<sanitized address>.json`. Each holds the recipient, the subject,
the template key, the language and the rendered body — **including the verification or reset
link in plaintext**, because the message *is* the link.

That is why this transport never ships, why it is refused at startup in production, and why
**no HTTP route returns captured mail**. A route that did would be a way to read anybody's
account-recovery credential. If a deployment ever puts a static file server in front of the
data directory, the test that walks the route table stops being the whole control.

The UAT reset script clears the directory along with the rest of the development environment.

### 12.3 What an operator sees in production today

The application starts. The Staff Portal and Public Tracking serve normally. Then:

| Request | Response |
|---|---|
| `POST /api/v1/account/register` | `503`, `{"code": "account_unavailable", …}` |
| `POST /api/v1/account/verification/resend` | `503` |
| `POST /api/v1/account/password/forgot` | `503` |
| `POST /api/v1/account/sign-in` | works — an existing account is not locked out by a delivery gate |
| `GET /api/v1/account/me` | works |

The 503 body says nothing about *why*: the reason is a deployment internal. The reason code
is in the logs.

Two configurations refuse to start at all, rather than degrading:

* `ACCOUNT_EMAIL_TRANSPORT=production` — there is no production transport, so a start would be
  a deployment silently discarding every verification link;
* `ACCOUNT_EMAIL_TRANSPORT=capture` with `ENVIRONMENT=production` — registration would appear
  to work while no customer ever received a message.

### 12.4 What to watch

None of these is implemented as an alert; they are the signals `RATE_LIMITS_AND_ABUSE.md` §7
names, expressed against the events this phase actually emits.

| Signal | Event | Means |
|---|---|---|
| Failed sign-ins per `address_key` | `customer_account.sign_in_failed` | A targeted attack on one account |
| Distinct `address_key` values per IP | same | Spraying or enumeration |
| `customer_account.locked` rate | `customer_account.locked` | Either an attack or a customer having a bad morning |
| Token refusals per identity | `customer_account.verification_refused` | Token brute force, or somebody clicking an old link |
| Registration attempts with outcome `existing_address` | `customer_account.register` | Somebody working through a list |
| Approval queue growth without verification | `customer_identities` where `status='pending_verification'` | Junk registration flood |

Every one of those payloads carries a **hashed** address key rather than an address, so a log
shipper does not become a list of who has a Solaris account. The key is stable, so grouping
works; it is keyed with the application secret, so it is not reversible.

### 12.5 Suspending or deactivating an account before Phase 10

There is no staff screen yet. The service functions exist precisely so this is possible
during an incident rather than first becoming possible on the day it is needed:

```python
from app.core.db import session_scope
from app.models import CustomerIdentity
from app.services import customer_identity_service

with session_scope() as db:
    identity = db.query(CustomerIdentity).filter_by(public_id="CA-000001").one()
    customer_identity_service.suspend(db, identity, reason_code="abuse_investigation")
```

Suspension revokes every session and takes effect on the **next request**, because the session
row holds no cached grant. `deactivate` additionally invalidates every outstanding token.
Neither deletes anything: there is no self-service hard delete, and a privacy request is
staff-executed and audited (OD-35). `reinstate` returns a suspended account to
`pending_approval`, never to `active` — only an explicit staff approval with a link reaches
`active`, and reinstatement must not become a second door into it.

Both write an audit row with the actor, the reason code and the identity's `public_id`.

### 12.6 The Phase 9 migration

`b1047733d0e9`. Nine new tables; nothing existing is altered, dropped or rewritten.

```bash
python -m alembic upgrade head        # from a1c7f4d92b30
python -m alembic downgrade a1c7f4d92b30
```

The downgrade drops the nine tables cleanly and is tested rather than asserted:
`tests/test_migrations_phase9.py` upgrades a populated Phase 8 database, downgrades it,
re-upgrades it, and compares the schema and every pre-existing row count at each step.

**A downgrade destroys every Customer Account identity, session, token, acknowledgement,
preference and proposal in the database it runs against.** That is the correct behaviour for
reversing the phase that introduced them, and a reason not to run it against anything but a
development database.

`alembic check` is green at head, and the autogeneration exclusion still names exactly
`role_merge_provenance` (section 11, DEC-0089).


## 13. Customer Account approval and linking (Phase 10)

### 13.1 The Phase 10 migration

`6af30fcdd3a8`. Two new tables and two new nullable columns on `customers`. Nothing is
dropped, renamed or rewritten.

```bash
python -m alembic upgrade head        # from b1047733d0e9
python -m alembic downgrade b1047733d0e9
```

**The downgrade requires SQLite 3.35.0 or newer** and refuses, with a message naming the
version it found, on anything older. The verified environment runs 3.49.1 (section 9 of
`docs/DEPLOYMENT.md`). The reason is worth knowing before an incident: Alembic's batch
`DROP COLUMN` rebuilds the table, and rebuilding `customers` violates the foreign keys
eleven other tables hold into it, with `PRAGMA foreign_keys` on for every connection. The
usual workaround — turning the pragma off around the rebuild — does not work either,
because the pragma is a no-op inside a transaction and a migration runs inside one. So the
downgrade uses the native statement, which rebuilds nothing, and refuses rather than
falling back to something known to fail (DEC-0102).

**A downgrade loses whatever was written into `customers.legal_name` and
`customers.display_name`**, and drops every disclosure acknowledgement and approval attempt
row. Every other column of every existing row survives, which is asserted value by value
rather than by row count: `tests/test_migrations_phase10.py` upgrades a populated Phase 9
database, downgrades it, re-upgrades it, and compares `customers`, `customer_addresses`,
`shipments`, `consent_events`, the aliases, the identities and the proposals column by
column at each step.

`alembic check` is green at head, and the autogeneration exclusion still names exactly
`role_merge_provenance`.

### 13.2 Who may review and approve

Two permissions, held by **Admin and Operations only**:

| Permission | Grants |
|---|---|
| `customer_account:review` | Read the pending queue, one application, its duplicate candidates, an approval preview |
| `customer_account:approve` | Acknowledge a preview, approve by creating, approve by linking, reject |

Every mutating route requires both. Marketing and the read-only manager hold neither and
reach nothing, even though both hold `duplicate:review` — reviewing a duplicate candidate
and activating somebody's account are deliberately separate powers (OD-24, DEC-0100).

### 13.3 What an approval actually does, for an operator

An approval either **creates a canonical customer** or **links to one that exists**, and the
difference matters operationally:

* **Create-new** writes a `customers` row through the same service a staff member uses, its
  addresses, and a marketing consent event *only* if the applicant explicitly chose one and
  the address is not suppressed. It shows up in the audit log as a normal `customer.create`
  plus the Customer Account actions.
* **Link-existing** writes **no canonical customer value at all**. Differences between what
  the applicant submitted and what the record holds are recorded as field keys and applied
  to nothing. If a linked customer's details need correcting, that is ordinary Staff Portal
  work; the registration does not do it (DEC-0104).

Both are refused unless the reviewer has read and acknowledged the **history disclosure
preview** — how many historical shipments the link makes visible, their oldest and newest
dates, and whether cancelled and rebooked ones are included (OD-29).

### 13.4 "The preview is out of date" — what to tell a reviewer

A `409` with `preview_stale` means a material fact moved between the preview and the
approval: somebody edited or merged the customer, a shipment was booked, cancelled or
rebooked, the applicant submitted a replacement, another reviewer decided first, or another
account took the customer. **It is not an error to retry past.** Take a fresh preview, read
it — the figures may be different — acknowledge it, and approve again.

A burst of these is a signal worth reading: two reviewers working the same queue, or
something rewriting customers while approvals are in flight.

### 13.5 Development-only decision notices

Approval and rejection each send one message through the Phase 9 seam, which in development
writes a local file and in production sends nothing because no provider is configured
(OD-34). Both are skipped silently, **without failing the decision**, when the address is
suppressed or when delivery is blocked: the account state is the fact, the message is a
courtesy, and refusing to approve accounts because no mailbox can be reached would be the
wrong trade. An idempotent retry sends nothing a second time.

Neither message carries a customer id, a linked-customer name, a shipment count, a staff
name, a duplicate result or a rejection reason.

### 13.6 What a rejection does to the account

Immediately, not at the next sign-in: every session is revoked and every outstanding
verification and reset token is invalidated. No customer and no link is created. The person
is told the account cannot be used and nothing else.

**Re-registration with the same address creates nothing** and returns the same generic
response as any already-registered address. The documented recovery is Admin reinstatement
(`STATE_MACHINES.md` transition 9), which **is not built** — see the gates below.

---

## 14. Authenticated shipment history (Phase 11)

### 14.1 There is no migration

Phase 11 adds no table, no column and no index. The schema is exactly where Phase 10 left
it, `alembic check` is green at the same head (`6af30fcdd3a8`), and there is nothing to
apply before or after deploying this code. The only database write either new route makes is
one `audit_events` row on a refused read.

### 14.2 Configuration

| Setting | Default | What it does |
|---|---:|---|
| `ACCOUNT_READ_IDENTITY_ATTEMPTS` | `300` | Authenticated shipment reads allowed per window, per account |
| `ACCOUNT_READ_IDENTITY_WINDOW_SECONDS` | `300` | The window |

Nothing else was added. The page-size bound (50), the default page size (20), the maximum
date range (400 days) and the status-group vocabulary are constants in
`app/services/customer_account_shipment_service.py`, because each of them is a **disclosure**
decision rather than a deployment one — raising the page size is a change to how much a
compromised session can pull per request, and that belongs in a diff a reviewer reads, not in
an environment variable.

The read bucket is keyed by the account, not by the address. A customer paging through their
own history will never reach 300 requests in five minutes; the bound exists so that a stolen
session cannot pull a long history quickly.

### 14.3 What an operator sees

Two log events, both on `solaris.account_shipments`:

```
account_shipment_read  surface=list    outcome=ok                             page_size=20 returned=7
account_shipment_read  surface=detail  outcome=not_found                      reference_digest=<keyed>
account_shipment_read  surface=list    outcome=not_authorized:no_effective_link
account_shipment_read  surface=detail  outcome=rate_limited
```

Every line carries `identity_digest` — a keyed digest of the account reference, **not** the
`CA-` reference. That is deliberate: an audit row is staff-facing and access-controlled,
while a log line goes to a file, a shipper and possibly a search index. The digest is stable,
so one session's requests correlate; it is not reversible, so a log export is not a list of
who has an account.

No log line and no audit payload carries a shipment reference, a carrier tracking number, an
email address, a phone number, recipient information, a session or CSRF value, a response
body, or a financial figure. `app.core.logging.SAFE_FIELDS` drops any field not on it, so a
field added to a call site and not to that set simply vanishes rather than leaking.

### 14.4 What to watch

| Signal | Means |
|---|---|
| `outcome=not_found` rising for one `identity_digest` | Probing after a session compromise (T-03). The digest groups the attempts; the reference digest says whether it is one reference or many |
| `outcome=rate_limited` for one `identity_digest` | A session pulling faster than a person reads. Worth correlating with `customer_account.sign_in` events for that account |
| `outcome=not_authorized:*` in bulk | Usually benign — approved accounts whose link was revoked, or applicants refreshing a page. A spike of `multiple_effective_links` is **not** benign and means the partial unique index is not doing its job |
| `customer_account.shipment_access_denied` rows growing steadily | The audit-side view of the same two signals, and the one that survives log rotation |

`not_authorized:linked_customer_merged` should be impossible: OD-40 refuses a merge while
either side holds an active link. If it ever appears, a merge has completed against a linked
customer and the account is reading nothing — investigate the merge path before touching the
link.

### 14.5 Telling a customer why they cannot see their history

The surface says one sentence for every reason, and does not narrate which one applies. An
operator can tell them apart from the log line's `outcome`:

| `outcome` | What to tell the customer |
|---|---|
| `identity_not_active` | Their application is still with the review queue, or their account has been suspended. Which of the two is a staff question, answered by the approval queue |
| `no_effective_link` | The account is approved but not linked, which should not happen — approval writes the link. Treat as a defect |
| `multiple_effective_links` | A database integrity problem. Do not "fix" it by revoking one at random; take it to whoever can say which link was intended |
| `linked_customer_archived` | Somebody archived a customer that has an account. Unarchiving restores access immediately, on the next request |
| `linked_customer_merged` | See above — this should be unreachable |

None of these reasons reaches the customer, and none of them should be read to them
verbatim: "your linked customer record was archived" is an internal fact about the CRM.

### 14.6 Suspension, deactivation and revocation take effect immediately

Not at the next sign-in — on the **next request**. The authorization chain is re-read from
the database on every read, and nothing is cached on the session row. An operator who
suspends an account can refresh and see the next request refused; there is no session to
wait out and no cache to clear.

The same is true in the other direction: a shipment booked a moment ago appears on the next
list request, and a link reinstated appears immediately.

### 14.7 Phase 11 production gates

Nothing new. The Customer Account's production blockers are unchanged and all of them predate
this phase: an approved email provider (OD-34), approved terms and privacy text with version
identifiers (OD-37), reviewed customer-facing English copy (OD-39), an accessibility review
(OD-19), retention periods (OD-01, OD-36), a shared rate-limit store if more than one worker
process runs (DEC-0006), and secrets in a secret store.

Phase 11 adds no customer-facing screen, so none of these moved — and none of them is
relieved by the routes existing. The surface is reachable by API and by nothing else until
Phase 12.

---

## 15. The development email workflow (Phase 12)

**This section is how a person gets a verification or password-reset link while testing the
Customer Account screens.** There is no mailbox page, there is no "show me the last email"
button, and neither is an omission.

### 15.1 The rule this section exists to keep

**No HTTP route returns captured mail, in any environment.** A captured verification or
reset message contains the link in plaintext, and that link is a live credential for
somebody's account until it is redeemed or expires. A route that returned captured mail —
even one gated on a development flag, even one on a port nobody exposes — would be a way to
read anybody's account-recovery credential, and a flag is a thing that gets set in the wrong
environment exactly once.

`EMAIL_DELIVERY.md` §2 states it; `backend/tests/test_account_email_capture.py` asserts it by
walking the route table rather than by grepping for a handler.

The consequence is that reading a message is a **filesystem** operation. That is the whole
inconvenience, and it is the point: a person who can read the capture directory is a person
who is already on the machine.

### 15.2 Manual development procedure

Start the backend with the capture transport:

```bash
ACCOUNT_EMAIL_TRANSPORT=capture backend/.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000 --app-dir backend --no-proxy-headers
```

Start the frontend as usual, and open `http://localhost:5173/account/register`.

After registering, the message is a JSON file in `data/account_mail/`:

```
data/account_mail/20260921T140355123456-account.verify_email-someone_example.com.json
```

The filename is `<timestamp>-<template key>-<sanitized address>.json`, so the newest file
for an address is the last one when the directory is sorted by name. The file holds the
recipient, the subject, the template key, the language and the rendered body.

**Open the file, copy the link out of the body, and paste it into the browser.** The link
points at `TRACKING_BASE_URL`'s origin with `/account/verify-email#token=…`, which in a
default development setup is `http://localhost:5173`. The token is in the URL fragment
since the 2026-10-14 fix pack (CA-SEC-07): a fragment is never sent to a server, and the
landing page removes it from the address bar before anything else runs. Links in the
older `?token=` shape still work.

The six template keys, so a tester knows which file to look for:

| Template key | Sent when |
|---|---|
| `account.verify_email` | Registration, and every resend |
| `account.registration_attempt_notice` | Registration for an address that already has an account |
| `account.password_reset` | A reset was requested for an address that has an account |
| `account.password_changed` | A reset completed. **No link** |
| `account.approved` | Staff approved the account. A sign-in link, no token |
| `account.rejected` | Staff declined it. Neutral wording, no reason, no link |

### 15.3 Two things that look like faults and are not

**A resend makes the previous link stop working.** Issuing a new token of the same purpose
invalidates the outstanding ones (`STATE_MACHINES.md` §5). A tester with two messages open
who clicks the older one reads "That link is no longer valid" and is looking at the control
working. Use the newest file.

**Registering twice with the same address produces no second verification message.** The
second registration creates nothing and may send a `account.registration_attempt_notice` to
the existing address instead — at most one per window. The HTTP response is byte-identical
either way, which is the enumeration defence (T-02), so the *only* way to tell what happened
is the capture directory. That is a testing convenience, not a customer-facing one.

### 15.4 Clearing the directory

The UAT reset script clears `data/account_mail/` with the rest of the development
environment. To clear it by hand, delete the `.json` files in it — nothing else reads them,
and the directory is git-ignored, so nothing there has ever been committed.

**Do not copy a captured message into a defect report, a screenshot, a ticket or a chat.**
The body contains a working credential. Quote the template key and the timestamp instead.

### 15.5 The E2E environment

`scripts/e2e_env.py` sets `ACCOUNT_EMAIL_TRANSPORT=capture` and points
`ACCOUNT_EMAIL_CAPTURE_DIR` at `data/e2e/run-<id>/mail/` — **inside the run's own
directory**, so it is removed when the run passes and preserved with the rest of the
evidence when it fails. `data/e2e/` is git-ignored at any depth, so a captured token cannot
be committed even by accident.

`frontend/tests/e2e/mailCapture.js` reads that directory. It:

* requires `E2E_MAIL_DIR`, which only `scripts/run_e2e.mjs` sets, and **throws rather than
  falling back** to the development capture directory. A fallback would let the helper
  succeed against a developer's own machine, which is the shape of the 2026-09-20 incident;
* returns a **link path**, never a message body, so a token cannot reach a Playwright
  failure message, a trace or an attached screenshot;
* makes no HTTP request of any kind.

A spec follows the link with `page.goto(...)`. No spec prints a token, and no fixture
contains one: every address a spec registers is minted per run.

### 15.6 Production

`ACCOUNT_EMAIL_TRANSPORT=capture` **is refused at startup in production**
(`config.email_transport_problems`), because a capture in production means registration
appears to work while no customer ever receives a message.

`ACCOUNT_EMAIL_TRANSPORT=production` is also refused, because no production transport is
written: OD-34 has selected no provider, and writing an adapter would be choosing one by
implementation.

So in production the transport is `null`, `account_delivery_blockers` is non-empty, and the
registration, resend and password-reset routes answer `503` with
`{"code": "account_unavailable", "message": "Customer accounts are not available yet. Please
contact Solaris Express."}`. The Customer Account registration screen renders that sentence
under the heading "Accounts are not open yet" and offers public tracking instead. **It names
no setting, no provider, no transport and no version string** — a configuration gate is not
something to explain to a stranger — and `tests/accountAuth.test.jsx` asserts that by
scanning the rendered page for those words.

## 13. Vendor tariffs and the exchange-rate worker (Phase 13A)

Two operator tasks arrive with the B2C merge's first phase: importing a vendor tariff
workbook, and running the exchange-rate worker. Both write **vendor cost data, which is
strictly internal** (directive v2.1 §1): the routes live on the staff router behind
`tariff:read` and `tariff:manage`, and nothing here ever reaches the public or Customer
Account routers (`backend/tests/test_tariff_import.py` asserts it).

### Importing a tariff workbook

An administrator uploads the vendor's `.xlsx` through `POST /api/v1/tariffs/versions/import`
with the effective date from the workbook's title. The importer:

* parses the file in memory (a part over 1 MiB may be spooled by the framework to a
  temporary file that is deleted when the request ends; nothing is written under the
  application's control);
* refuses a file whose SHA-256 was already imported (409, naming the existing version);
* refuses anything that is not laid out as a Kango tariff (422, saying which anchor it
  could not find) rather than importing part of it;
* writes a **draft** version with every table and an import report: counts, the anomalies it
  found (a price that falls as weight rises, a duplicate FSA, a beyond code with postal codes
  but no rate), the surcharge rows by pricing status, and the rules it read from prose.

Read the report before activating. `POST /api/v1/tariffs/versions/{id}/activate` makes the
version the one quotations will price against and marks the previous one `superseded`;
nothing is deleted, and a superseded version cannot be re-activated (import the file again
instead). Both acts are audited (`tariff_version.imported`, `tariff_version.activated`).

The vendor's workbook carries a sheet listing its own staff with personal mobile numbers.
The importer skips that sheet by name and never reads the corporate contact block; do not
copy the original workbook into this repository. The committed test fixture is a sanitized
copy made by `scripts/sanitize_kango_workbook.py`.

### The exchange-rate worker

```bash
backend/.venv/Scripts/python -m app.workers.fx_worker --once
```

One attempt against Vietcombank's public XML feed: fetch, verify, snapshot, exit 0 on a
verified reading and 1 otherwise. Every attempt is recorded in `fx_sync_attempts`; a
verified reading also writes `fx_rate_snapshots` with cash buying, transfer buying and
selling for CAD, the bank's own stamp, the retrieval time and the response digest.

```bash
backend/.venv/Scripts/python -m app.workers.fx_worker --poll-seconds 300
```

Continuous mode repeats every `FX_POLL_SECONDS` (default 300, floor 60) and stops cleanly
on `SIGINT`/`SIGTERM`. Run exactly one. **No unattended worker was started during this
build**; scheduling it is an operations decision to record here when it is taken.

What it refuses, and records as a failed attempt rather than a number: a response missing
either rate, a rate outside 1,000–100,000 VND/CAD, a selling rate not above the cash-buying
rate, a redirect, a non-XML response, anything larger than 512 KiB, and any URL that is not
the bank's own HTTPS host. It never substitutes another provider's rate.

What to watch: `GET /api/v1/fx/latest` reports `freshness` as `live`, `stale` (newest
snapshot older than `FX_STALE_AFTER_MINUTES`, default 1,440) or `none`, with the last
attempt's outcome and error category. A run of `failed` attempts is an outage at the bank or
on the network; the pricing engine (Phase 13C) will refuse to finalise on `stale` or `none`
rather than price silently.

What reaches a log: attempt outcome, worker name, a bounded error category. Never the
response body and never a rate value.

Configuration: `TARIFF_IMPORT_MAX_BYTES` (default 4 MiB), `FX_POLL_SECONDS`,
`FX_STALE_AFTER_MINUTES`. The bank's URL is fixed in `app/services/fx_service.py` on purpose.
