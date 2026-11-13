# 15 — Phase 13H completion record: vendor rate-email intake

**Date:** 2026-10-20 · **Branch:** `phase-13-b2c-merge` · **Base:** fae2b08 (Phase 13G) ·
**Migration:** `c5e8a1f3d7b9` (head), from `b7d2e9a4c1f6` · **Decision:** DEC-0214 ·
**Owner decisions:** OD-76 (D-12) · **Scope:** air only

Nothing is deployed, pushed or merged. **No mailbox is connected**: there is no IMAP, Graph or
Gmail call and no credential anywhere in this phase; nothing is sent to anybody. Test data
only: every test email is built from the sanitized fixture workbook (or an in-test modified
copy) with demo addresses.

## 1. What was built

| Area | Where | What it does |
|---|---|---|
| Tables | `models/tariff_intake.py` (new: `tariff_intake_settings`, `tariff_email_intakes`, `tariff_version_reviews`), migration `c5e8a1f3d7b9` | Approvers, allowed sender domains and the informational mailbox address (one row; readers never write); one row per rate email with its provenance, outcome, draft version and review; the approver's decision per version. Nothing existing altered (DEC-0181) |
| Workbook guard | `pricing/xlsx_guard.py` | Archive-bomb limits from the zip directory; a `DS SDT…` sheet stripped at the zip level, unread, before any hash, store or parse |
| Intake | `services/tariff_intake_service.py` (`ingest_eml`, `ingest_and_commit`) | Reads headers and attachment parts only (`email`, `policy.default`), 15 MB cap, never renders HTML or follows a link; once per Message-ID; exactly one `.xlsx`; an unknown sender's domain is `held_sender`; otherwise the existing importer makes a **draft** (effective date = the email's Date in America/Toronto, label = subject); duplicates by workbook SHA-256; each outcome audited; never activates |
| Diff | `tariff_intake_service.version_diff`, `GET /tariffs/versions/{id}/diff` | Against the active version: air brackets changed/added/removed (per product, zone and band), air surcharge rules changed/added/removed (name, price text, status, basis, scope, unit price), products added/removed, table counts; at most 300 entries per list, counts always complete |
| Approval | `approve`, `reject`, `release`; routes `/tariffs/versions/{id}/approve`, `/reject {reason}`, `/tariffs/intake/{id}/release` | Only a user with `tariff:manage` whose email is in `approver_emails` (default the owner's, OD-76). The existing `POST /tariffs/versions/{id}/activate` now applies the same rule (403 with the reason). Service calls with no actor (seed, demo, e2e) are unchanged. A rejected draft stays `draft` and can never be approved or activated (409) |
| Folder worker | `workers/tariff_intake_worker.py` (`--once`), `settings.tariff_intake_dir` (default `data/tariff_intake`, git-ignored) | Reads `*.eml` from the folder, moves each to `processed/` or `failed/`, never deletes |
| Staff API | `api/v1/routes/tariffs.py`, `schemas/tariff.py` | `POST /tariffs/intake/upload`, `GET /tariffs/intake`, `GET/PATCH /tariffs/intake/settings` (Admin; emails and domains validated); responses carry sender address and subject only, never the body |
| Staff screen | `features/settings/TariffUpdatesPanel.jsx`, Settings → **Tariff updates** (with `tariff:manage`) | Upload an `.eml`; the intake list with statuses; the pending version and its diff; Approve / Reject (with a reason) / Release enabled only for an approver; intake settings for Admin. English and Vietnamese catalogues |
| Tests | `tests/test_tariff_intake.py` (24), `tests/test_tariff_intake_review.py` (15, review fixes), the tester's `tests/test_tariff_intake_golden.py` (18), `frontend/tests/tariffUpdates.test.jsx` (10), `frontend/tests/e2e/staffTariffUpdates.spec.js` | See §3 |
| Adjusted tests | `test_tariff_import.py` (the HTTP activation test makes the demo Admin the approver, fixture `admin_is_tariff_approver` in `conftest.py`), `test_migrations_phase13f.py` (head), `test_quote_offers.py` (its migration test targets 13G's own revision) | Intent unchanged |

## 2. Trying it

Rebuild the demo (`scripts/workspace_demo_env.py --reset`) and start it as in
`11_PHASE_13D_RECORD.md` §2. Sign in as the demo administrator, open **Settings → Tariff
updates**, put the administrator's demo address in **Approvers** and `vendor.example.com` in
**Senders imported without review**, save, then upload an `.eml` whose attachment is a Kango
workbook (for example one built as in `test_tariff_intake.py::build_eml`). The draft appears
with its diff; approve or reject it. Or save the `.eml` into `data/tariff_intake/` and run
`python -m app.workers.tariff_intake_worker --once` from `backend/`.

## 3. Evidence

| Gate | Result |
|---|---|
| Backend (pytest, full) | 4,094 passed, 1 skipped (symlink test: this Windows account cannot create symlinks); 2 failed, the known environmental pair |
| ruff check / format | clean (322 files) |
| eslint, vitest | clean; 648 passed |
| vite build | built |
| Playwright (run alone) | 312 passed |
| Alembic on a scratch database | upgrade head → `c5e8a1f3d7b9`, check clean, downgrade -1, upgrade head |
| Verifiers | every check passed |

Independent tester: 18 black-box golden tests (`test_tariff_intake_golden.py`), no product
defect (one assertion updated on purpose: the kept workbook is now the stripped one).
Independent reviewer: two high (rejection of a manually imported draft; an Admin adding
themselves as approver), four medium and five low findings, all fixed (15 more tests in
`test_tariff_intake_review.py`).

## 4. Stand-ins (unspecified behaviour; the safest choice taken)

| Question | Stand-in |
|---|---|
| **Mailbox** | **No live mailbox connection** -- folder or upload intake until a mailbox connection (provider and credentials) is decided. The mailbox address is stored for information only |
| D-07 / D-09 / V-20 stand-ins | Unchanged by this phase |
| **The `.eml` files in the intake folder** | They are the stand-in mailbox itself: the vendor's original email, in git-ignored `data/`, with the same exposure as the real mailbox (including any staff-directory sheet in its attachment). The worker moves them to `processed/` or `failed/`; **no copy is made**. Only the stripped workbook reaches the importer, the held folder or the database |
| Who is held | Default `allowed_sender_domains` is empty, so every email waits for an approver to release it; exact domain match only (no subdomains) |
| Where a held workbook waits | The **stripped** workbook, in the intake folder's `held/` directory (git-ignored `data/`), never in the database; written to a temporary file before the commit and renamed after; after release it moves to `processed/`. If it is gone, release is refused (409) and an identical re-send restores it |
| An oversized email | Refused before parsing (422 on upload; moved to `failed/` by the worker); no intake row, since nothing was read |
| An email with no Message-ID, or an unreadable file | Its id is `sha256:` of the file, so the same bytes are still received once; an unreadable file (no sender) is `failed` |
| Attachments other than `.xlsx` beside one workbook | Ignored (never opened); only the `.xlsx` is imported |
| Refused vs failed | Refused by rule (no `.xlsx`, several, too large, not a zip container, an archive bomb) is `rejected`; a zip that is not a readable workbook, or an unreadable email, is `failed` |
| Archive-bomb limits | 2,000 parts, 100 MB uncompressed, overall ratio 100, a part over 1 MiB compressed more than 100 times; an XML part with a DTD is refused |
| An implausible Date | More than 60 days from the intake time: the intake date in Toronto is the effective date, with a warning on the row |
| The duplicate key | (Message-ID, sender): another sender reusing the vendor's Message-ID is a separate intake. A file with no sender (unreadable) is keyed by its digest |
| Who changes the approvers | A current approver; scripts without an actor; or, when no current approver is an active Admin (e.g. the owner's default address before the owner has an account), any Admin, audited as a recovery. Sender domains: any Admin with `settings:manage` |
| Reprocessing | An approver may reprocess a `failed` **folder** intake from its kept file in `failed/`; an uploaded email is not kept, so staff upload it again (a new Message-ID or sender is a new intake; the same one answers with the failed row) |
| Two `.xlsx` attachments | `rejected` (which one is the tariff is not guessed) |
| No Date header | The effective date is the intake date in Toronto |
| Rejecting | `TariffVersionStatus` has no rejected state and its table is not altered: the version stays `draft`, the decision is a `tariff_version_reviews` row (for an emailed or a manually imported draft alike), its intake row becomes `rejected`, and approve, the activate route and `activate_version` refuse it (409) |
| Approver rule scope | Route-level only; `activate_version(actor=None)` in seed, demo and e2e scripts is unchanged. An approver must also hold `tariff:manage` (Admin) |
| Settings | At least one approver (an empty list would make every tariff unapprovable); at most 20 approvers and 50 domains |
| The diff | Air only (air products' brackets, HCM and Hà Nội air surcharge sections); zones and beyond-area tables by count only |

## 4a. Independent review and test fixes (2026-10-20)

All eleven findings fixed (DEC-0214, "Review fixes"): rejection by version; approver-list
changes by approvers only (with an audited recovery); archive-bomb limits; held file written
before commit; the staff-directory sheet stripped at the zip level before anything else; the
approve confirmation, diff gating and full diff on the screen; (Message-ID, sender) key with a
concurrent-duplicate answer; a sturdier folder worker; the Date window; reprocessing a failed
folder email; distinct Vietnamese words, labelled server text and named Release buttons.

The tester's `test_tariff_intake_golden.py` changed in one place, because fix 5 changes the
intended behaviour: in `test_a_ds_sdt_sheet_marker_reaches_no_response_db_column_or_derived_file`
the kept file is no longer the raw attachment (`data == raw` became `data != raw`, plus a check
that the kept workbook has no `DS SDT test` sheet). The marker assertions are unchanged.

## 5. Not done

No mailbox connection (OD-76's mailbox is recorded, not read); no scheduled worker (whether
and where `tariff_intake_worker` runs is an operations decision); no notification to the
approver when a draft arrives; sea is not compared (air only); the Vietnamese wording awaits
review by Vietnamese-speaking staff.
