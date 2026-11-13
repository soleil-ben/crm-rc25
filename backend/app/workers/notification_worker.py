"""Milestone notification worker (Phase 13F).

    python -m app.workers.notification_worker --once     # process what is queued, then exit
    python -m app.workers.notification_worker            # loop

Picks up queued notifications and retries failed ones (up to the attempt cap). The request
that records a milestone already dispatches right after it commits; this worker is the safety
net for anything left queued. The only transports are ``null`` and ``capture``: nothing is
sent to a customer (test capture only, OD-72).
"""

from __future__ import annotations

import argparse
import time

from app.core.db import SessionLocal
from app.services import notification_service

POLL_SECONDS = 60


def run_once() -> int:
    # Not wrapped in a retried unit: dispatch commits per row, and re-running it whole after a
    # lock could send a row twice.
    with SessionLocal() as db:
        return notification_service.dispatch_pending(db)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.once:
        print(f"processed {run_once()} notification(s)")
        return 0
    while True:  # pragma: no cover - the loop is the --once body on a timer
        run_once()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
