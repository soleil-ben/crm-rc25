"""SQLite-safe online backup (CRM.md section 3).

Uses the SQLite online backup API, which takes a consistent copy while the application
keeps running. Copying an actively written database file with `cp` is unsafe: in WAL
mode the committed data lives partly in the `-wal` file, so a plain copy can produce a
torn or stale database.

Usage, from the repository root::

    python scripts/backup_db.py                     # writes to backups/
    python scripts/backup_db.py --out /mnt/backups  # custom destination
    python scripts/backup_db.py --keep 30           # prune older copies

The result is verified with `PRAGMA integrity_check` before the run reports success, so
a corrupt copy fails loudly instead of sitting unnoticed until a restore.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "data" / "solaris_crm.db"
DEFAULT_DEST = REPO_ROOT / "backups"


def resolve_source(explicit: str | None) -> Path:
    """Prefer an explicit path, then DATABASE_URL, then the documented default."""
    if explicit:
        return Path(explicit)
    url = os.environ.get("DATABASE_URL", "")
    prefix = "sqlite:///"
    if url.startswith(prefix):
        raw = url[len(prefix) :]
        if raw and raw != ":memory:":
            return Path(raw)
    return DEFAULT_SOURCE


def backup(source: Path, destination_dir: Path) -> Path:
    if not source.exists():
        raise SystemExit(f"Database not found: {source}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = destination_dir / f"solaris_crm-{stamp}.db"

    # Read-only source connection; the online backup API handles WAL correctly.
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

    with sqlite3.connect(target) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        target.unlink(missing_ok=True)
        raise SystemExit(f"Backup failed integrity_check: {result}")

    return target


def prune(destination_dir: Path, keep: int) -> list[Path]:
    if keep <= 0:
        return []
    copies = sorted(destination_dir.glob("solaris_crm-*.db"), reverse=True)
    removed = []
    for stale in copies[keep:]:
        stale.unlink()
        removed.append(stale)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Take a consistent SQLite backup.")
    parser.add_argument("--source", help="Path to the database file.")
    parser.add_argument("--out", default=str(DEFAULT_DEST), help="Destination directory.")
    parser.add_argument(
        "--keep", type=int, default=0, help="Keep only this many newest copies (0 = keep all)."
    )
    args = parser.parse_args(argv)

    source = resolve_source(args.source)
    destination_dir = Path(args.out)

    target = backup(source, destination_dir)
    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"Backup written: {target} ({size_mb:.2f} MB) - integrity_check ok")

    for removed in prune(destination_dir, args.keep):
        print(f"Pruned old backup: {removed}")

    print(
        "\nRestore: stop the application, move the current database aside, copy this file "
        "into place, then run `python -m alembic upgrade head` and verify sign-in."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
