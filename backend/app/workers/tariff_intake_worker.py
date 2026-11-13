"""The vendor rate-email folder worker (Phase 13H, OD-76).

**A stand-in for a live mailbox.** No mailbox connection exists (no IMAP, Graph or Gmail,
no credential): a rate email saved as an ``.eml`` file into the intake folder
(``settings.tariff_intake_path``, by default ``data/tariff_intake`` under the repository,
git-ignored) is read here exactly as a staff upload is read. ``--once`` processes every
``*.eml`` directly in the folder and exits; without it the worker repeats every
``--poll-seconds`` and stops cleanly on ``SIGINT``/``SIGTERM``.

Each file is moved after it is read, **never deleted**: to ``processed/`` when the email
was recorded as imported, duplicate or held, and to ``failed/`` when it was refused
(unreadable, too large, rejected, no attachment, or an import error). A second copy of an
email already received is recorded once and moved to ``processed/``; a file whose exact
bytes are already recorded (its move failed last time) is only moved, never audited again.
Symbolic links are skipped; a file that cannot be read or moved is logged and left for the
next run. The worker records where it moved each file, so an approver can reprocess a
``failed`` one. Nothing is activated: a draft waits for the designated approver.

**The ``.eml`` files are the stand-in mailbox itself**: the vendor's original email, as it
would sit in the real mailbox, kept in git-ignored ``data/``. No copy of it is made; a
staff-directory sheet in its workbook is never read from it, and only the stripped workbook
reaches the importer or the held folder.

Logging is categories only: file count and outcomes, never a sender, subject or content.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import signal
import sys
import time
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.db import SessionLocal, commit_with_retry
from app.core.enums import TariffIntakeStatus
from app.core.logging import log_event
from app.models import TariffEmailIntake
from app.services import tariff_intake_service
from app.services.errors import DomainError

logger = logging.getLogger("solaris.tariff_intake_worker")

PROCESSED = "processed"
FAILED = "failed"
_PROCESSED_STATUSES = {
    TariffIntakeStatus.IMPORTED.value,
    TariffIntakeStatus.DUPLICATE.value,
    TariffIntakeStatus.HELD_SENDER.value,
}


def _move(path: Path, folder: Path) -> Path:
    """Move ``path`` into ``folder``, never overwriting a file already there."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    counter = 1
    while target.exists():
        target = folder / f"{path.stem}-{counter}{path.suffix}"
        counter += 1
    shutil.move(str(path), str(target))
    return target


def _already_received(factory: sessionmaker, digest: str) -> TariffEmailIntake | None:
    db: Session = factory()
    try:
        return db.scalar(
            select(TariffEmailIntake).where(TariffEmailIntake.source_sha256 == digest).limit(1)
        )
    finally:
        db.close()


def _process(path: Path, factory: sessionmaker) -> tuple[str, int | None]:
    """One file: its outcome (a status, ``refused``, ``error`` or ``already_received``) and
    the intake row id. A file whose exact bytes were already recorded (a move that failed
    last time) is not ingested or audited again; only the move is retried."""
    if path.stat().st_size > settings.tariff_intake_max_eml_bytes:
        return "refused", None
    raw = path.read_bytes()
    seen = _already_received(factory, hashlib.sha256(raw).hexdigest())
    if seen is not None:
        return "already_received", seen.id
    db: Session = factory()
    try:
        result = tariff_intake_service.ingest_and_commit(db, raw, source="folder", actor=None)
        return result.intake.status, result.intake.id
    except DomainError:
        db.rollback()
        return "refused", None
    except Exception:  # noqa: BLE001 - one file's fault never stops the rest
        db.rollback()
        return "error", None
    finally:
        db.close()


def _record_stored_file(factory: sessionmaker, intake_id: int, relative: str) -> None:
    db: Session = factory()
    try:
        intake = db.get(TariffEmailIntake, intake_id)
        if intake is not None and intake.source == "folder":
            intake.stored_file = relative[:255]
            commit_with_retry(db)
    finally:
        db.close()


def run_once(
    directory: Path | None = None, *, session_factory: sessionmaker | None = None
) -> Counter:
    """Process every ``*.eml`` in the intake folder once. Returns outcome counts.

    Symbolic links are skipped. A file that cannot be read or moved is logged and left for
    the next run; the run goes on with the next file.
    """
    root = Path(directory) if directory else settings.tariff_intake_path
    root.mkdir(parents=True, exist_ok=True)
    factory = session_factory or SessionLocal
    outcomes: Counter = Counter()
    for path in sorted(root.glob("*.eml")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            status, intake_id = _process(path, factory)
        except OSError:
            log_event(logger, logging.WARNING, "tariff_intake_unreadable_file")
            outcomes["unreadable"] += 1
            continue
        outcomes[status] += 1
        if status == "already_received":
            seen_status = _status_of(factory, intake_id)
            folder = PROCESSED if seen_status in _PROCESSED_STATUSES else FAILED
        else:
            folder = PROCESSED if status in _PROCESSED_STATUSES else FAILED
        try:
            target = _move(path, root / folder)
        except OSError:
            log_event(logger, logging.WARNING, "tariff_intake_move_failed", folder=folder)
            continue
        if intake_id is not None and status != "already_received":
            _record_stored_file(factory, intake_id, target.relative_to(root).as_posix())
    log_event(
        logger,
        logging.INFO,
        "tariff_intake_run",
        files=sum(outcomes.values()),
        outcomes=dict(outcomes),
    )
    return outcomes


def _status_of(factory: sessionmaker, intake_id: int | None) -> str | None:
    if intake_id is None:
        return None
    db: Session = factory()
    try:
        intake = db.get(TariffEmailIntake, intake_id)
        return intake.status if intake else None
    finally:
        db.close()


class _Shutdown:
    requested = False

    def install(self) -> None:
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, _signum, _frame) -> None:  # noqa: ANN001
        self.requested = True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solaris CRM vendor rate-email folder worker")
    parser.add_argument("--once", action="store_true", help="Process the folder once and exit.")
    parser.add_argument("--directory", default=None, help="Override the intake folder.")
    parser.add_argument("--poll-seconds", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    directory = Path(args.directory) if args.directory else None
    if args.once:
        outcomes = run_once(directory)
        return 1 if outcomes.get("error") else 0

    shutdown = _Shutdown()
    shutdown.install()
    interval = max(30, args.poll_seconds)
    while not shutdown.requested:
        run_once(directory)
        for _ in range(interval):
            if shutdown.requested:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
