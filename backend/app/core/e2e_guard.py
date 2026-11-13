"""Where an automated browser run is allowed to write, and how it proves it (DEC-0112).

Phase 10 follow-up. The Playwright staff specs create customers, import batches and audit
rows, and they write them into whichever database the backend they reached is serving. The
suite never chose that database: ``playwright.config.js`` declared no ``webServer``, the
base URL defaulted to ``http://localhost:5173``, and the backend's own ``DATABASE_URL``
defaults to the development database. So "run the suite" meant "write into whatever is
already running", and on 2026-09-20 that was ``data/solaris_crm.db``.

Two separate things had to be true for that to happen, and this module closes both.

**The process must not be able to serve the wrong database.** ``e2e_database_problems``
refuses, at startup, any database that is not an approved scratch file: the resolved
filename must end in ``.e2e.db``, it must sit inside ``data/e2e/``, and the development
database, the UAT directory, the backup directory and the source tree are each refused by
name. Every comparison is on the *canonical* path -- ``os.path.realpath`` resolves symlinks
and Windows reparse points -- and under ``os.path.normcase``, so a junction, a relative
path, or a differently-cased drive letter cannot walk past a string comparison.

**The suite must not be able to reach a different process.** A path check inside the
launcher proves nothing about the server Playwright actually connected to: an already
running development backend answers the same port just as well. So each run mints a random
identifier, hands it to its own backend as an environment variable, writes it into the
scratch database it created, and the suite's global setup asks the server to confirm both
before a single test runs (``app.api.e2e``). Absence, mismatch, or a server that has never
heard of the endpoint all abort the run before anything can authenticate.

The identifier is not a credential. It authorises nothing, unlocks nothing, and the
endpoint that compares it returns a status and no data. It exists to answer one question --
"are you the process this run created?" -- and a wrong answer stops the run rather than
downgrading it.

Nothing here weakens a development or production check. The refusals are additive: they
apply when ``ENVIRONMENT`` is ``e2e``, an environment no deployment uses, and
``production_configuration_problems`` gained a matching refusal in the other direction so a
scratch database cannot be served as production either.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: The two repository roots, computed here rather than imported from ``app.core.config``.
#:
#: ``config`` builds its ``Settings`` at import time, and that build now asks this module
#: whether the environment is ``e2e`` -- so importing the roots from it would be a cycle
#: that fails at interpreter start rather than at the moment the guard is consulted.
#: ``tests/test_e2e_safety.py`` asserts these two are the same paths ``config`` computes,
#: so the duplication cannot drift without a test saying so.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent

#: The one value of ``ENVIRONMENT`` that turns the E2E rules on. Deliberately not
#: ``test``: pytest already runs under ``test`` against per-test temporary databases, and
#: giving the browser suite its own name keeps the two sets of rules from overlapping.
E2E_ENVIRONMENT = "e2e"

#: Every scratch database carries this. A bare ``.db`` in a convenient directory is still
#: a file somebody can mistake for a real one a month later; this makes the throwaway
#: obvious in a file listing, in an error message, and in a code review of a deletion.
E2E_DB_SUFFIX = ".e2e.db"

#: The only directory an E2E database may live in. Inside ``data/``, which ``.gitignore``
#: excludes at any depth, so the database, its WAL and SHM sidecars, and everything the
#: run exports, imports, labels, traces and logs are untracked by construction.
E2E_DIR = REPO_ROOT / "data" / "e2e"

#: Refused by name, canonicalised. This is the file the incident wrote to.
DEV_DB = REPO_ROOT / "data" / "solaris_crm.db"

#: Refused as a directory: everything under it belongs to ``scripts/uat_env.py``.
UAT_DIR = REPO_ROOT / "data" / "uat"

#: Refused as a directory. A backup is the evidence a mistake is recovered from.
BACKUP_DIR = REPO_ROOT / "backups"

#: The environment variable carrying the run identifier. Set by ``scripts/e2e_env.py`` for
#: the backend it starts, and by nothing else.
RUN_ID_ENV_VAR = "SOLARIS_E2E_RUN_ID"

#: The table ``scripts/e2e_env.py`` writes the run identifier into, inside the scratch
#: database it just created. Never created by a migration, so it exists in an E2E database
#: and in no other.
RUN_MARKER_TABLE = "e2e_run_marker"

#: What a run identifier may contain. Hex, fixed length: it is compared, echoed into a
#: refusal message, and used in a directory name, so it is constrained to characters that
#: are safe in all three rather than trusted to be well formed.
RUN_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")


class E2ESafetyError(RuntimeError):
    """A path or an environment was refused before anything was created or deleted."""


def is_e2e_environment(environment: str) -> bool:
    return environment.strip().lower() == E2E_ENVIRONMENT


def canonical(path: Path | str) -> Path:
    """The path with every symlink, junction and ``..`` resolved.

    ``os.path.realpath`` rather than ``Path.resolve`` because on Windows the former
    resolves reparse points -- directory junctions included -- while non-strict resolution
    of a path whose final component does not exist yet can stop short of doing so. A
    scratch database usually does not exist yet, which is exactly when the check matters.
    """
    return Path(os.path.realpath(os.path.abspath(str(path))))


def _norm(value: Path | str) -> str:
    """Case-folded on Windows, untouched on POSIX. Comparison form only, never displayed."""
    return os.path.normcase(str(value))


def is_within(child: Path, parent: Path) -> bool:
    """True when ``child`` sits strictly below ``parent``, comparing whole path segments.

    Segment-wise rather than by string prefix: ``data/e2e-scratch`` starts with
    ``data/e2e`` as text and is a different directory.
    """
    child_parts = Path(_norm(child)).parts
    parent_parts = Path(_norm(parent)).parts
    return child_parts[: len(parent_parts)] == parent_parts and len(child_parts) > len(parent_parts)


def sqlite_path_from_url(database_url: str) -> Path | None:
    """The file a ``sqlite:///`` URL names, or None for any other URL or ``:memory:``."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw = database_url[len(prefix) :]
    if not raw or raw == ":memory:":
        return None
    return Path(raw)


def e2e_database_problems(database_url: str) -> list[str]:
    """Reasons this database must not be served by an E2E backend. Empty means approved.

    Every problem at once rather than the first, so a misconfigured run is fixed in one
    pass, and each message names what was refused without printing the contents of
    anything. The path itself does appear -- it is a local scratch location the operator
    just typed, not a secret, and a refusal that will not say what it refused is a refusal
    nobody can act on.
    """
    problems: list[str] = []

    path = sqlite_path_from_url(database_url)
    if path is None:
        return [
            "DATABASE_URL must name a SQLite file for an E2E run; an in-memory or "
            "non-SQLite URL cannot carry the run marker that proves which run owns it."
        ]

    if not path.is_absolute():
        return [
            f"DATABASE_URL must be an absolute path in the E2E environment; got "
            f"{path.as_posix()!r}. A relative path follows the working directory of "
            "whatever started the process, which is how a run reaches a database it "
            "never chose."
        ]

    resolved = canonical(path)

    if not _norm(resolved.name).endswith(_norm(E2E_DB_SUFFIX)):
        problems.append(
            f"An E2E database filename must end in {E2E_DB_SUFFIX}; {resolved.name!r} does not."
        )

    if resolved.is_dir():
        problems.append(f"{resolved.as_posix()} is a directory, not a database file.")

    if not is_within(resolved, canonical(E2E_DIR)):
        problems.append(
            f"An E2E database must live inside {E2E_DIR.as_posix()}; "
            f"{resolved.as_posix()} resolves outside it. A symlink or junction is "
            "resolved before this check, so pointing one at a database elsewhere does "
            "not satisfy it."
        )

    if resolved == canonical(DEV_DB):
        problems.append(
            "That is the development database. The Phase 10 incident is exactly this "
            "path being served to a browser suite."
        )

    uat = canonical(UAT_DIR)
    if resolved == uat or is_within(resolved, uat):
        problems.append(
            "That is inside the UAT directory. UAT is built and reset by "
            "scripts/uat_env.py and a browser suite must not write into it."
        )

    backups = canonical(BACKUP_DIR)
    if resolved == backups or is_within(resolved, backups):
        problems.append("That is inside the backup directory. A backup is never a test target.")

    source_tree = canonical(BACKEND_ROOT / "app")
    if resolved == source_tree or is_within(resolved, source_tree):
        problems.append("That is inside the application source tree.")

    return problems


def run_id_problems(run_id: str | None) -> list[str]:
    """Reasons the run identifier cannot be used. Empty means usable."""
    if run_id is None or not run_id.strip():
        return [
            f"{RUN_ID_ENV_VAR} is not set. An E2E backend must carry the identifier of "
            "the run that started it, or the suite cannot tell it apart from a server "
            "that was already listening."
        ]
    if not RUN_ID_PATTERN.match(run_id.strip()):
        return [f"{RUN_ID_ENV_VAR} must be 32 lowercase hexadecimal characters."]
    return []


def current_run_id() -> str | None:
    value = os.environ.get(RUN_ID_ENV_VAR)
    return value.strip() if value and value.strip() else None


def e2e_startup_problems(database_url: str, run_id: str | None) -> list[str]:
    """Everything that must be true before an E2E backend is allowed to serve."""
    return [*e2e_database_problems(database_url), *run_id_problems(run_id)]
