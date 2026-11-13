# The browser suite wrote to the development database

**2026-09-20 / 2026-09-21. Closed: Option B executed under owner approval on 2026-09-21.**

Four complete Playwright runs were served `data/solaris_crm.db` instead of a scratch copy.
They added 314 rows to it: 40 customers, 32 import batches, 36 import rows, 195 audit
events and 11 staff sessions. Nothing was deleted, nothing was overwritten, and no customer
was merged.

Investigating that found an older, larger problem: the same thing had been happening since
2026-09-15, and the backup the 314 was measured against was itself already contaminated.
**§11 is the closure record** — 336 rows removed under owner approval, which is a different
number from 314 for reasons set out there. Sections 1 to 10 are left as they were written,
in the order the facts arrived, so the discovery sequence stays legible. Nothing below has
been rewritten to make an earlier estimate look better than it was.

Every timestamp in this record is UTC, because that is what the database stores. Local time
is UTC-4; where it helps, both are given.

No credential, token, tracking reference, customer name, address, email address, phone
number, CSV cell or audit summary appears anywhere in this document or in the difference
report beside it. Row counts, classifications and timestamps only.

---

## 1. What happened, in one paragraph

`playwright.config.js` declared no `webServer`, so the suite never started the stack it
tested. It opened `E2E_BASE_URL`, which defaulted to `http://localhost:5173`, and whatever
was listening there answered. The backend that answered was a development backend, whose
`DATABASE_URL` defaults to `sqlite:///<repo>/data/solaris_crm.db`. The staff specs then did
what they are written to do: signed in, imported CSVs, created customers, exported files.
`docs/OPERATIONS.md` section 10 did say to point the run at a scratch database — in prose,
to a person, who had to remember to export a variable. On four runs, nobody did.

**The root cause is not a mistake in a test.** It is that the harness had no way of knowing
which database it was writing to, because it never started the thing that chose one.

---

## 2. Timeline

| UTC | Local | What |
|---|---|---|
| 2026-09-20 12:34:46 | 08:34:46 | Pre-Phase-10 backup taken: `backups/solaris_crm_pre_phase10_20260920_083446.db`. Revision `b1047733d0e9`; customers 69, import batches 46, audit events 412, user sessions 74. |
| 2026-09-20 13:29:06 | 09:29:06 | **Run 1** signs in. First `auth.login` audit written to the development database. |
| 2026-09-20 13:29:48 → 13:31:24 | 09:29:48 → 09:31:24 | Run 1 writes: 10 customers, 8 import batches, 9 import rows, 49 audit events, 3 sessions. |
| 2026-09-21 00:15:21 → 00:16:41 | 20:15:21 → 20:16:41 | **Run 2** writes the same shape. |
| 2026-09-21 00:22:27 → 00:23:45 | 20:22:27 → 20:23:45 | **Run 3.** |
| 2026-09-21 00:27:14 → 00:28:55 | 20:27:14 → 20:28:55 | **Run 4**, the last write. |
| 2026-09-21 00:31:23 | 20:31:23 | Fresh post-incident backup taken: `backups/solaris_crm-20260921T003123Z.db`. |
| 2026-09-21 00:42 | 20:42 | Development database last written — a WAL checkpoint at clean shutdown, not a data change. See §4. |
| 2026-09-21 00:42:15 | 20:42:15 | Discovered and recorded in commit `7a280b9`, which measured the change against the pre-Phase-10 backup and attempted no repair. |
| 2026-09-21 01:0x | 21:0x | This work begins. Every backend, frontend, worker and test process confirmed stopped; ports 3000, 4173, 5173, 5174, 8000 and 8001 confirmed free; worktree confirmed clean before anything was touched. |

**Four runs, not two.** The count is measured rather than remembered: each staff spec mints
a per-run token and stamps it into every row it writes, and the marked rows fall into four
clusters separated by minutes of silence. Commit `7a280b9` said "roughly a quarter of that
predates this session", which is run 1 — that estimate was right.

### How the stack was started

Not recorded, and this record will not invent it. What is established is what it must have
been for these rows to exist: a backend started **without** `DATABASE_URL` set to a scratch
copy, so `app.core.config` used its default; and `playwright test` run against it. That is
the procedure in `docs/OPERATIONS.md` section 8 with the one optional-looking step omitted.

---

## 3. Evidence preserved before anything was changed

Every database below was opened **read-only** (`file:…?mode=ro`). None was modified, moved,
renamed or deleted, then or since.

| file | SHA-256 | integrity | FK violations | revision | customers | batches | audits |
|---|---|---|---|---|---:|---:|---:|
| `data/solaris_crm.db` (development) | `8cf7823a20d2d899087efbc4ad8cbaff4118a71ce54d4006c6f5457d99b152c6` | ok | 0 | `6af30fcdd3a8` | 109 | 78 | 607 |
| `data/uat/solaris_uat.uat.db` | `d2da806952d0366986c0289000cb30d8e7d0f5e156583b69abc5c00db940c19a` | ok | 0 | — | — | — | — |
| `backups/solaris_crm-20260921T003123Z.db` (post-incident) | `c36944173fc12e75f28e943faa9332f9518f54ae78df31f8af299a00ab773220` | ok | 0 | `6af30fcdd3a8` | 109 | 78 | 607 |
| `backups/solaris_crm_pre_phase10_20260920_083446.db` | `51a3d3310aa7093715bc6e302f896dd4f6d06d8d04207ffb1955001a57e8cd1d` | ok | 0 | `b1047733d0e9` | 69 | 46 | 412 |
| `backups/solaris_crm_pre_phase9_20260920_012738.db` | `e35bf375bc462c8b5dfd64023c656ff88972ebf58cd64d8e958f91e05234cef3` | ok | 0 | `a1c7f4d92b30` | 41 | 24 | 277 |
| `backups/solaris_crm-20260920T014403Z.db` | `df826270d4b6dc692c962ec32c1403f5755f61f07a9d839b423ccc6a17763879` | ok | 0 | `a1c7f4d92b30` | 41 | 24 | 270 |
| `backups/solaris_crm-20260914T015045Z.db` | `831047ea553b44e8cc8e10916392d66633d8283c916cfc846351be14578964ee` | ok | 0 | `c4a1f27b93de` | 11 | 0 | 117 |
| `backups/solaris_crm-20260911T045721Z.db` | `878da29b6d05c76375693914b1ef3ed0cef050e53a5410fae62e3f2faebd042d` | ok | 0 | `9d7dc78dd25c` | 10 | — | 107 |
| `backups/solaris_crm-20260909T225751Z.db` | `6370616300eec81d51dba050e36c91f21f6e0b3121220e9cb467a722779c38e8` | ok | 0 | `6b767a8a58fe` | 10 | — | 100 |
| `backups/solaris_crm-20260908T221314Z.db` | `9969f093d3fa74732672b023bea3aa6aaaebd174208bd4a30a429ac769fe98d5` | ok | 0 | `b39203a50b1e` | 10 | — | 20 |

`PRAGMA integrity_check` returned `ok` and `PRAGMA foreign_key_check` returned no rows for
every one of them. `.gitignore` excludes `*.db`, `data/` and `backups/` at any depth, so
none of these files is committed and none is committed by this work.

**The development database has not changed during this work.** Its SHA-256 was
`8cf7823a…b152c6` when the evidence was taken and is `8cf7823a…b152c6` now; the UAT
database is likewise unchanged at `d2da8069…40c19a`. `backend/tests/test_e2e_safety.py`
asserts both as a property of its own run rather than leaving it to review.

---

## 4. One thing that looks wrong and is not

The post-incident backup and the development database have **identical row counts and
different SHA-256 digests**. The backup was taken at 00:31:23 and the file was last written
at 00:42.

They are logically identical. A full table-by-table comparison of the two — all 46 tables,
by primary key, with a per-row digest over every shared column — reports **0 inserted, 0
deleted, 0 updated**. The byte difference is a WAL checkpoint folded into the main file
when the last connection closed cleanly: SQLite rewrote pages, not data.

This is recorded because the alternative reading — "something wrote to the database after
the backup" — is the reading a person would reasonably reach, and it is wrong.

---

## 5. What changed, and how confidently it is attributed

The full table is in [`2026-09-20-difference-report.md`](2026-09-20-difference-report.md),
regenerated from the databases by `scripts/incident_db_diff.py`, which opens both
read-only. Summary against the pre-Phase-10 backup:

| | rows |
|---|---:|
| inserted | **314** |
| deleted | **0** |
| updated in place | **3** |
| attributed by a per-run marker | 76 |
| attributed by dependent-row closure | 104 |
| attributed by session window | 134 |
| **not attributed** | **0** |

Per table, every table that changed:

| table | before | after | +ins | ~upd | marker | closure | session | unattributed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `customers` | 69 | 109 | 40 | | 40 | | | 0 |
| `import_batches` | 46 | 78 | 32 | | | 32 | | 0 |
| `import_batch_rows` | 52 | 88 | 36 | 36 | | | | 0 |
| `audit_events` | 412 | 607 | 195 | | | 72 | 123 | 0 |
| `user_sessions` | 74 | 85 | 11 | | | | 11 | 0 |
| `users` | 5 | 5 | | 1 | | | | 0 |
| `counters` | 2 | 2 | | 2 | | | | 0 |

The two `users` / `counters` updates are `last_login_at` on the demo administrator and the
public-identifier sequences the 40 new customers consumed. Both are consequences of the
inserts, not independent changes.

### How each class is established

**Marker (76 rows).** Each staff spec mints a token at startup — `E2E<base36>`,
`A11Y<base36>` or `KB<base36>` — and stamps it into every row it writes: appended to
`full_name`, and as the prefix of `source_record_id` for rows created through the CSV
import. All 40 new customers carry one. The four created by typing into the form rather
than by import carry it in the name only, which is why the name is checked as well as the
source key. Nothing else in the application produces that shape: not `app.seed`, not the
UAT fixture in `scripts/uat_env.py`, and not a person unless they typed it deliberately.

**Closure (104 rows).** Rows that carry no token but are reached from one. Every new
`import_batch` has rows, and every row of every one of them points at a marked customer —
"every", not "any", so a batch a person and a test had both written into would be a finding
rather than an attribution. 72 audit events name a marked customer's or a marked batch's
public identifier in `entity_id`.

**Session (134 rows).** Rows that reference no entity at all, so nothing in them can carry
or reach a token: 84 `customer.import_preview` audits (a preview is never persisted), 28
`export.*` audits (an export produces a file, not a row), 11 `auth.login` audits and the 11
sessions those logins created. These are attributed by actor and time — acted as
`admin@demo.example.com`, a reserved demo identity that `app.core.demo_identity` exists to
keep out of production, inside a window the marked rows themselves define. **This is
inference, not proof.** It is reported in its own column and never added to the two above.

It is strong inference. Every one of the 195 new audit events has the demo administrator as
its actor; every one of the 11 new sessions is that account arriving from loopback; and
**there is not one new audit event outside the four run windows**. There is no interleaved
human activity to disentangle, because there was none.

**Unattributed: zero.** Every inserted row is accounted for.

### Dependent-row closure: what is *not* there

No new row exists in `shipments`, `shipment_packages`, `shipment_events`,
`shipment_legs`, `leg_tracking_references`, `booking_confirmations`, `label_print_jobs`,
`follow_up_tasks`, `interactions`, `consent_events`, `contact_suppressions`,
`customer_addresses`, `customer_tags`, `customer_id_aliases`, `saved_segments`,
`referrals`, `service_issues` or `tags`. The 40 customers are childless: they were created
and left alone. That is what makes a targeted deletion a small operation rather than a
cascade — see Option B.

### The Customer Account tables, verified rather than assumed

Commit `7a280b9` stated both Customer Account tables are empty. That was checked directly,
by counting every one of them in the current development database rather than by re-reading
the claim:

`customer_identities` 0, `customer_identity_links` 0, `customer_sessions` 0,
`customer_auth_tokens` 0, `customer_data_proposals` 0, `customer_data_proposal_fields` 0,
`customer_registration_attempts` 0, `customer_terms_acknowledgements` 0,
`customer_notification_preferences` 0, `customer_id_aliases` 0,
`customer_account_approval_attempts` 0, `customer_account_disclosure_acknowledgements` 0.

Twelve tables, all empty, in the backup and in the current database. No identity, no
proposal, no link, no approval, no token and no session was created. `role_merge_provenance`
holds its two rows, unchanged.

Integration tables — `integration_connections`, `integration_jobs`,
`integration_provider_events`, `integration_webhook_inbox`,
`integration_worker_heartbeats` — are all 0 in both, as they have been since Phase 4A.

---

## 6. The finding nobody was looking for

**The pre-Phase-10 backup is not clean either.** 58 of its 69 customers carry the same
per-run tokens.

Tracing the marker through every backup:

| backup | revision | customers | of which marked | genuinely non-test |
|---|---|---:|---:|---:|
| `20260908T221314Z` | `b39203a50b1e` | 10 | 0 | 10 |
| `20260909T225751Z` | `6b767a8a58fe` | 10 | 0 | 10 |
| `20260911T045721Z` | `9d7dc78dd25c` | 10 | 0 | 10 |
| `20260914T015045Z` | `c4a1f27b93de` | 11 | 0 | **11** |
| `20260920T014403Z` | `a1c7f4d92b30` | 41 | 30 | 11 |
| `pre_phase9_20260920_012738` | `a1c7f4d92b30` | 41 | 30 | 11 |
| `pre_phase10_20260920_083446` | `b1047733d0e9` | 69 | 58 | 11 |
| current | `6af30fcdd3a8` | 109 | 98 | **11** |

Two things follow, and both matter for the decision.

1. **The last uncontaminated backup is `solaris_crm-20260914T015045Z.db`**, at revision
   `c4a1f27b93de` — six revisions and three phases behind head. Every later backup already
   contains browser-suite data.
2. **The genuine data has not changed since 2026-09-14.** Eleven customers: ten from
   `app.seed` and one created by hand around 2026-09-13. Not one legitimate customer has
   been created since. The 98 marked rows are the entire difference between then and now.

So this is not a new problem that started on 2026-09-20. 2026-09-20 is when somebody
noticed. The suite has been writing into the development database for as long as the staff
specs have existed, and the earlier occasions were recorded as ordinary validation.

---

## 7. What was changed so this cannot recur

Four changes, and none of them weakens a production or development check.

**The backend cannot serve the wrong database.** `app.core.e2e_guard` refuses, at startup,
any database an E2E backend is pointed at that is not an approved scratch file: the resolved
filename must end in `.e2e.db`, it must sit inside `data/e2e/`, and the development
database, the UAT directory, `backups/` and the source tree are each refused by name. Every
comparison is on the canonical path — `os.path.realpath`, so symlinks and Windows junctions
are resolved *before* the check — and under `os.path.normcase`. The guard runs the other way
too: `production_configuration_problems` now refuses a `.e2e.db`, so a scratch database
cannot be served as production either.

**The suite cannot reach a backend it did not start.** `frontend/scripts/run_e2e.mjs` mints
a random run identifier, gives it to the backend's environment and to a marker row inside
the database that backend serves, and `globalSetup.js` requires the server to confirm both
before any project runs. A development backend has no such endpoint (404). A stale E2E
backend has a different identifier (409). The right process serving the wrong database fails
on the marker (409). Playwright started by hand has no identifier to present and stops with
an explanation. The identifier is not a credential: presenting the right one returns
`{"status":"ok"}` and grants nothing.

**An occupied port is never silently reused.** The harness *binds* the port it wants rather
than probing whether something answers, and an occupied one is either a hard failure or a
controlled move to a port the operating system just allocated. There is no branch that
returns a port something else is holding — a harness that reused the existing server to save
time would be this incident with a comment explaining it.

**The rate limits are applied by the harness.** `scripts/e2e_env.py` puts the documented
E2E limits into the backend's environment itself, so a run cannot be started without them
and then fail public-tracking tests for a reason that looks like a layout bug. No
application default moved: `config.py` still ships 30 public lookups and 8 login attempts,
and the tests that exist to exercise the limiter still set their own explicit values.

One authoritative command, documented in `docs/OPERATIONS.md` section 8:

```bash
npm run e2e --prefix frontend
```

---

## 8. Recovery options

**None of these has been executed.** No row was deleted, no database was restored, no
backup was modified, and the development database is byte-identical to what it was before
this work started. Each option below is a plan and a rollback path, for an owner to choose
between.

### Option A — restore a verified clean backup

**Which backup.** `backups/solaris_crm-20260914T015045Z.db`, revision `c4a1f27b93de`,
SHA-256 `831047ea…8964ee`. It is the newest backup with zero marked rows. The
pre-Phase-10 backup that seems like the obvious choice already holds 58 of them; restoring
it would trade 98 test customers for 58 and call it a repair.

**What would be lost.** Measured by running the same difference report against that backup
rather than estimated. Every row created between 2026-09-14 and now:

| table | in the backup | now | would be discarded | of which test-created | of which **not** |
|---|---:|---:|---:|---:|---:|
| `customers` | 11 | 109 | 98 | 98 | **0** |
| `import_batches` | 0 | 78 | 78 | 78 | **0** |
| `import_batch_rows` | 0 | 88 | 88 | 88 | **0** |
| `audit_events` | 117 | 607 | 490 | 480 | **10** |
| `user_sessions` | 49 | 85 | 36 | 27 | **9** |
| `label_print_jobs` | 1 | 2 | 1 | 0 | **1** |
| `label_print_job_packages` | 2 | 4 | 2 | 0 | **2** |
| `counters` | 1 | 2 | 1 | 0 | **1** |
| | | | **794** | **771** | **23** |

**Twenty-three rows of that are genuine development work**, not test output: a label print
job with its two package links, ten audit events, nine sign-ins and a counter row, all
created while Phases 7 through 10 were built. They are small, and they are the only copy.

**And `role_merge_provenance` does not exist in that backup at all.** The table is created
by revision `a1c7f4d92b30`, which is two revisions after `c4a1f27b93de`. Migrating the
restored copy forward would recreate it — **empty**. Its two rows are the pre-merge roles
Phase 7 captured so that its migration is reversible, and they cannot be reconstructed:
`docs/DECISIONS.md` and `tests/test_migrations_role_merge.py` describe their shape, not
their contents.

**0 legitimate customers would be lost**, because none has been created since 2026-09-13.
That is the one part of this that is free.

**Migrating it forward.** `c4a1f27b93de` → `6af30fcdd3a8` is six revisions and includes
the Phase 9 and Phase 10 migrations. `backend/tests/test_migrations_phase9.py` and
`test_migrations_phase10.py` already exercise that path from both an empty and a populated
database, so it is a tested path rather than a hopeful one.

**Verifying it before anything is replaced.** Copy the backup to
`data/e2e/…/restore-check.e2e.db` — a scratch location the guards already approve — migrate
*that copy* to head, run `alembic check`, `PRAGMA integrity_check`, `PRAGMA
foreign_key_check`, and `scripts/incident_db_diff.py` against the untouched development
database. Nothing touches `data/solaris_crm.db` until every one of those passes.

**Rollback.** `backups/solaris_crm-20260921T003123Z.db` is a verified, logically identical
copy of the current state (§4). Restoring it returns the database exactly to today. The
rollback is one file copy and it has already been proven equivalent.

**Verdict.** Technically sound, and expensive in a way the summary counts hide: it removes
771 rows of test data by also removing 23 rows of real work and emptying
`role_merge_provenance`. Restoring a backup is the safest-sounding option here and the only
one that destroys something irreplaceable.

### Option B — targeted removal of the proven test rows

**Identification predicate.** A customer is in scope when
`full_name GLOB '* E2E[0-9A-Z]*' OR full_name GLOB '* A11Y[0-9A-Z]*' OR full_name GLOB
'* KB[0-9A-Z]*' OR source_record_id GLOB 'E2E[0-9A-Z]*' OR source_record_id GLOB
'A11Y[0-9A-Z]*' OR source_record_id GLOB 'KB[0-9A-Z]*'`. 98 rows match. `GLOB` is
case-sensitive in SQLite and the token is upper case by construction, so a lower-case "kb"
in a genuine note does not match.

**Why no legitimate row can match.** The eleven non-matching customers are the ten
`app.seed` creates and one created by hand on 2026-09-13 — a set small enough to enumerate
and confirm. Every matching row was created between 2026-09-15 and 2026-09-21 by
`admin@demo.example.com` from loopback, and no legitimate customer has been created since
2026-09-13. The claim is not "these look like test rows"; it is "the genuine set is eleven
rows and has not grown".

**Deletion order**, innermost first, so no foreign key is ever left dangling:

1. `import_batch_rows` where `customer_id` is in scope, or `batch_id` is a batch all of
   whose rows are in scope;
2. `import_batches` all of whose rows were removed above;
3. `audit_events` whose `entity_id` is a public id of anything removed above;
4. `customers` in scope.

`user_sessions` are left alone. They expire, they carry no customer data, and deleting a
session row destroys the record of a sign-in for no benefit.

**Dependent-row closure is empty**, which is what makes this small: the 98 customers have no
shipments, packages, events, addresses, tags, aliases, consents, tasks, interactions,
referrals or segments. Nothing cascades.

**Audit treatment.** The 123 session-attributed audit events — previews, exports, logins —
would be **kept**, not deleted. They reference nothing that is being removed, they are the
record of what was done rather than of what exists, and deleting an audit row because the
thing it describes is inconvenient is the habit an audit trail exists to prevent. The 72
that name a removed entity go with it.

**Expected counts afterwards.** customers 109 → 11; import_batches 78 → 0; import_batch_rows
88 → 0; audit_events 607 → 535; user_sessions 85 (unchanged); everything else unchanged.

**Verification.** Perform it on a copy in the approved scratch location first. Then
`PRAGMA foreign_key_check` (zero rows), `PRAGMA integrity_check` (`ok`), `alembic check`,
`scripts/incident_db_diff.py` against `solaris_crm-20260921T003123Z.db` to confirm the
deletions are exactly the intended set and nothing else moved, and a re-count of the twelve
Customer Account tables to confirm they are still empty.

**Rollback.** `backups/solaris_crm-20260921T003123Z.db`, one file copy.

**Eligibility.** A targeted deletion must not be proposed while any affected row is
ambiguous. Zero rows are unattributed, so it is available. That said, 123 of the 195 new
audit events are attributed by inference rather than by marker — and this option does not
delete a single one of them. Every row it removes is marker-attributed or closure-attributed.

### Option C — keep the data and label it

**What it costs, concretely.**

* *Demos.* A customer list of 109 rows, 98 of them ending in a run token
  (`<name> E2E<base36>`), is not a list anybody can show anyone.
* *Duplicate detection.* The import specs deliberately create near-duplicates to exercise
  the duplicate panel. 98 of them sit in the matching corpus permanently, so every future
  import is matched against a pile of synthetic near-misses and the feature cannot be
  judged by hand.
* *Reports.* Route mix, volume and conversion figures are computed over 109 customers of
  which 90% are test rows. Every number on the reports page is meaningless, and it is
  meaningless in a way that looks plausible.
* *Migration measurements.* Any "how long does this migration take on real data" figure is
  now a figure about synthetic data at ten times the real volume.
* *Future tests.* Harmless: the suite no longer touches this database at all.

**How it would be marked.** A row in `PROJECT_STATUS.md` and a note in
`docs/OPERATIONS.md` stating that `data/solaris_crm.db` holds 98 synthetic customers from
browser runs between 2026-09-15 and 2026-09-21, that the genuine set is 11, and that no
figure derived from it is meaningful. The marker predicate above is the definition, so
anyone can recount it.

**When it is acceptable.** If the audit trail of Phases 7 through 10 is worth more than a
usable demo dataset — and it may be, this close to UAT. It costs nothing today and it is
not reversible by waiting: the longer it stands, the more likely somebody quotes a report
figure from it.

---

## 9. Recommendation

**Option B**, and only after an owner approves it.

The reasoning is the evidence, not a preference.

* **Zero rows are unattributed**, which is what makes a targeted deletion permissible at
  all. One ambiguous row and this option would be off the table.
* **Dependent-row closure is empty.** The 98 customers have no shipments, packages, events,
  addresses, tags, aliases, consents, tasks or interactions. The deletion is four statements,
  not a cascade.
* **The genuine customer set is eleven rows and has not grown since 2026-09-13**, so "delete
  what matches, keep the rest" removes nothing anybody wants.
* **It destroys nothing irreplaceable.** Option A, measured properly, discards 23 rows of
  real development work and empties `role_merge_provenance` — the evidence behind a
  documented Phase 7 decision, which cannot be reconstructed. Option B touches none of it.

Option A is the option that *sounds* safest and is the only one that loses something that
cannot be got back. Option C is right only if nobody will demo, report on, or measure
anything against this database before it is replaced — and it gets harder to choose the
longer it stands, because the risk is somebody quoting a figure from it.

**Ambiguous rows: none.** That is the fact the recommendation rests on, and it is the fact
to re-check if anything about this database changes before the decision is made.

---

## 10. What has not been done

*Written before the owner's decision, and true of everything up to it. §11 records what
changed afterwards.*

* No row has been deleted, updated or inserted in `data/solaris_crm.db`. Its SHA-256 is
  unchanged: `8cf7823a20d2d899087efbc4ad8cbaff4118a71ce54d4006c6f5457d99b152c6`.
* No backup has been modified, renamed, moved or deleted.
* The UAT database is unchanged: `d2da806952d0366986c0289000cb30d8e7d0f5e156583b69abc5c00db940c19a`.
* No database, backup or generated artifact is committed.
* `scripts/uat_env.py --reset` was not run. It manages the isolated UAT database and would
  not have restored anything here.

**Any replacement or deletion requires explicit owner approval after this report.**

---

## 11. Closure: Option B, executed 2026-09-21

The owner approved Option B on the corrected report, naming the counts themselves. This
section records what was done, and — because the two numbers people will remember are
different — why 336 rows were deleted when 314 were inserted.

### 11.0 A note on the difference report beside this one

[`2026-09-20-difference-report.md`](2026-09-20-difference-report.md) describes the database
**as it was before the cleanup**, and is left that way deliberately. It is the measurement
the decision was made from. Regenerating it now would produce different numbers and destroy
the evidence, so it has not been and should not be.
[`2026-09-21-post-cleanup-difference-report.md`](2026-09-21-post-cleanup-difference-report.md)
is the separate, after-the-fact view.

### 11.1 Why 336 and not 314

They measure different things, and both are correct.

**314** is the *insertion* count: rows present in the database that were absent from
`backups/solaris_crm_pre_phase10_20260920_083446.db`. It is the answer to "what did the
four runs on 20–21 September add?"

**336** is the *deletion* count: every row in the database that is conclusively the browser
suite's work, whenever it was written. §6 is the reason the two differ — the pre-Phase-10
backup was never a clean baseline. 58 of its 69 customers already carried the suite's
markers, from runs on 2026-09-15 and earlier on 2026-09-20 that had been recorded as
ordinary validation.

| | inserted since the backup | total synthetic | deleted |
|---|---:|---:|---:|
| customers | 40 | 98 | **98** |
| import batches | 32 | 78 | **78** |
| import batch rows | 36 | 88 | **88** |
| audit events, directly attributable | 72 | — | **72** |
| audit events, session-attributed | 123 | — | 0, retained |
| user sessions | 11 | — | 0, retained |
| | **314** | | **336** |

The audit line is the one that does not follow the pattern, and deliberately: the owner
approved exactly the 72 rows whose `entity_id` names a targeted customer or batch, which is
the *directly attributable* set. The 123 previews, exports and logins were attributed by
session window — inference rather than proof — and are retained.

### 11.2 What was deleted

336 rows, in one `BEGIN IMMEDIATE` transaction with `PRAGMA foreign_keys` on throughout,
children before parents: 72 `audit_events`, 88 `import_batch_rows`, 78 `import_batches`,
98 `customers`.

Deleted **by primary key from a frozen manifest**, never by predicate.
`scripts/incident_cleanup.py` explains why at length; briefly, a predicate evaluated at
deletion time answers "what matches now", and what was approved was "these rows, as
measured then". Every row carried a SHA-256 fingerprint and the tool would have rolled back
on a single mismatch. The manifest is not committed: it holds primary keys and public
identifiers.

Before the deletion, the manifest proved — and the tool re-proved inside the transaction —
that none of the 98 customers was referenced by a retained row in any of the **15 tables
with a foreign key into `customers`**, nor by `customers.merged_into_customer_id` in either
direction. Every count was zero. That is what made this four statements rather than a
cascade.

### 11.3 Three updates retained, not reconstructed

Three rows were modified by the affected runs and are **left exactly as they are**:

* `users` — one row, the demo administrator's `last_login_at`;
* `counters` — two rows, the public-identifier sequences the created customers consumed.

Their pre-incident values are not recorded anywhere, and inventing them would be worse than
leaving a known, attributed effect in place. They are documented here as retained test
effects. No `VACUUM` was run and no SQLite sequence was reset, for the same reason.

### 11.4 Residual contamination, reported not repaired

**104 audit events written before the comparison boundary name a customer or batch this
cleanup removed.** They are from the earlier contaminated runs. `audit_events.entity_id` is
free text rather than a foreign key, so there is no integrity violation and
`PRAGMA foreign_key_check` returns clean — but those rows now name entities that no longer
exist.

They were outside the approved set of 72 and were not touched. Recorded here so the next
person to read the audit trail is not surprised by it.

### 11.5 Counts, before and after

| table | before | after |
|---|---:|---:|
| `customers` | 109 | **11** |
| `import_batches` | 78 | **0** |
| `import_batch_rows` | 88 | **0** |
| `audit_events` | 607 | **535** |
| `user_sessions` | 85 | **85**, unchanged |
| `role_merge_provenance` | 2 | **2**, unchanged |

Every other table is unchanged: shipments 27, packages 48, events 25, legs 3, leg packages
9, tracking references 3, booking confirmations 8, label print jobs 2 and their 4 package
links, addresses 10, tags 5, customer tags 9, consents 7, follow-up tasks 7, interactions
10, saved segments 13, referrals 1, service issues 1, route interests 2, users 5,
organization settings 1, counters 2. All twelve Customer Account tables remain empty, and
all five integration tables remain empty.

### 11.6 Verification

* All 336 targeted primary keys are absent.
* All 11 retained customers, all 123 retained session-attributed audit events, all 412
  pre-boundary audit events and all 85 user sessions match their pre-cleanup fingerprints
  exactly — 0 missing, 0 changed.
* `PRAGMA integrity_check` → `ok`; `PRAGMA foreign_key_check` → 0 violations.
* Alembic remains at `6af30fcdd3a8`; `alembic check` reports no new upgrade operations.
* A downgrade to base and re-upgrade to head on an isolated copy restored the schema and
  **restored 2 accounts from `role_merge_provenance`** — which proves those two rows are not
  merely present but still functional.
* `customer_identity_links` is empty, so no effective Customer Account link can point at a
  tombstone.

### 11.7 Backup hashes

| when | file | SHA-256 |
|---|---|---|
| pre-cleanup | `backups/solaris_crm-20260921T033836Z.db` | `c36944173fc12e75f28e943faa9332f9518f54ae78df31f8af299a00ab773220` |
| post-cleanup | `backups/solaris_crm-20260921T034126Z.db` | `14ce155a2910532c3be96baf638182966d7c32c14c1fd0b2dfee6a8dc649532b` |

Both taken with the SQLite online backup API via `scripts/backup_db.py`, both verified
independently for integrity, foreign keys, revision, provenance and complete table counts.
The pre-cleanup backup is byte-identical to `solaris_crm-20260921T003123Z.db`, the one taken
when the incident was discovered — which is itself evidence that nothing touched the
database between discovery and repair.

**No existing backup was modified, renamed, moved or deleted.** There are now ten.

### 11.8 Development database hashes

| point | SHA-256 |
|---|---|
| before the cleanup | `8cf7823a20d2d899087efbc4ad8cbaff4118a71ce54d4006c6f5457d99b152c6` |
| after the cleanup | `ce9519bc6e33c2bd0532db2ec35578612a6e9487cd0215fa40162962695b7539` |

The second value is the one that must now stay put. It was recorded before post-cleanup
validation and again after it, and every suite in that validation ran against an isolated
database. The file size is unchanged at 1,490,944 bytes because no `VACUUM` was run.

### 11.9 A third finding, from trying to confirm the second

The closure checklist asks for a confirmation that **no automated suite opened the
development database**. Checking it rather than asserting it found that one did.

`app/core/db.py` builds its module-level engine from `settings.database_url` at import
time. `backend/tests/conftest.py` set `ENVIRONMENT=test` and left `DATABASE_URL` alone, so
that default was `data/solaris_crm.db` — and every `TestClient(app)` runs the application
lifespan, whose readiness check queries that engine. **The backend suite connected to the
real development database once per app startup, several thousand times a run.**

Nothing was ever written. Two `SELECT`s and a `PRAGMA journal_mode=WAL` against a database
already in WAL, and the file's SHA-256 was byte-identical before and after a full 2,404-test
validation pass. But "it only read it" is the same sentence that would have been true of the
browser suite right up until the moment it was not, and this is the shape of the incident
this whole area exists to prevent.

**How it stayed hidden is the interesting part.** `test_phase5b_startup_and_health.py`
asserts that `/health/ready` reports ready — and that assertion was passing *because* the
engine was reading a database that really was migrated. A health check was being proved
correct against the production-shaped data nobody meant to involve. Point the engine at an
empty file and the test fails, which is why the fix does not simply redirect it:
`conftest.module_engine_database` creates the schema and stamps the migration head in a
temporary database, so readiness answers for a reason of its own.

Worth saying plainly: `test_e2e_safety.py` had been asserting, correctly, that the
development database did not *change* during its run. That assertion was true and it was not
the whole question. It is now paired with
`backend/tests/test_no_suite_opens_the_development_database.py`, which asserts the file is
not opened — by listening on the engine for a connection rather than by reading the
configured URL, so a future change that opened a second connection would fail even if the
URL still looked right.

This was pre-existing, not introduced by the cleanup, and it is fixed rather than recorded.

### 11.10 `uat_env.py` was never used as a repair

It was named as one in `PROJECT_STATUS.md` §21.9 before this work, and that is corrected
there. `scripts/uat_env.py` builds and destroys `data/uat/solaris_uat.uat.db` and refuses by
name any target that is not inside `data/uat/` carrying a `.uat.db` suffix. It was not run
at any point, and `scripts/incident_cleanup.py` refuses the UAT database outright — a
refusal `backend/tests/test_incident_cleanup.py` exercises rather than assumes. The UAT
database is unchanged at
`d2da806952d0366986c0289000cb30d8e7d0f5e156583b69abc5c00db940c19a`.
