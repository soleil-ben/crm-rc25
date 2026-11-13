"""The exchange-rate worker.

A separate process, in the shape of ``integration_worker.py``: ``--once`` makes one
attempt and exits with a code, which is what the tests and the runbook use; continuous
mode repeats every ``FX_POLL_SECONDS`` and stops cleanly on ``SIGINT``/``SIGTERM``. The
request process never fetches a rate inline (CRM.md section 3).

**No unattended service was started during this build.** The v1.5 prototype polled from a
thread inside its desktop server and so only updated while somebody had the window open;
this worker is the replacement, and whether and where it runs is an operations decision
recorded in ``docs/OPERATIONS.md`` when the phase lands.

**Logging is categories only.** Outcome, attempt id, worker name, a bounded error
summary. Never the response body and never a rate value: rates are read from the
database, not from logs.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from app.core.config import settings
from app.core.db import session_scope
from app.core.enums import FxSyncOutcome
from app.core.logging import log_event
from app.services import fx_service

logger = logging.getLogger("solaris.fx_worker")

DEFAULT_WORKER_NAME = "fx-worker-1"


class _Shutdown:
    requested = False

    def install(self) -> None:
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, _signum, _frame) -> None:  # noqa: ANN001
        self.requested = True


def run_once(worker_name: str) -> fx_service.SyncResult:
    with session_scope() as db:
        result = fx_service.sync_once(db, worker_name=worker_name)
    log_event(
        logger,
        logging.INFO if result.outcome == FxSyncOutcome.OK else logging.WARNING,
        "fx_sync_attempt",
        worker_name=worker_name,
        outcome=result.outcome.value,
        error_summary=result.error_summary,
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solaris CRM exchange-rate worker")
    parser.add_argument("--once", action="store_true", help="Make one attempt and exit.")
    parser.add_argument("--worker-name", default=DEFAULT_WORKER_NAME)
    parser.add_argument("--poll-seconds", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.once:
        result = run_once(args.worker_name)
        return 0 if result.outcome == FxSyncOutcome.OK else 1

    shutdown = _Shutdown()
    shutdown.install()
    interval = max(60, args.poll_seconds or settings.fx_poll_seconds)
    log_event(logger, logging.INFO, "fx_worker_started", worker_name=args.worker_name)
    while not shutdown.requested:
        run_once(args.worker_name)
        for _ in range(interval):
            if shutdown.requested:
                break
            time.sleep(1)
    log_event(logger, logging.INFO, "fx_worker_stopped", worker_name=args.worker_name)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
