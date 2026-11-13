"""Build, inspect and destroy the isolated end-to-end environment (DEC-0112).

One run, one directory, one database, and nothing outside it is ever touched.

    data/e2e/<first 8 of the run id>/
        solaris.e2e.db          the scratch database, migrated and seeded
        solaris.e2e.db-wal      SQLite sidecars
        solaris.e2e.db-shm
        art/                    traces, screenshots, exports, labels, imports
        backend.log             the backend's own output for this run
        vite.log                the dev server's

Short names on purpose: see ``RUN_DIRECTORY_CHARS``. On Windows the full artifact path has
to stay inside ``MAX_PATH``, and it did not the first time.

``data/`` is excluded by ``.gitignore`` at any depth, so every one of those is untracked by
construction rather than by remembering to add a rule.

Why a whole script for this
---------------------------
Because the previous arrangement was "start the stack however you like, then run
Playwright", and on 2026-09-20 that wrote forty customers, thirty-two import batches and a
hundred and ninety-five audit rows into ``data/solaris_crm.db``. ``docs/OPERATIONS.md``
section 10 did say to point the run at a scratch database; it said so in prose, to a human,
who had to remember to export a variable. This replaces the prose with a refusal.

Safety, in the order the checks run
-----------------------------------
1. ``ENVIRONMENT=production`` is refused outright. Nothing here runs against production.
2. The run identifier must be 32 lowercase hex characters. It names a directory and is
   compared over HTTP, so it is validated rather than trusted.
3. The target must pass ``app.core.e2e_guard.e2e_database_problems``: resolved filename
   ending in ``.e2e.db``, inside ``data/e2e/``, not the development database, not inside
   the UAT directory, not inside ``backups/``, not inside the source tree, not a
   directory. Every comparison is on the canonical path, so a symlink or a Windows
   junction is resolved *before* it is checked rather than after.
4. Whatever ``DATABASE_URL`` currently points at is refused by name, canonicalised, so a
   shell that already exports the development database cannot have it reused as a target.
5. ``--destroy`` removes one directory: the one this run identifier names, after that
   directory has itself passed containment. It never walks ``data/e2e/`` looking for
   things to tidy up, so a concurrent run's evidence is not collateral.

What the backend is told
------------------------
``--print-env`` emits the complete environment for the run's backend, which is what
``frontend/scripts/run_e2e.mjs`` starts it with:

* ``ENVIRONMENT=e2e``, which is what turns on the refusals in ``app.core.config`` and
  mounts the handshake in ``app.main``;
* ``DATABASE_URL`` for this run's scratch database;
* ``SOLARIS_E2E_RUN_ID``, which the handshake compares against the marker row written into
  that database;
* the two rate limits the suite needs, applied here rather than left to a developer to
  remember -- see ``E2E_RATE_LIMITS`` below.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/e2e_env.py --new-run-id
    backend/.venv/Scripts/python scripts/e2e_env.py --reset    --run-id <id>
    backend/.venv/Scripts/python scripts/e2e_env.py --check    --run-id <id>
    backend/.venv/Scripts/python scripts/e2e_env.py --print-env --run-id <id>
    backend/.venv/Scripts/python scripts/e2e_env.py --destroy  --run-id <id>
    backend/.venv/Scripts/python scripts/e2e_env.py --list

You are not expected to type any of these. ``npm run e2e --prefix frontend`` does.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

sys.path.insert(0, str(BACKEND_ROOT))

from app.core import e2e_guard  # noqa: E402  (needs the path above)

#: The limits every E2E run gets, applied automatically.
#:
#: These are not a loosening of the product's defaults; they are the settings that make the
#: suite measure what it is trying to measure. The public limiter lives in the backend
#: process and is keyed by client address, and every test in the suite arrives from
#: loopback -- so one browser project replaying a few dozen tracking lookups exhausts a
#: production-sized window and the next project's assertions fail as "element not found",
#: which is really "Too many lookups". Roughly five public-tracking tests failed that way
#: before this was applied automatically.
#:
#: Two things this does not do. It does not change any application default: `config.py`
#: still ships 30 public lookups and 8 login attempts, and nothing here is written to a
#: `.env`. And it does not disable the limiter for the tests that exist to exercise it --
#: `zzRateLimit.spec.js` and the backend's `test_account_rate_limits.py` set their own
#: explicit values and run against a window they chose, which is why the staff and
#: Customer Account limiters stay independently testable.
E2E_RATE_LIMITS = {
    "PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS": "200",
    "LOGIN_RATE_LIMIT_ATTEMPTS": "100",
    # Phase 12. The Customer Account journeys register, verify, sign in and recover
    # several accounts per run, all from one loopback address, against production-sized
    # per-IP windows -- five registrations an hour, five resends, ten sign-ins in five
    # minutes. Left alone, the suite exhausts them part-way through and the remaining
    # specs fail as "element not found", which is really "Too many requests": the same
    # failure the public-tracking limits produced before they were raised here.
    #
    # Only the **per-IP** windows are raised. The per-address ones are left near their
    # defaults, because those are the ones the enumeration and mail-bombing behaviours
    # depend on (T-02, T-11): a spec that registers the same address twice must still meet
    # the real rule. Raising a per-IP window weakens nothing a spec asserts, because no
    # spec asserts anything about how many accounts one address may create.
    "ACCOUNT_REGISTER_IP_ATTEMPTS": "200",
    "ACCOUNT_RESEND_IP_ATTEMPTS": "200",
    "ACCOUNT_SIGNIN_IP_ATTEMPTS": "200",
    "ACCOUNT_RESET_IP_ATTEMPTS": "200",
    "ACCOUNT_TOKEN_IP_ATTEMPTS": "200",
    # Per-address, raised only where one *journey* legitimately repeats an action: a
    # password-reset spec requests a link, uses it, and a later spec may request another
    # for the same account. Still far below "unbounded", and still a real limit.
    "ACCOUNT_RESET_ADDRESS_ATTEMPTS": "20",
    "ACCOUNT_SIGNIN_ADDRESS_ATTEMPTS": "40",
}


class SafetyError(RuntimeError):
    """A path or an environment was refused before anything was created or deleted."""


# --- Paths -------------------------------------------------------------------------


def new_run_id() -> str:
    return secrets.token_hex(16)


def validated_run_id(run_id: str | None) -> str:
    problems = e2e_guard.run_id_problems(run_id)
    if problems:
        raise SafetyError(problems[0])
    assert run_id is not None
    return run_id.strip()


#: How much of the run identifier names the run's directory.
#:
#: Eight characters, not thirty-two, and the reason is Windows. This repository sits inside
#: a OneDrive business folder whose root is already 151 characters, and Playwright builds a
#: directory per failed test under the output directory -- test title, project name, an
#: `attachments` folder and a hashed filename. With `run-<32 hex>/artifacts/` in front of
#: that, the full path passed 260 characters, `MAX_PATH` truncated it, and four CSV export
#: tests failed with `download.createReadStream: canceled` -- a path-length failure wearing
#: the costume of a product defect.
#:
#: `data/e2e/<8 hex>/art` is twenty-one characters, the same as the `frontend/test-results`
#: it replaces, so the suite has exactly the path budget it had before.
#:
#: **The directory name is not the run identifier.** The handshake still compares all
#: thirty-two characters (`app.api.e2e`); this is only what the folder is called. A
#: collision between two eight-character prefixes would mean a new run reusing a preserved
#: failed run's directory, which `create` refuses rather than overwrites.
RUN_DIRECTORY_CHARS = 8


def run_directory(run_id: str) -> Path:
    return e2e_guard.E2E_DIR / validated_run_id(run_id)[:RUN_DIRECTORY_CHARS]


def database_path(run_id: str) -> Path:
    return run_directory(run_id) / f"solaris{e2e_guard.E2E_DB_SUFFIX}"


def artifacts_directory(run_id: str) -> Path:
    return run_directory(run_id) / "art"


def mail_directory(run_id: str) -> Path:
    """Where this run's captured account mail lands.

    Inside the run's own directory, so it is removed with the run and preserved with a
    failed one. The capture transport writes a JSON file per message containing the
    verification or reset **link in plaintext**, which is why it lives here and nowhere
    reachable: there is no HTTP route that returns captured mail in any environment
    (`EMAIL_DELIVERY.md` section 2), and `data/e2e/` is git-ignored at any depth.
    """
    return run_directory(run_id) / "mail"


def database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


# --- Guards ------------------------------------------------------------------------


def refuse_production() -> None:
    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment.startswith("prod"):
        raise SafetyError(
            f"ENVIRONMENT={environment!r}. This script never runs against production."
        )


def _refuse_current_database_url(resolved: Path) -> None:
    """Refuse a target that is what ``DATABASE_URL`` already names.

    The shell that runs the suite may well have the development database exported. That
    is not a reason to refuse the run; it is a reason to refuse *reusing that value as a
    target*, which is the mistake this whole module exists to prevent.
    """
    configured = os.environ.get("DATABASE_URL", "")
    current = e2e_guard.sqlite_path_from_url(configured)
    if current is None:
        return
    try:
        if e2e_guard.canonical(current) == resolved:
            raise SafetyError(
                "That is what DATABASE_URL currently points at. An end-to-end run builds "
                "its own database and never adopts an inherited one."
            )
    except OSError:
        return


def validated_target(path: Path) -> Path:
    """Resolve and check a database target, or refuse it by name."""
    refuse_production()
    problems = e2e_guard.e2e_database_problems(database_url(Path(os.path.abspath(str(path)))))
    if problems:
        raise SafetyError(problems[0] if len(problems) == 1 else "; ".join(problems))
    resolved = e2e_guard.canonical(path)
    _refuse_current_database_url(resolved)
    return resolved


def validated_run_directory(run_id: str) -> Path:
    """The directory ``--destroy`` is allowed to remove, or a refusal.

    Checked independently of the database inside it. A deletion that is only as safe as
    the file it expects to find would be unsafe against a directory holding something
    else, and the point of deleting by run identifier is that the identifier -- not the
    contents -- decides what may go.
    """
    refuse_production()
    directory = run_directory(run_id)
    resolved = e2e_guard.canonical(directory)
    approved = e2e_guard.canonical(e2e_guard.E2E_DIR)

    if resolved == approved:
        raise SafetyError(
            f"{resolved.as_posix()} is the end-to-end root itself. Runs are removed one "
            "directory at a time, never by emptying the root."
        )
    if not e2e_guard.is_within(resolved, approved):
        raise SafetyError(
            f"{resolved.as_posix()} resolves outside {approved.as_posix()}. A symlink or "
            "junction is resolved before this check."
        )
    if resolved.parent != approved:
        raise SafetyError(f"{resolved.as_posix()} is not a direct child of {approved.as_posix()}.")
    if resolved.exists() and not resolved.is_dir():
        raise SafetyError(f"{resolved.as_posix()} exists and is not a directory.")
    return resolved


# --- Build -------------------------------------------------------------------------


def backend_environment(run_id: str) -> dict[str, str]:
    """The complete environment this run's backend is started with."""
    run_id = validated_run_id(run_id)
    return {
        "ENVIRONMENT": e2e_guard.E2E_ENVIRONMENT,
        "DATABASE_URL": database_url(database_path(run_id)),
        e2e_guard.RUN_ID_ENV_VAR: run_id,
        "ALLOW_DEMO_SEED": "true",
        # DEC-0048: the suite runs on loopback with no proxy in front of it, and a
        # forwarding header the limiter believed would let a test choose its own bucket.
        "TRUST_PROXY_HEADERS": "false",
        "TRUSTED_PROXY_HOSTS": "",
        # Human-readable rather than one JSON object per line: this log is read by a person
        # looking at a failed run, not shipped anywhere.
        "LOG_JSON": "false",
        # The capture transport, not the null one. Phase 12's registration, verification
        # and password-reset journeys need the message a real customer would receive, and
        # `null` records that a send was requested and produces nothing to read.
        #
        # It opens no socket, and it is confined to this run: the directory is inside the
        # run's own directory, so it is removed when the run passes and preserved with the
        # evidence when it fails. Nothing here is reachable over HTTP -- the helper that
        # reads it is `tests/e2e/mailCapture.js`, which reads the filesystem.
        "ACCOUNT_EMAIL_TRANSPORT": "capture",
        "ACCOUNT_EMAIL_CAPTURE_DIR": str(mail_directory(run_id)),
        # Python block-buffers stdout when it is a pipe rather than a terminal, and the
        # harness redirects the backend's output to a file. Without this the log lands in
        # 8 KiB chunks, so the last few seconds before a failure -- the only part anybody
        # reads -- are still sitting in the child's buffer when it is killed.
        "PYTHONUNBUFFERED": "1",
        **E2E_RATE_LIMITS,
    }


def _run_backend(args: list[str], run_id: str) -> None:
    """Run a backend module against this run's database, under the E2E guard.

    The subprocess gets ``ENVIRONMENT=e2e`` rather than ``development``, so the migration
    and the seed are held to the same path refusal the server is. A build step that could
    write somewhere the server would refuse to read would be the hole this module exists
    to close.
    """
    env = {**os.environ, **backend_environment(run_id)}
    result = subprocess.run(  # noqa: S603
        [sys.executable, *args], cwd=BACKEND_ROOT, env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"{' '.join(args)} failed with exit {result.returncode}")


def write_marker(path: Path, run_id: str) -> None:
    """Record which run owns this database, inside the database itself.

    Not a migration and not in ``app.models``: the table must exist in an E2E database and
    in no other, so that a process serving a real database answers the handshake with "no
    marker" rather than with somebody else's identifier. ``alembic check`` never sees it
    because it never runs against a scratch database.
    """
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {e2e_guard.RUN_MARKER_TABLE} "  # noqa: S608
            "(run_id TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(f"DELETE FROM {e2e_guard.RUN_MARKER_TABLE}")  # noqa: S608
        connection.execute(
            f"INSERT INTO {e2e_guard.RUN_MARKER_TABLE} (run_id, created_at) VALUES (?, ?)",  # noqa: S608,E501
            (run_id, datetime.now(UTC).isoformat(timespec="seconds")),
        )
        connection.commit()
    finally:
        connection.close()


def read_marker(path: Path) -> str | None:
    if not path.exists():
        return None
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            f"SELECT run_id FROM {e2e_guard.RUN_MARKER_TABLE} LIMIT 1"  # noqa: S608
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return row[0] if row else None


def create(run_id: str, *, reset: bool) -> Path:
    """Migrate and seed a fresh scratch database for this run. Returns its path."""
    run_id = validated_run_id(run_id)
    target = validated_target(database_path(run_id))

    existing = read_marker(target) if target.exists() else None
    if existing is not None and existing != run_id:
        raise SafetyError(
            f"{run_directory(run_id).as_posix()} already holds a database belonging to "
            "another run. That is an eight-character directory-name collision, not a "
            "reason to overwrite somebody's preserved evidence. Remove it deliberately "
            "with --destroy, or start a new run."
        )

    if reset:
        destroy(run_id, quiet=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    artifacts_directory(run_id).mkdir(parents=True, exist_ok=True)

    print(f"[e2e] migrating {target.name}")
    _run_backend(["-m", "alembic", "upgrade", "head"], run_id)

    # `app.seed` calls `random.seed(20260908)` before it builds anything, so volumes,
    # names, dates, amounts and states are identical from one run to the next. The public
    # identifiers are not: they carry a cryptographically random suffix, which is why
    # `tests/e2e/fixtures.js` reads them out of the database rather than hard-coding them.
    print("[e2e] seeding deterministic synthetic data")
    _run_backend(["-m", "app.seed"], run_id)

    # Phase 13D: the workspace prices against an active tariff and an exchange rate. The
    # sanitized Kango fixture and a fixed demo reading (source ``demo://fixture``); no bank
    # or vendor request. The workspace spec builds its own master through the screens.
    print("[e2e] adding the demo tariff and exchange rate")
    _run_backend(["-m", "app.seed_pricing"], run_id)

    write_marker(target, run_id)
    print(f"[e2e] run marker written for {run_id}")
    return target


def _clear_read_only(function, path, _exc_info):  # noqa: ANN001
    """Retry one failed removal after clearing the read-only bit, then give up.

    Windows refuses to unlink a read-only file, and this repository lives inside a
    OneDrive folder whose sync client sets that bit on a file it is mid-upload. The
    retry is narrow on purpose: it changes a permission on a path ``shutil.rmtree`` was
    already walking -- one that ``validated_run_directory`` has already confined to a
    single run's directory -- and it re-raises anything the retry does not fix.
    """
    os.chmod(path, 0o700)
    function(path)


def destroy(run_id: str, *, quiet: bool = False) -> None:
    """Remove exactly one run's directory, and only after it has passed containment."""
    directory = validated_run_directory(run_id)
    if not directory.exists():
        if not quiet:
            print(f"[e2e] nothing to remove at {directory.as_posix()}")
        return

    # A handle can outlive the process that held it by a moment -- SQLite's WAL sidecars
    # and the OneDrive sync client are both capable of it -- so a removal that fails once
    # is retried briefly before it is reported. Three attempts over half a second, then
    # the error, because a cleanup that retried forever would hang a passing run.
    # `\\?\` opts this one call out of `MAX_PATH`. Playwright names a failed test's
    # directory after the test title and then puts an `attachments` folder inside it, so a
    # deep artifact path is ordinary rather than exotic -- and a cleanup that cannot delete
    # what the run created would leave the next run to trip over it. The prefix is applied
    # only after `validated_run_directory` has resolved and confined the path, so it
    # escapes a length limit and nothing else.
    target = (
        f"\\\\?\\{directory}"
        if os.name == "nt" and not str(directory).startswith("\\\\")
        else str(directory)
    )

    last: OSError | None = None
    for attempt in range(3):
        try:
            shutil.rmtree(target, onexc=_clear_read_only)
            if not quiet:
                print(f"[e2e] removed {directory.as_posix()}")
            return
        except OSError as error:  # pragma: no cover - timing dependent
            last = error
            time.sleep(0.2 * (attempt + 1))

    raise RuntimeError(
        f"Could not remove {directory.as_posix()}: {last}. It holds this run's scratch "
        "database and artifacts only, and removing it by hand is safe."
    )


def check(run_id: str) -> int:
    """Confirm the database exists, is at head, holds the marker, and holds seed data."""
    path = database_path(validated_run_id(run_id))
    if not path.exists():
        print(f"No end-to-end database at {path.as_posix()}.", file=sys.stderr)
        return 1

    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        customers = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        shipments = connection.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
    finally:
        connection.close()

    marker = read_marker(path)
    print(f"database : {path.name}")
    print(f"revision : {revision[0] if revision else '<none>'}")
    print(f"marker   : {'matches this run' if marker == run_id else 'MISSING OR WRONG'}")
    print(f"customers: {customers}")
    print(f"shipments: {shipments}")

    if marker != run_id:
        return 1
    if customers == 0 or shipments == 0:
        print("The database is migrated but not seeded.", file=sys.stderr)
        return 1
    return 0


def list_runs() -> int:
    root = e2e_guard.E2E_DIR
    if not root.exists():
        print(f"No end-to-end directory at {root.as_posix()}.")
        return 0
    entries = sorted(p for p in root.iterdir() if p.is_dir())
    if not entries:
        print("No preserved end-to-end runs.")
        return 0
    print(f"Preserved end-to-end runs under {root.as_posix()}:")
    for entry in entries:
        size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
        stamp = datetime.fromtimestamp(entry.stat().st_mtime).isoformat(timespec="seconds")
        print(f"  {entry.name}  {size / 1_048_576:.1f} MiB  last written {stamp}")
    print()
    print("Each is the preserved evidence of a failed run. Remove one with --destroy.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the isolated end-to-end environment.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--new-run-id", action="store_true", help="Print a fresh run identifier.")
    action.add_argument("--create", action="store_true", help="Build it if it is not there.")
    action.add_argument("--reset", action="store_true", help="Destroy and rebuild from scratch.")
    action.add_argument("--check", action="store_true", help="Verify the database and marker.")
    action.add_argument("--destroy", action="store_true", help="Delete this run's directory.")
    action.add_argument("--list", action="store_true", help="List preserved runs.")
    action.add_argument(
        "--print-env", action="store_true", help="Print the backend environment as JSON."
    )
    parser.add_argument("--run-id", default=os.environ.get(e2e_guard.RUN_ID_ENV_VAR))
    args = parser.parse_args(argv)

    if args.new_run_id:
        print(new_run_id())
        return 0
    if args.list:
        return list_runs()

    try:
        run_id = validated_run_id(args.run_id)
        if args.print_env:
            environment = backend_environment(run_id)
            environment["E2E_ARTIFACTS_DIR"] = str(artifacts_directory(run_id))
            print(json.dumps(environment, indent=2, sort_keys=True))
            return 0
        if args.destroy:
            destroy(run_id)
            return 0
        if args.check:
            return check(run_id)

        target = create(run_id, reset=args.reset)
        print(f"[e2e] ready: {target.as_posix()}")
        return check(run_id)
    except SafetyError as refused:
        print(f"Refused: {refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
