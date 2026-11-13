# Backup and restore

How the database is copied, how a copy is proved usable, and what has and has not
actually been done.

> **Nothing here is deployed.** No off-site storage has been purchased, configured, or
> contacted. No production host exists. The rehearsal recorded below ran on a developer
> workstation against a scratch copy, and that is the only restore this project has ever
> performed.

---

## 1. What was actually rehearsed, and what was not

This distinction is the whole point of the section, so it comes first.

| | Status |
|---|---|
| **Local restore rehearsal against a scratch copy** | **Done.** Measured, reconciled, and repeatable. Section 3 |
| Production disaster-recovery exercise | **Not done, and not claimed.** There is no production host to lose, no off-site copy to fetch, no second machine to restore onto, and no service to bring back for real users |
| Off-site copy | **Not done.** Nothing has been purchased or configured. Section 6 |
| Restore onto a different machine | **Not done.** The rehearsal restored onto the same workstation that made the backup |
| Restore under incident conditions | **Not done.** No timed drill, no on-call person, no degraded infrastructure |
| Encryption at rest or in transit | **Not done.** Requirements are stated in section 5; nothing is configured |

A successful scratch rehearsal proves the backup file is complete and the restore
procedure is correct. It does not prove the business can recover from a disaster, because
every part of a disaster except the database copy is still hypothetical.

---

## 2. Taking a backup

SQLite in WAL mode keeps recently committed data partly in the `-wal` file, so copying
`solaris_crm.db` with `cp` while the application runs can produce a torn or stale
database that still opens. Always use the online backup API.

```bash
backend/.venv/Scripts/python scripts/backup_db.py --keep 30
```

The script opens the source **read-only**, uses `sqlite3.Connection.backup`, then runs
`PRAGMA integrity_check` on the copy and deletes it if the check fails. **A backup that
does not report `integrity_check ok` did not happen.**

`backups/` is git-ignored. No database or backup file is ever committed.

### Frequency — recommendation

| Window | Recommended | Why |
|---|---|---|
| Business hours | **Hourly** | An hour of lost bookings is recoverable from paperwork and staff memory; a day is not |
| Outside business hours | **Nightly** | Write volume is near zero; an hourly job would copy the same bytes repeatedly |
| Before a release or migration | **Always, manually** | The one backup most likely to be needed, and the one most likely to be skipped |

This is a recommendation, not a configured schedule. Nothing runs on a timer today.

### Retention — options, pending the owner's decision

**The retention period is an undecided business decision** (`docs/DECISIONS.md`, and
`PROJECT_STATUS.md` section 9). It is not chosen here, and no retention deletion is
implemented anywhere in the product. These are the options the owner can choose between:

| Option | Local | Off-site | Storage cost driver | Suits |
|---|---|---|---|---|
| **A — minimal** | 7 daily | 4 weekly | Smallest | A business that could reconstruct a week from paperwork |
| **B — conventional** | 30 daily | 12 weekly + 12 monthly | Moderate | The usual small-business default |
| **C — long tail** | 30 daily | 12 weekly + 24 monthly + 7 yearly | Largest | Customs or tax retention obligations that reach back years |

Option B is what `--keep 30` currently implements **locally only**. That is a default in
a script, not a decision: the off-site half of every option above does not exist.

The choice interacts with a question nobody has answered yet — how long shipment and
customs records must legally be kept. `CRM.md` section 11 is explicit that legal
conclusions must not be guessed. Until that is settled, retention is deliberately
over-provisioned locally and undefined off-site.

---

## 3. The rehearsal — measured results

```bash
backend/.venv/Scripts/python scripts/restore_rehearsal.py
```

The script backs up a populated database, restores it into a freshly created scratch
directory, migrates the restored copy to the current head if required, runs structural
checks, and reconciles the restored data against the source. It then removes only the
scratch tree it created. It never writes to, renames, migrates, or deletes
`data/solaris_crm.db`, which it opens read-only.

**Machine context.** Windows 11, AMD64, Python 3.12.10, SQLite 3.49.1, developer
workstation, local SSD. Every figure below is **measured on that machine**. None is an
estimate, and none should be read as a production figure — production hardware, disk, and
database size are all unknown.

### Run A — against the populated development database, 2026-09-14

| Measure | Value | Kind |
|---|---|---|
| Source size | 0.89 MiB (933,888 bytes) | Measured |
| Backup size | 0.89 MiB (933,888 bytes) | Measured |
| Backup elapsed | **0.018 s** | Measured |
| Restore elapsed | **0.010 s** | Measured |
| Verification elapsed | **0.791 s** | Measured |
| Total | **0.819 s** | Measured |
| Alembic head expected / restored | `e5623fcf8018` / `e5623fcf8018` | Measured |
| Upgrade required | No — the copy was already at head | Measured |
| `PRAGMA integrity_check` | `ok` | Measured |
| `PRAGMA foreign_key_check` | clean | Measured |
| Source unchanged after the run | Yes — identical size and mtime to the nanosecond | Measured |

**Reconciliation, Run A**

| Entity | Source | Restored | Result |
|---|---:|---:|---|
| customers | 11 | 11 | match |
| shipments | 27 | 27 | match |
| packages | 48 | 48 | match |
| shipment events | 25 | 25 | match |
| tracking references | 3 | 3 | match |
| Solaris shipment IDs | 25 | 25 | match |
| import batches | 0 | 0 | match — **but see below** |
| audit records | 117 | 117 | match |

**The import-batch line in Run A is a match that proves nothing.** The development
database has never had a customer import committed against it, so both sides are zero.
Zero equals zero regardless of whether the restore would have carried those rows. Run B
exists because of that.

### Run B — against a synthetic fixture where nothing is zero, 2026-09-14

The fixture is the Phase 5A reporting dataset — already awkward on purpose, with drafts, a
cancellation, a cancel-and-rebook pair, a return, a merged customer, and a three-package
two-leg shipment — plus shipment events, an audit trail, and two committed import batches.

| Measure | Value | Kind |
|---|---|---|
| Source size | 0.81 MiB (851,968 bytes) | Measured |
| Backup elapsed | **0.007 s** | Measured |
| Restore elapsed | **0.008 s** | Measured |
| Verification elapsed | **0.634 s** | Measured |
| Total | **0.648 s** | Measured |
| `PRAGMA integrity_check` / `foreign_key_check` | `ok` / clean | Measured |

**Reconciliation, Run B — every entity non-zero**

| Entity | Source | Restored | Result |
|---|---:|---:|---|
| customers | 5 | 5 | match |
| shipments | 12 | 12 | match |
| packages | 3 | 3 | match |
| shipment events | 12 | 12 | match |
| tracking references | 1 | 1 | match |
| Solaris shipment IDs | 11 | 11 | match |
| **import batches** | **2** | **2** | **match** |
| audit records | 18 | 18 | match |

### Relationships, not only counts

Two databases can agree on every count and still disagree about which customer owns which
shipment. Both runs therefore also compare, and both matched:

| Check | What it would catch |
|---|---|
| `public_id_fingerprint` | Every Solaris ID concatenated in order — a renamed or reassigned identifier that leaves the count untouched |
| `shipment_customer_pairs` | Which customer each shipment belongs to |
| `package_parentage` | Which shipment each package belongs to, and its reference |
| `event_spine` | Each event keyed to its shipment and moment |
| `orphan_shipments`, `orphan_packages` | A foreign key pointing at nothing — zero on both sides |

A test (`test_a_corrupted_restore_would_be_noticed`) plants a deliberate shortfall in the
restored counts and asserts the run reports failure, so a passing reconciliation is
evidence that the comparison works rather than evidence that it is lenient.

### Recovery expectations, and what they are worth

| | Figure | Kind |
|---|---|---|
| **RPO** — data at risk between backups | Up to **1 hour** during business hours, up to **12 hours** overnight, under the recommended schedule in section 2 | **Target, not measured.** No schedule runs today |
| **RTO** — time to restore service | Restore and verification measured at **under 1 second** at 0.89 MiB | **Measured, and misleading on its own** |

The measured RTO is the database step only, at development size, on a local SSD. A real
recovery also needs: someone to notice, someone to decide, the host to exist, the
off-site copy to be fetched over a network, the application and worker to start, and a
smoke test to pass. **None of those has been timed, because none of them exists.** Quoting
"under one second" as a recovery-time objective would be dishonest.

Backup duration grows roughly with database size. At development size it is not a
constraint. The point at which it becomes one is a PostgreSQL threshold — see
`docs/HOSTING.md`.

### Restore-testing frequency — recommendation

| When | What |
|---|---|
| **Monthly** | `scripts/restore_rehearsal.py` against the current database. Automated, ~1 second, no excuse to skip |
| **Quarterly** | A restore onto a *different* machine from an *off-site* copy, timed end to end. **Not possible today** — neither exists |
| **After any schema migration** | The rehearsal, to prove the migration applies to a restored copy |
| **After any backup-configuration change** | The rehearsal, plus a check that the new destination is actually receiving files |

---

## 4. Restoring for real

The procedure, for the day it is needed. It has **not** been performed against a
production system, because there is no production system.

1. **Stop the application and the worker.** A restore under a running writer is not a
   restore.
2. **Move the current database aside — do not delete it.**
   `mv data/solaris_crm.db data/solaris_crm.db.broken-$(date -u +%Y%m%dT%H%M%SZ)`
   The broken file is evidence. It is also the only copy of anything written since the
   last backup.
3. **Copy the chosen backup into place** as `data/solaris_crm.db`.
4. **Run the migrations:** `cd backend && .venv/Scripts/python -m alembic upgrade head`.
   A backup taken before a schema change restores at the older revision and must be
   brought forward.
5. **Verify before reopening:** `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and
   the stamped Alembic revision. `scripts/restore_rehearsal.py` does all three against a
   scratch copy — run it against the backup *before* step 3 if there is any doubt.
6. **Start the application**, sign in, open a customer, confirm the dashboard counts, and
   look up one shipment on the public tracking page.
7. **Record what was lost.** Everything written between the backup timestamp and the
   failure is gone. Staff need to know the window so they can re-enter it.

**Never restore over a running application. Never restore onto the live path without
moving the current file aside first.** The rehearsal script refuses both by construction:
it will not write to the live database, anywhere inside the repository, the home
directory, a path outside the scratch root it created, or any file that already exists.

---

## 5. Encryption, access control, and rotation

**None of this is configured.** These are requirements for the deployment, recorded so
the decision is deliberate rather than forgotten.

### Encryption at rest — required

| Layer | Requirement |
|---|---|
| Database volume | Full-disk or volume encryption on the host holding `data/`. SQLite itself is not encrypted; the file is readable by anyone who can read it |
| Backup files | Encrypted before leaving the host. A backup is a complete copy of every customer record, address, and shipment, with none of the application's access controls |
| Key storage | Keys in a secret store or the platform's key service, never beside the data and never in the repository |

The product does **not** implement application-level database encryption (no SQLCipher).
That is a deliberate omission: it would add a key-management burden and an operational
failure mode in exchange for protection that volume encryption already provides against
the realistic threat, which is a lost or improperly disposed disk.

### Encryption in transit — required

| Path | Requirement |
|---|---|
| Staff browser to application | TLS 1.2 or better, terminated at the reverse proxy. `COOKIE_SECURE=true` |
| Public tracking page | Same |
| Host to off-site backup storage | TLS, or an encrypted transport such as SSH. Never plain FTP or unencrypted rsync |
| Operator to host | SSH with key authentication; password authentication disabled |

### Access control

| Control | Requirement |
|---|---|
| Backup directory permissions | Readable only by the service account and the operator. `0700` on the directory, `0600` on the files |
| Off-site credentials | Write-and-list only where the storage supports it, so a compromised application host cannot delete history |
| Who may restore | A named, short list. A restore silently discards everything written since the backup |
| Audit | Every restore recorded in writing: who, when, which backup, what was lost |

### Secure off-site copying

Requirements only — **nothing has been purchased, configured, or contacted.**

- Copies leave the host encrypted and travel over an encrypted transport.
- The destination is a different failure domain from the application host. A second
  directory on the same disk is not an off-site copy.
- The off-site credential cannot delete or overwrite existing objects. Ransomware that
  reaches the application host must not be able to reach backup history.
- Restoring from off-site is exercised quarterly — see section 3.
- The copy is verified after arrival, not assumed. A transfer that reports success and
  writes a truncated file is a normal failure mode.

### Rotation

| Item | Rotation |
|---|---|
| Off-site storage credential | Annually, and immediately on staff offboarding |
| Backup encryption key | Annually. **Old keys must be retained while any backup encrypted under them is still within retention** — a rotated-away key makes those backups unreadable |
| Host SSH keys | Annually, and on offboarding |
| `SECRET_KEY` | On suspicion of exposure and on offboarding. See `docs/OPERATIONS.md` section 2 |

---

## 6. Gates still open

| Gate | Status |
|---|---|
| Local restore rehearsal | **Closed.** Section 3, measured and reconciled |
| Backup schedule actually running | **Open.** Nothing runs on a timer |
| Off-site copy exists | **Open.** Nothing purchased or configured |
| Off-site restore rehearsed | **Open.** Depends on the above |
| Restore onto a second machine | **Open** |
| Encryption at rest configured | **Open** |
| Encryption in transit configured | **Open.** Depends on TLS and the reverse proxy — `docs/DEPLOYMENT.md` |
| Retention period chosen | **Open — owner decision.** Section 2 |
| Production disaster-recovery exercise | **Open.** Not attempted, not claimed |

---

## 7. Related

- `docs/OPERATIONS.md` — day-to-day operations, secrets, the worker
- `docs/RUNBOOKS.md` — failed backup, failed restore verification, low disk space
- `docs/MONITORING.md` — backup age, last successful verification, disk space
- `docs/DEPLOYMENT.md` — TLS, reverse proxy, production configuration
- `docs/HOSTING.md` — when database size makes backup duration a constraint
