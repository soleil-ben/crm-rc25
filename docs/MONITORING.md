# Monitoring plan

Vendor-neutral. Every signal below can be collected by reading a file, calling an HTTP
endpoint, or running one SQL query, so nothing here commits the business to a monitoring
product before one has been chosen.

> **Nothing is deployed and nothing is being monitored.** No alerting tool has been
> purchased, configured, or connected. This is the plan an operator would implement on the
> day of deployment, not a description of a running system.
>
> **No external telemetry, hosted monitoring, or error-reporting service was added** to
> the application (DEC-0075 sets the deferral; this phase adds no vendor either way).

---

## 1. How to read this

Each signal gives: what is measured, where it comes from, what healthy looks like, when to
warn, when to page, the likely causes, what the operator does immediately, when to
escalate, and what privacy rule applies to the signal itself.

**The privacy column is not decoration.** A monitoring system is a second copy of
production data with weaker access control, and a metric labelled by tracking reference or
customer email would put exactly what `CRM.md` sections 10 and 11 forbid into a vendor's
search index. Every signal below is a count, a duration, an age, or a category.

### Thresholds are starting points

Every number is a **proposed default, not a measured baseline**. No production traffic
exists, so no threshold here has been validated against real behaviour. Review them after
two weeks of real traffic and again after a month.

---

## 2. Because no provider is configured

Three rules apply to the whole plan and are enforced by the application, not by
convention:

| Rule | Why |
|---|---|
| **Provider freshness must remain unavailable.** No "last synchronized" metric exists, and none may be invented | `stale_assignment_count` is `null` by DEC-0065, and no report carries a freshness field (asserted by `test_phase5a_integration_seam.py`) |
| **Provider status must remain `not_configured`** | The production adapter registry is empty; the health endpoint reports it honestly |
| **No alert may imply that provider synchronization should be occurring** | There is nothing to synchronize. An alert on "sync age" would be an alert on a thing that has never existed, and would train an operator to ignore it |

The integration signals below (queue depth, retries, terminal failures, leases, heartbeat)
are all **real and worth collecting** — the infrastructure exists and is correct. They will
simply read zero until a provider is verified in the final phase. That is the expected
value, and an alert should not fire on it.

---

## 3. Availability and correctness

### 3.1 Application availability

| | |
|---|---|
| **Measured** | HTTP reachability of `GET /health/live` |
| **Source** | The application, unauthenticated |
| **Healthy** | 200 `{"status":"ok"}` within 1 s |
| **Warning** | Two consecutive failures, or latency above 2 s |
| **Critical** | Three consecutive failures over 90 s |
| **Likely causes** | Process died; host down; disk full preventing startup; port conflict; reverse proxy misconfigured |
| **Immediate action** | Check the process is running; read the last 50 log lines for `startup_complete` or a configuration refusal; restart |
| **Escalation** | If a restart does not hold for 5 minutes, stop restarting — a crash loop usually means configuration or disk, and repeated restarts hide the evidence. Open `RUNBOOKS.md` §1 |
| **Privacy** | None. The response contains no path, version, environment name, or configuration value |

### 3.2 Readiness failures

| | |
|---|---|
| **Measured** | `GET /health/ready` status, and which named check failed |
| **Source** | The application. Returns 503 and `{"checks": {...}}` with `ok`/`failed` per check |
| **Healthy** | 200, all three of `database`, `migrations`, `timezone` reporting `ok` |
| **Warning** | Any single 503 |
| **Critical** | 503 for more than 60 s, or `migrations: failed` at any time |
| **Likely causes** | `database`: volume not mounted, file permissions, disk full. `migrations`: deployed code newer than the schema — a release that skipped its migration step. `timezone`: `tzdata` missing from the image |
| **Immediate action** | **Take the instance out of the load balancer; do not restart it.** A readiness failure is not fixed by restarting, and a supervisor that restarts on it will loop forever |
| **Escalation** | `migrations: failed` means the release is not safe to serve. Roll back — `RUNBOOKS.md` §11 |
| **Privacy** | Check names only. No path, no revision, no connection string |

> **Liveness and readiness are deliberately different endpoints.** A process whose database
> volume has not mounted is *alive* and must not be restarted; it must stop receiving
> traffic. A supervisor pointed at the wrong one will either restart a healthy process or
> keep sending traffic to a broken one.

### 3.3 Startup failures

| | |
|---|---|
| **Measured** | Absence of a `startup_complete` log event within 30 s of process start; presence of a `Refusing to start:` message |
| **Source** | Application stdout |
| **Healthy** | `startup_complete` once per start, with `ready: true` |
| **Warning** | `configuration_incomplete` events (see §7) |
| **Critical** | `Refusing to start:` — the application deliberately refused unsafe production configuration |
| **Likely causes** | A development `SECRET_KEY`; `COOKIE_SECURE` false; `ALLOW_DEMO_SEED` true; `DEBUG` true; a localhost CORS origin; a non-https tracking URL; half a proxy configuration; a relative or missing database path |
| **Immediate action** | Read the refusal. It lists **every** problem at once, names the variable, and says what is wrong. Fix them all, then restart |
| **Escalation** | None needed — the message is the diagnosis |
| **Privacy** | The refusal names variables, never their values |

### 3.4 HTTP error rate

| | |
|---|---|
| **Measured** | Proportion of `http_request` events with `status_code >= 500`, over 5 minutes |
| **Source** | Structured logs; count by `status_code`, group by `route` |
| **Healthy** | 0% |
| **Warning** | Any 5xx, or 4xx above 20% of requests on a staff route |
| **Critical** | 5xx above 1% over 5 minutes |
| **Likely causes** | An unhandled exception; database locked beyond the retry budget; a migration half-applied |
| **Immediate action** | Group `request_failed` events by `route` and `error_type`. The correlation id joins a user's report to the failure |
| **Escalation** | If one route dominates, that is the change to roll back |
| **Privacy** | `route` is the **template**, never the resolved path — a public tracking path contains the tracking reference, which is why the application logs `/track/{reference:path}` instead |

---

## 4. Abuse and rate limiting

### 4.1 Authentication rate-limit activity

| | |
|---|---|
| **Measured** | Count of 429 responses on `/api/v1/auth/login`, and failed-sign-in count per 5 minutes |
| **Source** | Structured logs, by `route` and `status_code` |
| **Healthy** | Occasional single failures — people mistype passwords |
| **Warning** | More than 20 failures in 5 minutes, or any 429 |
| **Critical** | Sustained 429s for more than 15 minutes, or failures spread across more than 5 distinct accounts |
| **Likely causes** | A staff member locked out; credential stuffing; a misconfigured integration retrying a stale password |
| **Immediate action** | Confirm with the affected staff member before assuming an attack. If it is an attack, the limiter is already doing its job; record it |
| **Escalation** | Distributed failures across many accounts means credential stuffing — `RUNBOOKS.md` §10 |
| **Privacy** | **Never label this metric by email address.** Count failures; do not enumerate accounts into a monitoring system. The audit log already records sign-in events with proper access control |

### 4.2 Public-tracking rate-limit activity

| | |
|---|---|
| **Measured** | Count of 429s on the public tracking route; count of distinct `reference_digest` values per `client_key` |
| **Source** | `public_tracking_lookup` events |
| **Healthy** | Rare 429s. A customer refreshing is normal |
| **Warning** | Sustained 429s from one client key |
| **Critical** | One client key producing many distinct `reference_digest` values — enumeration of identifiers |
| **Likely causes** | A customer refreshing; a scraper; someone walking the identifier space |
| **Immediate action** | The limiter is the control and it is already applied. Record the pattern |
| **Escalation** | If enumeration is sustained, consider a network-level block. Note that the identifier space is 32¹² and unguessable, so enumeration is expensive and unlikely to succeed |
| **Privacy** | **The tracking reference is never logged** (DEC-0057). Only a keyed HMAC digest, which cannot be reversed without the application secret. Do not add the reference to any metric label, ever |

---

## 5. Database

### 5.1 SQLite lock and busy-timeout events

| | |
|---|---|
| **Measured** | Count of `database is locked` occurrences; count of commit retries |
| **Source** | Structured logs (`error_type: OperationalError`) |
| **Healthy** | Zero to a handful per day. `commit_with_retry` absorbs brief contention |
| **Warning** | More than 10 per hour |
| **Critical** | Any request failing *after* the retry budget, or sustained locking under normal load |
| **Likely causes** | A long-running read blocking a write; a second writer process (which must not exist); a backup running against the live file without the online API; slow storage |
| **Immediate action** | Confirm **exactly one** application process and **at most one** worker are running. `RUNBOOKS.md` §2 |
| **Escalation** | Sustained locking under normal load is the **PostgreSQL gate** (`docs/HOSTING.md`), not something to tune away |
| **Privacy** | Counts and categories only. Never log the SQL statement — it carries bound values |

### 5.2 Database integrity

| | |
|---|---|
| **Measured** | `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on the most recent backup |
| **Source** | `scripts/backup_db.py` (integrity) and `scripts/restore_rehearsal.py` (both) |
| **Healthy** | `ok`, and an empty foreign-key list |
| **Warning** | — there is no warning level here |
| **Critical** | **Anything other than `ok`** |
| **Likely causes** | Storage corruption; a copy taken with `cp` instead of the online backup API; abrupt power loss on storage without proper flushing |
| **Immediate action** | **Stop writing.** Take the application out of service, preserve the current file as evidence, and restore from the last backup that verified clean |
| **Escalation** | Immediate. This is data loss until proven otherwise — `RUNBOOKS.md` §5 |
| **Privacy** | Report the result, never the offending rows |

### 5.3 Disk space

| | |
|---|---|
| **Measured** | Free bytes and free percentage on the volume holding `data/`, and on the backup volume |
| **Source** | The host |
| **Healthy** | Above 30% free |
| **Warning** | Below 20% free, **or** less than 5 × the current database size remaining |
| **Critical** | Below 10% free |
| **Likely causes** | Backup retention not pruning; WAL growth under a long-lived reader; log files not rotated |
| **Immediate action** | Check backup retention first — it is the usual cause. `RUNBOOKS.md` §3 |
| **Escalation** | A full disk during a write is how SQLite databases get corrupted. Do not let this reach zero |
| **Privacy** | None |

> The "5 × database size" rule matters more than the percentage. SQLite needs room for the
> WAL, a checkpoint, and a backup copy taken on the same volume.

### 5.4 Database size and growth

| | |
|---|---|
| **Measured** | Size of `solaris_crm.db` plus its `-wal`, weekly |
| **Source** | The host |
| **Healthy** | Growth roughly proportional to shipment volume |
| **Warning** | Growth more than 3 × the trailing month without a matching rise in shipments |
| **Critical** | Size approaching the point where a backup takes longer than the backup interval |
| **Likely causes** | Audit-log growth; a `-wal` that never checkpoints because a reader is always open |
| **Immediate action** | Compare against the shipment count. If the `-wal` is large and not shrinking, look for a long-lived read transaction |
| **Escalation** | The PostgreSQL gate — see `docs/HOSTING.md` |
| **Privacy** | None |

---

## 6. Backup and restore

### 6.1 Backup age

| | |
|---|---|
| **Measured** | Age of the newest file in the backup directory |
| **Source** | The host |
| **Healthy** | Under the backup interval — 1 h during business hours, 12 h overnight |
| **Warning** | More than 2 × the interval |
| **Critical** | More than 24 h |
| **Likely causes** | Scheduled job not running; disk full; permissions; the job failing silently |
| **Immediate action** | Run `scripts/backup_db.py` by hand. If it succeeds, the schedule is broken, not the backup |
| **Escalation** | **A silent backup failure is the classic root cause of a bad restore.** Treat a stale backup as urgent even while everything else looks fine — `RUNBOOKS.md` §4 |
| **Privacy** | Age and size only. Never list backup filenames into a third-party system if they encode anything but a timestamp |

### 6.2 Last successful backup verification

| | |
|---|---|
| **Measured** | Whether the most recent backup reported `integrity_check ok` |
| **Source** | `scripts/backup_db.py` exit status and output |
| **Healthy** | Every backup verifies |
| **Warning** | One failure |
| **Critical** | Two consecutive failures, or any failure that also deleted its output |
| **Likely causes** | Source corruption; storage error; disk full mid-write |
| **Immediate action** | The script deletes a copy that fails, so a failure means **no new backup exists**. Check §5.2 on the live database immediately |
| **Escalation** | A failing verification on a healthy source points at storage |
| **Privacy** | None |

### 6.3 Failed restore verification

| | |
|---|---|
| **Measured** | Exit status of `scripts/restore_rehearsal.py`, run monthly |
| **Source** | The rehearsal script |
| **Healthy** | Exit 0: integrity ok, foreign keys clean, revision at head, every count and relationship reconciled |
| **Warning** | — |
| **Critical** | **Any non-zero exit** |
| **Likely causes** | A backup that verified but does not restore; a migration that cannot apply to an older copy; a reconciliation mismatch indicating silent data loss |
| **Immediate action** | Do not overwrite the backup set. Run it again with `--keep` and inspect the scratch tree |
| **Escalation** | Immediate. **A restore that fails in rehearsal would have failed in an incident** — `RUNBOOKS.md` §6 |
| **Privacy** | The rehearsal reports counts and fingerprints, never row contents |

---

## 7. Integration infrastructure

**All of these read zero today, and that is correct.** No provider is configured. They are
listed because the infrastructure is real and will need watching the moment a provider is
verified — not because anything is expected to happen now.

**No alert in this section may imply that synchronization should be occurring.**

| Signal | Measured | Healthy today | Warning | Critical | Immediate action | Privacy |
|---|---|---|---|---|---|---|
| **Job queue depth** | `oldest_pending_job_age_seconds` from the health API | `null` — nothing queued | Any value above 300 s | Above 900 s | **This is the number that reveals a stopped worker.** Pending counts look identical whether work flows or is frozen; age does not | Counts and ages only |
| **Job retry count** | Jobs with `attempt_count > 1` | 0 | More than 10% of jobs retrying | More than 25% | Group by `error_code` — a category, never a provider message | `error_code` is an application category |
| **Terminal failures** | `jobs_requiring_review` | 0 | Any value above 0 | Above 5, or rising | Review in Settings → Integration infrastructure. `RUNBOOKS.md` §7 | Never log the payload |
| **Expired / reclaimed leases** | Count of `integration_worker_reclaimed_expired_leases` events | 0 | More than 3 per hour | Sustained reclaiming | Repeated reclaiming means a worker is dying mid-job, or two workers are running | Worker name and count |
| **Worker heartbeat age** | Age of the newest heartbeat row | No heartbeat — no worker runs. **Not an error today** | Older than 3 × poll interval, *once a worker is supervised* | Older than 15 min with jobs pending | Distinguish stopped from dead: a clean shutdown writes `stopped_at` | Worker name only |
| **Duplicate workers** | Distinct `worker_name` values heartbeating | 0 | **More than 1** | More than 1 with lock contention | **Run exactly one.** `RUNBOOKS.md` §7 | Worker name only |

---

## 8. Process and application health

### 8.1 Process restarts

| | |
|---|---|
| **Measured** | Count of `startup_complete` events per hour |
| **Source** | Structured logs |
| **Healthy** | One per deployment |
| **Warning** | More than 2 per hour outside a deployment |
| **Critical** | More than 5 per hour — a crash loop |
| **Likely causes** | Out of memory; the supervisor restarting on a readiness failure it should not restart on; a configuration refusal |
| **Immediate action** | **Stop the restart loop first**, then read the logs. A loop overwrites the evidence of its own cause |
| **Escalation** | `RUNBOOKS.md` §1 |
| **Privacy** | None |

### 8.2 Import failures

| | |
|---|---|
| **Measured** | Count of import commits that returned an error; count of rejected files |
| **Source** | Structured logs and `import_batches` |
| **Healthy** | Rejections are normal — operators upload the wrong file sometimes |
| **Warning** | Repeated failures of the same file |
| **Critical** | A commit that failed **partway** |
| **Likely causes** | Malformed CSV; encoding; row or size limits; a genuine bug |
| **Immediate action** | A commit is one transaction (DEC-0079) — a failure leaves **no** customer and no batch row. Confirm the customer count is unchanged |
| **Escalation** | If a partial commit ever appears, that is a serious defect: stop imports and investigate |
| **Privacy** | **Never log a CSV cell.** Row numbers and error categories only |

### 8.3 Export failures

| | |
|---|---|
| **Measured** | Non-200 responses on `/api/v1/exports/*` |
| **Source** | Structured logs by `route` and `status_code` |
| **Healthy** | 403s are normal and correct — the allowlist refusing an unauthorized role is the control working |
| **Warning** | 5xx on any export |
| **Critical** | A 200 export by a role that should not have it |
| **Likely causes** | 5xx: a large export timing out. 200-by-wrong-role: a permission regression |
| **Immediate action** | For a permission surprise, check the audit log and `test_exports.py` |
| **Escalation** | A wrongly authorized export is a privacy incident — `RUNBOOKS.md` §9 |
| **Privacy** | Never log the exported rows or the filter values |

### 8.4 Unexpected audit-write failures

| | |
|---|---|
| **Measured** | Any error raised while writing an `audit_events` row |
| **Source** | Structured logs |
| **Healthy** | Zero |
| **Warning** | — |
| **Critical** | **Any occurrence** |
| **Likely causes** | Disk full; database locked beyond retry; schema drift |
| **Immediate action** | The audit trail is how a merge, a suppression release, or an export is later explained. A material change that happened without its audit row is a gap in the record — capture what is known now, by hand, while it is still known |
| **Escalation** | Immediate, and record the window during which auditing may have been incomplete |
| **Privacy** | Audit rows already redact secrets and personal values. Do not copy their `detail_json` into a monitoring system |

---

## 9. What to collect, and what to leave off

### Safe to collect

Counts, rates, durations, ages, sizes, percentages; HTTP status codes; **route templates**;
application error categories; correlation ids; keyed reference digests; worker names; job
ids and job types; internal integer entity ids.

### Never collect

Customer names, addresses, email addresses, phone numbers; internal notes; CSV cell
contents; **tracking references** (Solaris or carrier) in any form other than the keyed
digest; bearer, session, or CSRF tokens; integration credentials; complete request or
response bodies; resolved URL paths for public tracking; SQL statements with bound values;
rendered exception messages.

The application enforces most of this at the logging boundary — a field survives only if
its name is on an allowlist, our own loggers may emit only event names, and vocabulary
fields are constrained. But **a monitoring system can add labels of its own**, and nothing
in the application can stop that. Review metric labels before shipping them anywhere.

### Access-log redaction is a separate, unclosed gate

The **reverse proxy** writes its own access log, and the application cannot filter it. A
public tracking request is `GET /api/v1/public/track/SX-CAV-XXXXXXXX`, so the proxy's log
records the tracking reference unless it is configured not to. This is an open production
gate (DEC-0057), and `docs/DEPLOYMENT.md` carries the configuration.

---

## 10. Suggested review cadence

| When | What |
|---|---|
| Daily | Availability, error rate, backup age |
| Weekly | Disk free, database growth, rate-limit activity, import and export failures |
| Monthly | Run `restore_rehearsal.py`; review thresholds against actual behaviour |
| Quarterly | Restore from an off-site copy onto a different machine, timed |
| After any release | Readiness, error rate, and process restarts for the first hour |

---

## 11. Related

`docs/RUNBOOKS.md` · `docs/BACKUP_RESTORE.md` · `docs/OPERATIONS.md` ·
`docs/DEPLOYMENT.md` · `docs/HOSTING.md`
