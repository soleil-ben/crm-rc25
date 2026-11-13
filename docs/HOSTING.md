# Hosting and the PostgreSQL threshold

Three hosting approaches compared on their fit for this application, the threshold at
which SQLite stops being the right answer, and a PostgreSQL migration plan.

> **Nothing has been selected, purchased, contacted, or configured.**

---

## 1. Pricing research: deliberately incomplete

**No prices appear in this document.** This is an owner decision recorded on 2026-09-14:
pricing research is **deferred until a hosting option is shortlisted closer to
deployment**.

| | |
|---|---|
| **Status** | **INCOMPLETE — deferred by owner decision** |
| **Why** | Quoting a price requires an authoritative current source and the date it was checked. Live pricing was deliberately not fetched in this phase |
| **What is not here** | Base compute, storage, bandwidth, backup, taxes, and optional-service costs for any provider |
| **What must happen before a figure is quoted** | Check the provider's own current pricing page, record the URL and the date checked, and separate base compute from storage, bandwidth, backups, taxes, and optional services |

**No price is estimated, remembered, or carried over from anywhere.** A stale or invented
figure is worse than no figure: it gets into a budget and nobody re-checks it. The
comparison below is on *architecture fit*, which does not expire the way a price does.

When a shortlist exists, the cost dimensions that will actually matter for this
application are:

- **Compute** — one small instance is enough; this is not a CPU-bound workload
- **Persistent block storage** — mandatory, and the item most often mispriced or missing
- **Bandwidth** — low. Label PDFs are the largest responses and are generated on demand
- **Backup storage, off-site** — the item most often forgotten entirely
- **Taxes** — Canadian business; confirm whether quoted prices include them
- **Optional services** — a managed database is **not** needed before the PostgreSQL gate

---

## 2. The three approaches

Judged on fit for *this* application, whose defining constraint is a single SQLite file on
a persistent local disk with exactly one writer.

### A — One small virtual machine

A single Linux VM. The application, the worker, the proxy, and the database file all on it.

| | |
|---|---|
| **Fit** | **Best.** This is precisely the architecture the application was built for |
| **Persistent disk** | Native, and the default |
| **One writer** | Trivially satisfied |
| **Backups** | Cron plus `scripts/backup_db.py`, and an off-site copy you arrange |
| **TLS** | Your own nginx or Caddy; Caddy does automatic certificates |
| **Operational burden** | **Highest.** OS patching, certificate renewal, monitoring, and backups are all yours |
| **Migration to PostgreSQL later** | Straightforward — install it on the same host or point at a managed one |
| **Main risk** | It is a pet. One host, one disk. Recovery depends entirely on backups that work |

### B — A managed application platform with a persistent volume

A platform that runs a container or buildpack and attaches a persistent volume.

| | |
|---|---|
| **Fit** | **Good, but only if a genuine persistent volume is offered** |
| **Persistent disk** | **The decisive question.** Many such platforms offer only ephemeral filesystems, which would silently destroy the database on every restart |
| **One writer** | Requires pinning to one instance and **disabling autoscaling**. Platforms that scale by default are actively dangerous here |
| **Backups** | Platform snapshots may cover the volume; the application-level backup script is still required, because a volume snapshot is not a verified SQLite copy |
| **TLS** | Usually included and automatic |
| **Operational burden** | **Lowest.** Patching and certificates are handled |
| **Migration to PostgreSQL later** | Usually easiest — most such platforms offer a managed PostgreSQL |
| **Main risk** | A platform default — autoscaling, a rebuild, an ephemeral disk — quietly breaking the single-writer or persistence assumption. **Also: check whether its access logs record full URLs and whether that can be turned off** (DEC-0057, `DEPLOYMENT.md` §3) |

### C — Container host with an attached volume

A container runtime on infrastructure you control, or a managed container service with
block storage.

| | |
|---|---|
| **Fit** | **Workable, and the most portable** |
| **Persistent disk** | An explicitly attached volume; never the container's own filesystem |
| **One writer** | One replica. **Never more**, and the orchestrator must be told so explicitly |
| **Backups** | Yours to arrange, same script |
| **TLS** | An ingress or a proxy container |
| **Operational burden** | **Middle**, and the most moving parts |
| **Migration to PostgreSQL later** | Easy — add a container or a managed instance |
| **Main risk** | Orchestrator defaults. A rolling update that briefly runs two replicas will run two writers against one SQLite file |

### The comparison that matters

| | A — VM | B — Managed platform | C — Containers |
|---|---|---|---|
| Persistent local disk | **Native** | **Verify first** | Attached volume |
| Single-instance guarantee | Trivial | Must be enforced | Must be enforced |
| Operational burden | Highest | Lowest | Middle |
| Patching and TLS | Yours | Theirs | Mixed |
| Access-log control | **Full** | **Verify** | Usually full |
| Path to PostgreSQL | Straightforward | Easiest | Easy |
| Biggest risk | Single host | Silent platform defaults | Orchestrator defaults |

**The recommendation, on architecture alone:** A or B. A is the most predictable and the
best match for the constraints; B is attractive if — and only if — it offers a real
persistent volume, can be pinned to one instance, and lets you control or redact access
logs. C is reasonable if containers are already the house style.

**This is not a selection.** It is the shape of the decision the owner will make once
pricing is checked.

### Non-negotiable requirements for any candidate

Whatever is shortlisted must satisfy all of these, and each is a question to ask the
provider rather than an assumption to make:

- [ ] **A genuinely persistent filesystem**, surviving restart, redeploy, and scaling
- [ ] **Local block storage, not network storage.** SQLite locking on NFS/SMB is unreliable
- [ ] **Ability to run exactly one instance**, with autoscaling off
- [ ] **Ability to run a second long-lived process** (the worker) — or a scheduled task
- [ ] **Control over, or redaction of, access logs** (DEC-0057)
- [ ] TLS with automatic renewal
- [ ] A secret store, or environment files with restrictive permissions
- [ ] Canadian or otherwise acceptable data residency — **an owner/legal decision**
- [ ] A documented backup and restore path for the volume
- [ ] Ability to reach the host for an operator restore

---

## 3. When to leave SQLite

SQLite is not a compromise here; for one small office it is the right choice. But it has
one hard limit and several soft ones.

**Move to PostgreSQL when any of these becomes true.**

| # | Threshold | Why it is the line |
|---|---|---|
| 1 | **More than one application instance needs to write** | SQLite has a single writer. WAL does not change that. This is the hard limit |
| 2 | **A second integration worker is needed** | Same. The claim logic is correct under concurrency but is demonstrated under two sessions, not two processes |
| 3 | **Sustained `database is locked` under normal load** | Contention is no longer brief. Watch the signal in `MONITORING.md` §5.1; raising the busy timeout indefinitely is hiding it, not fixing it |
| 4 | **Backup duration approaches the backup interval** | At development size a backup takes 18 ms. When a backup takes a meaningful fraction of an hour, hourly backups start to overlap |
| 5 | **Database size makes restore time unacceptable** | RPO/RTO is a business question; when restore stops being near-instant, it needs answering |
| 6 | **Reporting interferes with operational writes** | Read replicas are the answer, and SQLite has none. Note the measured headroom below |
| 7 | **High availability or failover is required** | One file on one host cannot provide it |
| 8 | **A second region is planned** | Same |

### What has actually been measured

This is the part worth keeping, because it turns three of those thresholds from opinion
into arithmetic.

| Measure | At 24,000 shipments / 6,000 customers / 48,000 packages | Source |
|---|---|---|
| Full report set | **539 ms median, 564 ms slowest** | `scripts/report_query_review.py` |
| SQL statements per report set | **42**, and **unchanged** when the dataset is halved | Same |
| Peak memory | **13.1 MiB** | Same |
| Backup of the development database | **18 ms** at 0.89 MiB | `scripts/restore_rehearsal.py` |
| Restore and verification | **10 ms / 791 ms** | Same |

The statement count not moving when the data halves is the important one: report queries
are **bucket-bound, not row-bound**, so threshold 6 is further away than it looks.
Reporting load grows with the *period length*, which is capped at 731 days, not with the
number of shipments.

**Threshold 1 is the one to watch.** It is the only hard limit, and it arrives the moment
somebody wants a second instance for availability rather than for load.

### Also required before horizontal scaling

- Move rate limiting out of process memory (DEC-0006) — it is per-process today, so two
  instances would give a caller two allowances
- Sessions are already in the database, so they need no change

---

## 4. PostgreSQL migration plan

**Not performed, and not needed yet.** Written now so the move is an execution task rather
than a design task under pressure.

### Why it is expected to be straightforward

The groundwork was laid deliberately, from Phase 1:

- No SQLite-only column types anywhere
- No SQLite-only SQL in service code — the dashboard buckets dates in Python for exactly
  this reason
- Every schema change is an Alembic migration
- Connection setup is isolated in `app/core/db.py`
- Every timestamp is stored in UTC
- The ORM is SQLAlchemy 2.x, which is dialect-agnostic here

### The plan

**1. Prepare** — Provision PostgreSQL 16+. Create the database, role, and password; put the
password in the secret store. Confirm network reachability and TLS.

**2. Verify the schema builds** — Run `alembic upgrade head` against an **empty**
PostgreSQL database. Every migration must apply cleanly. Fix any dialect assumption here,
where it costs nothing.

**3. Run the test suite against PostgreSQL** — Point `DATABASE_URL` at a scratch PostgreSQL
database and run the full backend suite. This is the real compatibility check, and it will
surface anything step 2 missed.

**4. Rehearse the data copy** — Copy from a **backup**, never from the live database.
Table by table in dependency order, preserving primary keys. Then reset every sequence to
`max(id) + 1` — **the most commonly forgotten step**, and its symptom is a primary-key
violation on the first insert after cutover.

**5. Reconcile** — The same comparison `restore_rehearsal.py` already performs: per-table
counts for customers, shipments, packages, events, tracking references, Solaris IDs,
import batches and audit records, **plus** the relationship fingerprints. Counts alone
would not catch a re-keyed foreign key.

**6. Verify behaviour, not just data** — Sign in; open a customer with Vietnamese
diacritics; confirm a booking; generate a label; run all nine reports and compare every
figure against the SQLite source; export a CSV; look up a public tracking reference.
**Confirm report figures match exactly** — a timezone or collation difference would show
up here and nowhere else.

**7. Cut over** — Stop the worker, then the application. Take a final SQLite backup. Do a
final incremental copy of anything written since step 4. Switch `DATABASE_URL`. Start the
application; confirm `/health/ready`. Start the worker. Smoke test (`DEPLOYMENT.md` §5).

**8. Keep the SQLite file** — Read-only, for at least one full retention period. It is the
only way to answer "what did it say before?"

### What to watch for specifically

| Area | Risk |
|---|---|
| **Sequences** | Not reset after a keyed copy. Immediate primary-key violations |
| **Collation and sorting** | Vietnamese names sort differently. Affects list ordering and any test asserting an order |
| **Case sensitivity** | SQLite `LIKE` is case-insensitive for ASCII by default; PostgreSQL's is not. **Check every search path**, particularly customer search |
| **Booleans** | SQLite stores 0/1; PostgreSQL has a real boolean type. SQLAlchemy handles it, but raw SQL would not |
| **Timestamps** | Everything is UTC already. Do not let `TIMESTAMPTZ` reinterpret naive values on the way in |
| **`PRAGMA` behaviour** | Foreign keys are always enforced in PostgreSQL. A latent violation SQLite tolerated will surface during the copy — **which is a finding, not an obstacle** |
| **Concurrency** | The constraints that forced one writer are gone. Do not assume the rest of the system is ready for many: rate limiting must move out of process memory first |

### What does not change

The worker code, the adapter contract, the report definitions, the export allowlists, the
import transaction boundaries, and the public tracking contract. None of them is
SQLite-specific.

---

## 5. Open decisions

| Decision | Needed from | Blocks |
|---|---|---|
| **Hosting approach and provider** | Owner | Deployment |
| **Pricing** | Owner — **deferred to shortlisting** | A budget |
| **Data residency** | Owner, possibly legal | Provider shortlist |
| **Retention period** | Owner | Backup retention, and any retention deletion |
| **RPO and RTO** | Owner | Backup frequency and the hosting tier |
| **When to move to PostgreSQL** | Driven by §3, but the availability requirement is the owner's | — |
