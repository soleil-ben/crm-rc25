# Operator runbooks

Eleven incidents, each with the same shape: what you will see, what to check, what to do,
and when to stop and get help.

> **None of these has been executed against a production system, because there is no
> production system.** They are written from the code and from the local rehearsals, and
> they should be walked through once on a staging host before they are relied on.

**Conventions.** `$APP` is the application directory. Commands assume the documented
layout in `README.md`. Where a command writes anything, it says so.

**Two rules that apply to every runbook here:**

1. **Preserve evidence before you fix.** A restart, a retry, or a redeploy usually
   destroys the thing that would have explained the incident. Copy the logs first.
2. **Never restore over a running application**, and never delete the current database
   file. Move it aside.

---

## 1. Application will not start

**You will see** — no `startup_complete` event; `/health/live` unreachable; possibly a
restart loop.

**Check, in this order**

1. **Read the last 50 log lines.** The application refuses unsafe configuration loudly and
   lists *every* problem at once:
   ```
   Refusing to start: 3 unsafe production setting(s).
     - SECRET_KEY is still the development default; generate one
     - COOKIE_SECURE must be true in production
     - ALLOW_DEMO_SEED must be false in production
   ```
   If you see this, the message **is** the diagnosis. Fix all of them and restart.
2. **Timezone.** `The configured timezone ... cannot be resolved` means `tzdata` is missing
   from the image. It is a declared dependency; the image was built without it.
3. **Database path.** `The database directory does not exist` or a path refusal means the
   persistent volume is not mounted. **Do not create the directory to make the error go
   away** — an empty directory on an unmounted volume gives you an empty database and a
   very confusing morning.
4. **Port already in use.** A previous process did not exit. Find and stop it.
5. **Disk full.** See §3.

**Do**

- Fix the named cause, start once, confirm `startup_complete` with `ready: true`, then
  confirm `/health/ready` returns 200.

**Stop and escalate if**

- It restarts more than 3 times in 10 minutes. **Stop the supervisor first.** A crash loop
  overwrites the evidence of its own cause, and every restart makes diagnosis harder.

---

## 2. Database is locked

**You will see** — `OperationalError` in logs; slow or failing writes; possibly a 500.

**Understand first.** SQLite has one writer. `commit_with_retry` absorbs brief contention
with a bounded backoff, so an occasional lock is normal and invisible. What you are
looking at is contention that outlasted the retry budget.

**Check, in this order**

1. **How many application processes are running?** There must be **exactly one**. This is
   the most common cause by a wide margin.
2. **How many workers?** At most one (`docs/OPERATIONS.md` §9).
3. **Is a backup running with `cp` instead of the online API?** A plain file copy holds
   locks and can produce a torn database. Only `scripts/backup_db.py` is safe.
4. **Is there a long-lived read transaction?** A large export or report holds a read while
   it streams. Check for a very large `-wal` that is not shrinking.
5. **Storage latency.** Network storage will do this. SQLite must be on a local disk —
   never on NFS or SMB.

**Do**

- Reduce to one writer. Restart the surplus process.
- If a backup was running with `cp`, stop it and switch to the script.

**Stop and escalate if**

- Locking is sustained under normal load with a single writer. That is not a tuning
  problem, it is **the PostgreSQL gate** — see `docs/HOSTING.md`. Do not paper over it by
  raising the busy timeout indefinitely.

---

## 3. Low disk space

**You will see** — a disk alert; possibly write failures or a failed backup.

**Act before it reaches zero.** A full disk during a write is one of the few ways to
corrupt a SQLite database.

**Check, in this order**

1. **Backup retention.** Almost always the cause. `ls -la backups/` — if there are
   hundreds, pruning is not running. `scripts/backup_db.py --keep 30` prunes as it writes.
2. **Log files.** Not rotated, or a debug level left on.
3. **The `-wal` file.** A large one that never shrinks means a reader is always open, so
   checkpointing never completes.
4. **Anything that is not the application.** Other tenants, OS updates, core dumps.

**Do**

- Prune old backups **after confirming a recent one verifies** (§4). Never delete the only
  good backup to free space.
- Rotate and compress logs.
- If the `-wal` is the problem, a brief restart checkpoints it cleanly.

**Never**

- Delete `solaris_crm.db`, `-wal`, or `-shm`. Deleting the `-wal` of a running database
  discards committed data.

**Stop and escalate if**

- Free space is below 10% and you cannot identify what is consuming it. Growing the volume
  is the safe move; hunting is the risky one.

---

## 4. Backup failed

**You will see** — a non-zero exit from `scripts/backup_db.py`, a stale backup-age alert,
or no new file.

**Understand first.** The script runs `PRAGMA integrity_check` on the copy and **deletes
the copy if it fails**. So a failure means no new backup exists — not that a questionable
one is sitting there.

**Check, in this order**

1. **Run it by hand.** If it succeeds, the schedule is broken, not the backup. Check the
   scheduler, its user, and its environment.
2. **Disk space** on the backup destination — §3.
3. **Permissions** on the backup directory.
4. **`integrity_check` failure on the copy.** This points at the **source**. Go to §5
   immediately: your live database may be damaged.
5. **Source missing.** Check `DATABASE_URL` and that the volume is mounted.

**Do**

- Fix the cause and take a backup immediately, by hand.
- Confirm it reports `integrity_check ok`.
- Verify it restores: `scripts/restore_rehearsal.py`.

**Stop and escalate if**

- Two consecutive backups fail verification while the application is serving normally. The
  source is suspect — §5.

**Say plainly how much is at risk.** Time since the last good backup is the data you would
lose. Tell whoever needs to know, now, not after the restore.

---

## 5. Database integrity check failed

**This is the most serious runbook here. Treat it as data loss until proven otherwise.**

**You will see** — `integrity_check` returning anything but `ok`, or a non-empty
`foreign_key_check`.

**Do this first, before anything else**

1. **Stop the application and the worker.** Every further write makes it worse.
2. **Preserve the current file as evidence.** Copy `solaris_crm.db`, `-wal` and `-shm`
   somewhere else. Do not delete them, do not "repair in place", do not run `VACUUM`.
3. **Find the most recent backup that verifies clean.** Check them newest-first with
   `restore_rehearsal.py --source <backup>`.

**Then**

4. Restore that backup by the procedure in `docs/BACKUP_RESTORE.md` §4.
5. Run `integrity_check`, `foreign_key_check`, and the Alembic revision check on the
   restored copy **before** putting it into service.
6. **Work out what was lost.** Everything between the backup timestamp and the failure.
   Staff need to know the window so they can re-enter it — and customers may have been
   given a Solaris ID that no longer exists in the database.

**Stop and escalate if**

- No backup verifies clean. Do not keep trying restores; preserve everything and get help.
- The corruption recurs after a clean restore. That is storage or hardware, not data.

**Afterwards**

- Record the window, the cause if known, and which records were re-entered. A shipment ID
  that reached a customer or a carrier and no longer exists is an operational problem, not
  just a database one.

---

## 6. Restore verification failed

**You will see** — a non-zero exit from `scripts/restore_rehearsal.py`: a count mismatch, a
relationship mismatch, a failed structural check, or a revision that is not at head.

**Understand first.** This is the rehearsal doing its job. **A restore that fails here
would have failed during an incident**, when there would have been no time to investigate.

**Check by failure type**

| Failure | Means | Do |
|---|---|---|
| `integrity_check` not `ok` | The backup itself is damaged | Try the previous backup. If several are damaged, the source is suspect — §5 |
| `foreign_key_check` not clean | Referential damage | Same. Do not "fix" the rows |
| Revision not at head | The backup predates a migration and the upgrade failed | Read the Alembic output in the report. The migration may not apply to that vintage |
| Count mismatch | **Rows did not survive the copy** | Serious. Do not reuse this backup. Check the source with §5 |
| Relationship mismatch | Counts agree but linkage does not | More serious than a count mismatch. Escalate |

**Do**

- Re-run with `--keep` so the scratch tree survives for inspection, and read the report.
- Take a fresh backup and rehearse *that*, to separate "this backup is bad" from "backups
  are broken".

**Stop and escalate if**

- A fresh backup also fails to restore. The problem is the source or the storage, and you
  currently have **no working recovery path**. Say so plainly and immediately.

---

## 7. Worker heartbeat missing

**Understand first.** **Today this is not an error.** No provider is configured, no worker
runs unattended, and no heartbeat exists. This runbook applies once a worker is supervised.

**You will see** — no heartbeat row, or one older than 3 × the poll interval.

**Check, in this order**

1. **Was a worker ever started?** Absent is different from stale.
2. **Stopped or dead?** A clean shutdown writes a heartbeat with `stopped_at` set. That is
   a stopped worker, not a dead one.
3. **Is the queue actually backing up?** `oldest_pending_job_age_seconds` is the number
   that distinguishes "idle because there is nothing to do" from "frozen". Pending counts
   look identical either way.
4. **Is more than one worker running?** Check distinct `worker_name` values. **Two workers
   against one SQLite file is a standing constraint violation** (`docs/OPERATIONS.md` §9).
5. **Are leases being reclaimed repeatedly?** That means a worker is dying mid-job.

**Do**

- One bounded pass, which is safe and deterministic:
  ```
  backend/.venv/Scripts/python -m app.workers.integration_worker --once
  ```
  Expected with no provider: `claimed=0 succeeded=0 failed=0 reclaimed=0`.
- If a duplicate is running, stop the extras. Killing one mid-job is survivable — the
  lease expires and the next worker reclaims it.
- To stop processing safely: send `SIGTERM`. The worker finishes the job in hand, then
  writes a heartbeat with `stopped_at`.

**Inspecting failed work without exposing payloads**

`GET /api/v1/integrations/jobs?review_only=true`, or Settings → Integration
infrastructure. Both show job id, type, provider key, attempt count, and an **error
category** — never the payload, never a credential, never a tracking reference. That is
deliberate; do not go around it by reading the raw row to "see what happened".

**Stop and escalate if**

- Jobs are failing terminally while no provider is configured. There is nothing for them to
  talk to, so that would mean a defect — §8.

---

## 8. Integration job terminal failure while no provider is configured

**You will see** — `jobs_requiring_review` above zero.

**Understand first.** **This should be impossible right now.** No provider is registered,
the resource allowlist is empty, and nothing enqueues provider work. A terminal failure
here is a signal that something is wrong with the *application*, not with an integration.

**Check**

1. **What enqueued the job?** `job_type` and `provider_key`. A `provider_key` that is not a
   test fake means something registered an adapter — which contradicts DEC-0075 and
   `test_the_production_adapter_registry_is_still_empty`.
2. **Is this a demo or test artefact?** `scripts/integration_worker_demo.py` uses a fake
   adapter and throwaway databases. It should never touch a production database.
3. **`error_code`** is an application category: `retryable`, `rate_limited`,
   `authentication`, `malformed_payload`, `mapping`, `permanent`.

**Do**

- Record it. Do not retry blindly — a retry buys one attempt and will fail the same way.
- If a provider key you do not recognise appears, treat it as a configuration or supply
  chain concern and stop the worker.

**Stop and escalate if**

- Any evidence of an outbound provider request exists. Nothing in this build should make
  one, and several tests exist to prevent it.

---

## 9. Public tracking unavailable

**You will see** — customers reporting the tracking page does not work; 5xx on the public
route; or every lookup returning the generic failure.

**Check, in this order**

1. **Is the whole application down?** §1. Public tracking shares the process.
2. **Is it the rate limiter?** A 429 with `Retry-After` is the limiter working. If
   legitimate customers are being limited, the allowance may be too low for real traffic,
   or a proxy is collapsing every customer into one client key — see §4 below.
3. **Is it one reference or all of them?** One reference failing is a data question, not an
   availability one. Check that the shipment is confirmed and has a public id.
4. **Proxy client-IP collapse.** If `TRUST_PROXY_HEADERS` is false and a proxy sits in
   front, every request arrives from the proxy's address and shares one bucket. This is
   the **single most likely cause of a sudden public rate-limit problem after deployment**.
   The fix is to configure both halves properly (`docs/DEPLOYMENT.md`), not to raise the
   limit.
5. **The frontend build.** The public shell is code-split; a failed deploy can leave the
   staff bundle serving and the public one missing.

**Do**

- If the limiter is misfiring because of proxy configuration, fix the proxy configuration.
- **Do not disable the rate limiter.** It is the only thing standing between the public
  identifier space and enumeration.

**What customers see meanwhile** — a generic, identical failure for every unsuccessful
lookup. That is by design (DEC-0051) and is not a sign that something extra is broken.

**Stop and escalate if**

- The public page is serving data it should not. That is §9 below, not this one.

---

## 10. Accidental disclosure concern

**Applies when** — a customer may have seen another customer's data; an export reached the
wrong person; a log or screenshot may contain personal data; the public page showed
something private.

**Do this first**

1. **Write down what was seen, by whom, when, and how you learned of it.** Before
   investigating. Memory degrades and the timeline matters.
2. **Stop the mechanism.** If it is an export, revoke the recipient's access. If it is a
   page, take it out of service. Containment before diagnosis.
3. **Preserve evidence.** Logs, the exported file if you have it, the audit entries.

**Then check**

1. **The audit log.** Settings → Audit access. Every material change and every export is
   recorded with actor, action, and entity.
2. **Was it actually private?** The public payload is a 24-field allowlist with 45 tests
   behind it. Confirm what was visible rather than assuming the worst or the best.
3. **Scope.** One record or many? One recipient or a list?

**Do not**

- Delete the evidence, including the offending export.
- Tell the affected customer anything before you know what happened.
- Assume a screenshot is the whole story.

**Escalate immediately.** This is an owner decision and possibly a legal one. `CRM.md`
section 11 is explicit that legal conclusions must not be guessed — **do not decide
whether this is reportable**. Bring it to the owner with the facts.

---

## 11. Staff account compromise

**You will see** — sign-ins at implausible times or locations; a spike in failed
sign-ins across accounts; a staff member reporting they did not do something the audit log
says they did.

**Do this first, in this order**

1. **Deactivate the account.** Settings → Staff and permissions. **Sessions are revoked in
   the same transaction**, so this ends access immediately, and the change is audited.
2. **Do not change the password first.** Deactivation is faster and revokes sessions;
   a password change alone may not.
3. **Preserve the audit log** for the suspected window before doing anything else.

**Then**

4. **Read the audit trail** for that actor: what was viewed, changed, exported, merged, or
   released from suppression.
5. **Exports are the highest-value question.** An export is a file of customer data that
   has left the building. Check them specifically.
6. **Check for changes that persist after access ends** — a new staff account, a changed
   permission, a released suppression.
7. **`POST /api/v1/auth/revoke-all`** revokes every session for a user.
8. **Rotate `SECRET_KEY`** if it may have been exposed. Note that sessions are opaque
   random values stored as digests, so rotating the key does **not** invalidate sessions —
   revoke them explicitly.

**Stop and escalate if**

- Any customer data was exported. Treat it as §10 as well.
- More than one account is affected — that suggests credential stuffing or a shared
  password, not a single compromise.

**Afterwards** — MFA is not built (an open gate in `docs/OPERATIONS.md` §6). If this
happens once, that gate has become urgent.

---

## 12. Rollback after a failed release

**You will see** — errors after a deploy; readiness failing on `migrations`; a workflow
that worked yesterday failing now.

**Decide quickly: forward or back?** A small, understood defect can be fixed forward. If
you do not know the cause within a few minutes, go back. Rolling back is cheap; debugging
in production is not.

**The order matters, because of the schema**

1. **Take the instance out of service.** Stop the application and the worker.
2. **Take a backup of the current database, now.** Whatever went wrong, the data written
   since the release is real and is only in this file.
3. **Decide whether the release included a migration.**
   - **No migration** — deploy the previous build. The schema is unchanged and you are
     done after step 5.
   - **Migration, and it is reversible** — downgrade one revision, then deploy the previous
     build. Every migration in this project has a tested downgrade.
   - **Migration, and data has been written under the new schema** — this is the hard case.
     Downgrading may discard that data. **Stop and think** before running it; the backup
     from step 2 is what protects you.
4. **Run the downgrade against a scratch copy first** if there is any doubt:
   ```
   DATABASE_URL="sqlite:///$TMP/rollback-test.db" python -m alembic downgrade -1
   ```
   Never rehearse a downgrade on the live database.
5. **Start the previous build**, confirm `/health/ready` returns 200 with all checks `ok`,
   and run the post-deployment smoke test in `docs/DEPLOYMENT.md`.
6. **Record what was lost**, if anything, and tell staff.

**Never**

- Roll back the application without considering the schema. A previous build against a
  newer schema fails in ways that look like data corruption.
- Delete a migration file to "undo" it. Write a new one.

**Stop and escalate if**

- The downgrade fails, or a rehearsed downgrade loses data you cannot afford to lose.
  Staying on the broken release with a known workaround is sometimes better than an
  unplanned migration under pressure.

---

## Related

`docs/MONITORING.md` · `docs/BACKUP_RESTORE.md` · `docs/OPERATIONS.md` ·
`docs/DEPLOYMENT.md` · `docs/STAFF_GUIDE.md`
