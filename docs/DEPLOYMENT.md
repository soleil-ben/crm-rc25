# Deployment preparation

Vendor-neutral. Nothing here names a hosting provider, because none has been chosen
(`docs/HOSTING.md`).

> **Nothing is deployed.** No host, domain, certificate, DNS record, or service has been
> purchased, configured, or contacted. This document is what a deployment *would* consist
> of. Preparing a deployment is not deploying one, and this phase did neither.

---

## 1. The baseline architecture

Constrained by one fact: **SQLite has a single writer**. Everything below follows from it.

```
                    Internet
                       │
                       ▼
           ┌───────────────────────┐
           │   Reverse proxy       │  TLS termination
           │   (nginx / Caddy /    │  Access-log redaction  ← DEC-0057
           │    provider LB)       │  Request body limits
           └───────────┬───────────┘
                       │  127.0.0.1 only
                       ▼
           ┌───────────────────────┐
           │  Application          │  EXACTLY ONE instance
           │  uvicorn, 1 worker    │  --no-proxy-headers    ← DEC-0048
           │  /health/live         │
           │  /health/ready        │
           └───────────┬───────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌───────────────┐            ┌──────────────────┐
│ SQLite on     │◀───────────│ Integration      │  EXACTLY ONE
│ persistent    │            │ worker           │  Nothing to do until
│ local disk    │            │ (separate proc)  │  a provider exists
└───────┬───────┘            └──────────────────┘
        │
        ▼
┌───────────────┐            ┌──────────────────┐
│ Backups       │───────────▶│ Off-site copy    │  NOT CONFIGURED
│ (local)       │            │                  │  Encrypted in transit
└───────────────┘            └──────────────────┘  and at rest
```

| Component | Requirement | Why |
|---|---|---|
| **Application instances** | **Exactly one** | SQLite has one writer, and the rate limiter is per-process (DEC-0006) — two instances would give a caller two allowances |
| **Integration worker** | **Exactly one**, separate process | Same single-writer constraint. Nothing to do until a provider is verified (DEC-0075) |
| **Storage** | **Persistent local disk.** Never NFS, SMB, or any network filesystem | SQLite's locking is unreliable on network storage. An ephemeral filesystem loses the database on restart |
| **TLS** | Terminated at the proxy | `COOKIE_SECURE=true` requires it, and the public tracking page carries customer data |
| **Reverse proxy** | Required. See §3 | TLS, body limits, and access-log redaction |
| **Secrets** | Environment file mode `0600`, or a platform secret store | Never in the repository or a unit file |
| **Backups** | Local plus off-site | `docs/BACKUP_RESTORE.md` |
| **Logs** | Structured JSON to the journal or a file, rotated | `docs/MONITORING.md` §9 |

**There is no object storage, no message broker, no cache, and no managed database.** Label
PDFs are generated on demand inside the request and streamed; nothing is stored. Adding
infrastructure that is not needed is adding something else to fail.

---

## 2. Deployment checklist

Run in order. Steps 1–4 happen before any traffic moves.

### Before the first deployment

- [ ] Host provisioned with persistent local storage
- [ ] Service user and group created; it owns the application directory and the data directory
- [ ] `data/` and `backups/` created on persistent storage, mode `0700`, owned by the service user
- [ ] Python 3.11+ and Node 22 available (see §6)
- [ ] Domain registered; DNS pointing at the host
- [ ] TLS certificate issued and auto-renewal working — **verify renewal, do not assume it**
- [ ] Reverse proxy configured, including §3
- [ ] `.env.production` written, mode `0600`, every item in §4 answered
- [ ] Service templates in `deploy/` edited: every `@PLACEHOLDER@` replaced

### Every deployment

- [ ] **Take a backup, and verify it** — `scripts/backup_db.py`. Not optional, and not "the nightly one will do"
- [ ] Confirm the backup reports `integrity_check ok`
- [ ] Build the frontend: `npm run build --prefix frontend`
- [ ] Stop the worker **first**, then the application
- [ ] Deploy the new code
- [ ] **Run migrations before starting the application:** `cd backend && .venv/bin/python -m alembic upgrade head`
- [ ] Start the application; wait for `startup_complete`
- [ ] **Confirm `/health/ready` returns 200 with all three checks `ok`** — do not restore traffic until it does
- [ ] Start the worker
- [ ] Run the smoke test (§5)
- [ ] Watch error rate and process restarts for the first hour

### Migration ordering, and why it is this way

**Migrations run while the application is stopped, before the new code starts.**

The application refuses readiness when the stamped revision does not match the code's
expected head, so starting first would produce a process that is alive and not ready — and
a supervisor that restarts on readiness failures would loop forever.

Running them *before* stopping the old code is also wrong: the old code would then be
serving against a schema it does not expect.

Every migration in this project is additive and reversible, and each has a tested
downgrade. That is what makes rollback (§7) possible at all.

---

## 3. The reverse proxy, and the DEC-0048 resolution

**Decision: proxy-header trust stays disabled, and Phase 5B did not enable it.** What
follows is the exact set of conditions under which it may be enabled later.

### Why it is disabled

`TRUST_PROXY_HEADERS` defaults to false, and the documented run command passes
`--no-proxy-headers`.

DEC-0007 originally said the application does not read forwarding headers. **The Phase 3
end-to-end suite proved that was not protection.** Uvicorn enables `--proxy-headers` by
default and trusts `127.0.0.1`, so it rewrites `request.client` from `X-Forwarded-For`
*before the application runs*. The application was declining to read a header whose value
it was already being handed as the peer address — and a caller on loopback got a fresh
rate-limit bucket per request simply by changing it. Which is to say: no rate limit at all.

Two mechanisms hold the line now, because one of them depends on deployment configuration
and the other does not:

1. `--no-proxy-headers` on the server, which is correct and documented;
2. the shared-bucket rule in `public_client_key`: while trust is off, **every** request
   carrying a forwarding header is folded into one shared bucket, whatever the ASGI server
   did to the scope. A spoofer can exhaust that one bucket and no more; a direct caller,
   who sends no such header, keeps their own and is unaffected.

Six unit tests cover it, plus an end-to-end test that sends a different forged address on
every request and asserts the limit still engages.

### The exact conditions required before enabling it

**All five, or none.** Phase 5B added an enforcement for this: production refuses to start
with one half set and the other empty (DEC-0087).

1. **A specific reverse proxy is deployed**, and you can name its address.
2. **`TRUSTED_PROXY_HOSTS`** lists exactly that address — not a range, not `*`, not a
   hostname that could resolve elsewhere.
3. **`TRUST_PROXY_HEADERS=true`** is set at the same time.
4. **The ASGI server is told to trust only that proxy**, by replacing `--no-proxy-headers`
   with `--forwarded-allow-ips=<that exact address>`. Never `*`.
5. **The proxy overwrites `X-Forwarded-For` rather than appending to it**, so a
   client-supplied value cannot survive into the header the application believes.

### What must be verified about the network hops

Before turning it on, establish and write down:

- **How many proxies are in front of the application.** If there are two — a provider load
  balancer and your own nginx — `X-Forwarded-For` has two entries and the client address
  is not the last one. Getting this wrong keys the limiter on your own proxy's address.
- **Whether the platform's load balancer already sets the header**, and whether it
  overwrites or appends.
- **Whether the application port is reachable from anywhere except the proxy.** If it is,
  trust is unsafe regardless of configuration: an attacker who can reach the port directly
  can set any header they like. Bind to `127.0.0.1` and firewall the port.

### How an incorrect configuration corrupts client-IP rate limiting

| Misconfiguration | Result |
|---|---|
| Trust enabled, proxy **appends** rather than overwrites | A client sends its own `X-Forwarded-For`; the application believes it. **Fresh allowance per request — the limiter is gone** |
| Trust enabled, application port reachable directly | Same, bypassing the proxy entirely |
| Trust enabled, wrong hop counted with two proxies | Every request keys to the same address. **Every customer shares one bucket**, and normal traffic trips the limit |
| Trust **disabled** with a proxy in front (today's state) | Every request keys to the proxy's address. Same shared-bucket effect: legitimate customers throttle each other. **This is the single most likely cause of a public rate-limit problem immediately after deployment** — see `RUNBOOKS.md` §9 |
| `--forwarded-allow-ips=*` | Anyone who reaches the socket is trusted. Worst of all |

Note the fourth row: **the current safe default is not free.** Disabled trust behind a
proxy collapses all customers into one bucket. That is why enabling it correctly is a
launch task rather than an optional nicety — but half-enabling it is worse than either.

### How to test the resulting client-address behaviour

After enabling, before announcing:

1. **From outside, as a normal client.** Make a public lookup. The limiter should key to
   your real address — repeat until it engages and confirm the count matches the
   configured allowance.
2. **From a second, different address**, confirm you have your own allowance and were not
   affected by step 1.
3. **Forge the header.** Send `X-Forwarded-For: 203.0.113.1` and a different value on each
   request. **The limit must still engage.** If it does not, the proxy is appending rather
   than overwriting, or the port is directly reachable.
4. **Try the application port directly**, bypassing the proxy. It should not be reachable.
5. Confirm the audit log and structured logs show a sensible `client_key` distribution —
   not every request sharing one value.

`frontend/tests/e2e/zzRateLimit.spec.js` already performs the equivalent of step 3 locally.

### Access-log redaction — required, and the proxy's job

**The application never logs a tracking reference** (DEC-0057); it logs the route template
`/api/v1/public/track/{reference:path}` and a keyed digest. **The reverse proxy does not
know that.** Its access log records the resolved path, which contains the reference.

This must be configured before launch. For nginx:

```nginx
# Replace the tracking reference in the logged path with a placeholder, so the
# access log cannot become a list of customers' parcels.
map $request_uri $safe_request_uri {
    "~^(?<prefix>/api/v1/public/track/).*$"  "${prefix}[redacted]";
    default                                   $request_uri;
}

log_format solaris '$remote_addr - - [$time_local] '
                   '"$request_method $safe_request_uri $server_protocol" '
                   '$status $body_bytes_sent';

access_log /var/log/nginx/solaris.log solaris;
```

The same applies to any platform-provided access log you cannot reconfigure. **If the
platform logs full URLs and cannot be told not to, that is a reason not to use it** for
the public tracking host.

### Other proxy requirements

- `client_max_body_size` at or below the application's `MAX_REQUEST_BYTES` (8 MiB default)
- Pass `Host` through unchanged
- Do not cache public tracking responses; the application already sends `no-store`
- Proxy to `127.0.0.1`, and firewall the application port

---

## 4. Production configuration checklist

The application **refuses to start** in production if any of the refusals below is
violated. It lists every problem at once rather than one per restart.

| Setting | Requirement | Enforced |
|---|---|---|
| `SECRET_KEY` | Generated randomly, at least 32 characters, from a secret store | **Refuses to start** — dev default or too short |
| `COOKIE_SECURE` | `true` | **Refuses to start** |
| `COOKIE_SAMESITE` | Reviewed for the final domain layout; `none` requires secure | **Refuses to start** if `none` without secure |
| `ALLOW_DEMO_SEED` | `false` | **Refuses to start** |
| `DEBUG` | `false` | **Refuses to start** |
| `LOG_LEVEL` | `INFO` or higher, never `DEBUG` | **Refuses to start** on `DEBUG` |
| `CORS_ORIGINS` | The exact production origin, https, no localhost | **Refuses to start** |
| `TRACKING_BASE_URL` | The real tracking domain, https, not localhost | **Refuses to start** |
| `DATABASE_URL` | Absolute path, on persistent storage, outside the source tree, directory exists | **Refuses to start** |
| `TRUST_PROXY_HEADERS` / `TRUSTED_PROXY_HOSTS` | Both, or neither (§3) | **Refuses to start** if only one |
| `PUBLIC_HELP_URL` | The real contact URL | **Warns** — `public_help_url_empty`. Incomplete, not unsafe |
| `PUBLIC_CARRIER_LINK_HOSTS` | Reviewed; each host is where that carrier actually serves public tracking | **Warns** if empty |
| `DEFAULT_TIMEZONE` | `America/Toronto` unless the business says otherwise; `tzdata` installed | **Refuses to start** if unresolvable |
| Demo users | Every seeded account removed; real staff accounts created | Manual — check `users` and `is_demo_record` |
| Seed data | No `is_demo_record` rows in production | Manual |
| Filesystem permissions | `data/` and `backups/` mode `0700`, owned by the service user; `.env.production` mode `0600` | Manual |
| Backup directory | On persistent storage, with the retention the owner chooses | Manual — **retention is an open owner decision** |
| Retention settings | **Undecided.** No retention deletion exists, deliberately | Nothing to configure yet |
| Integration status | `INTEGRATION_RESOURCE_ALLOWED_HOSTS` and `..._PATH_PREFIXES` **empty**; registry empty; health `not_configured` | Asserted by test |

### Generating a secret

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Store it in the secret store or `.env.production`. Rotating it does **not** invalidate
sessions — sessions are opaque random values stored as digests — so revoke sessions
explicitly if that is the intent.

---

## 5. Post-deployment smoke test

Manual, five minutes, every deployment. Automated tests do not prove *this* deployment
works.

- [ ] `/health/live` returns 200
- [ ] `/health/ready` returns 200, all three checks `ok`
- [ ] Sign in as a real staff account; confirm the dashboard renders with real counts
- [ ] Open a customer record; confirm Vietnamese names render with diacritics intact
- [ ] Open a shipment; confirm the Solaris ID displays and copies
- [ ] Generate a label preview; confirm the PDF downloads and is 4 × 6
- [ ] Open a report; confirm figures appear and the range is in the URL
- [ ] Export a CSV; open it and confirm the BOM, headers, and diacritics
- [ ] **Public tracking, from a device that is not signed in**: look up a real Solaris ID over HTTPS, confirm the result, and confirm the language switch works
- [ ] **Public tracking with a nonsense reference**: confirm the generic failure
- [ ] Confirm the TLS certificate is valid and the padlock is clean
- [ ] Confirm the proxy access log shows `[redacted]` in place of the tracking reference
- [ ] Confirm no console error and no third-party network request on the public page
- [ ] Take a backup and confirm `integrity_check ok`

---

## 6. Dependency and runtime versions

| Component | Version | Notes |
|---|---|---|
| Python | **3.11+** (3.12.10 used for all Phase 5B evidence) | `requires-python = ">=3.11"` |
| Node | **22** | Build only; not required at runtime |
| SQLite | **3.49.1** in the verified environment | Must support WAL. Any modern build does |
| FastAPI | `>=0.115` | |
| SQLAlchemy | `>=2.0.36` | |
| Alembic | `>=1.14` | |
| Pydantic | `>=2.9` | |
| uvicorn | `>=0.32` with `[standard]` | |
| argon2-cffi | `>=23.1` | Password hashing |
| **tzdata** | `>=2024.2` | **Load-bearing.** Windows ships no tz database and slim Linux images often omit one; without it every "Toronto" timestamp silently becomes UTC. `create_app` refuses to start if the zone cannot be resolved |
| reportlab | `>=4.2` | Label PDFs. BSD-licensed |
| python-multipart | `>=0.0.9` | CSV upload |

The frontend build produces static files. The application serves the API; the proxy or a
static host serves the built assets.

**`index.html` must be served with `Cache-Control: no-store, no-cache, must-revalidate,
private` and `Pragma: no-cache`.** The staff portal is one document whose screens render
customer data, and a browser allowed to keep a copy can show that copy after a sign-out,
from the Back button or the back-forward cache (UAT-AD-01). The hashed assets under
`assets/` may be cached for as long as you like; the document may not. The Vite dev and
preview servers already send these headers (`frontend/vite.config.js`); the production
host has to be told. For nginx:

```nginx
location = /index.html {
    add_header Cache-Control "no-store, no-cache, must-revalidate, private" always;
    add_header Pragma "no-cache" always;
}
location / {
    try_files $uri /index.html;
}
```

**`pymupdf` is an optional dev extra and is AGPL-3.0.** It is used only by the local test
suite to rasterize a page for barcode decoding, is never imported by the application, and
is not part of the shipped product.

---

## 7. Rollback

The full procedure is `RUNBOOKS.md` §12. The essentials:

1. Take a backup **first** — the data written since the release exists only in that file
2. Stop the worker, then the application
3. If the release included a migration, downgrade **before** deploying the previous build,
   and rehearse the downgrade against a scratch copy if there is any doubt
4. Deploy the previous build
5. Confirm `/health/ready`, then smoke test

**Never roll the application back without considering the schema.** A previous build
against a newer schema fails in ways that look like data corruption.

---

## 8. Gates still open at deployment time

| Gate | Status |
|---|---|
| Hosting chosen | **Open** — `docs/HOSTING.md`; pricing research deferred by owner decision |
| Domain and TLS | **Open.** `track.solarisexpress.ca` does not exist |
| `PUBLIC_HELP_URL` | **Open — owner decision** |
| Carrier link allowlist reviewed | **Open.** Nine plausible hosts nobody has checked |
| Retention period | **Open — owner decision** |
| Final Operations/Marketing permissions | **Open — owner decision** (DEC-0082) |
| Proxy-header trust enabled correctly | **Open.** Conditions in §3; deliberately not enabled |
| Access-log redaction configured | **Open.** §3 |
| Off-site backup | **Open** |
| MFA | **Open.** Not built |
| Physical label print and scan | **Open.** Never printed on real hardware |
| Vietnamese copy reviewed | **Open — owner decision** |
| Staff UAT executed | **Open.** Materials prepared, not run |
| Provider integration | **Deferred to the final phase** (DEC-0075) |
