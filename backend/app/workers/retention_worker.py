"""Retention worker (RC-UAT-21 Phase D, DEC-0233). Never scheduled; run by hand only.

    python -m app.workers.retention_worker --once             # a real run (if switched on)
    python -m app.workers.retention_worker --once --dry-run   # counts only, nothing changed

Does nothing at all while retention deletion is off (the default; OD-01 and OD-36 leave
every period undecided). When an Admin has turned it on, with the owner's approval, it works
only the record classes that are enabled and have a period, in bounded batches, and records
a run row and an audit event. It can never reach invoices, payments, vendor bills or audit
events (``data_retention_service.FORBIDDEN_TABLES``). There is no loop mode: ``--once`` is
required, so nothing can leave it running on a timer by accident.
"""

from __future__ import annotations

import argparse
import json

from app.core.db import SessionLocal
from app.services import data_retention_service


def run_once(*, dry_run: bool, batch_size: int | None = None, session_factory=None) -> dict:
    factory = session_factory or SessionLocal
    with factory() as db:
        if dry_run:
            row = data_retention_service.dry_run(db, trigger="worker")
            db.commit()
            return {"dry_run": True, **data_retention_service.run_view(row)}
        row = data_retention_service.run(db, trigger="worker", batch_size=batch_size)
        if row is None:
            return {"dry_run": False, "status": "disabled", "counts": {}}
        return {"dry_run": False, **data_retention_service.run_view(row)}


def main(argv: list[str] | None = None, *, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args(argv)
    if args.batch_size is not None and not (
        data_retention_service.BATCH_MIN <= args.batch_size <= data_retention_service.BATCH_MAX
    ):
        parser.error("--batch-size is out of range")
    result = run_once(
        dry_run=args.dry_run, batch_size=args.batch_size, session_factory=session_factory
    )
    if result.get("status") == "disabled":
        print("retention deletion is off: nothing was done")
        return 0
    print(
        json.dumps(
            {"status": result["status"], "dry_run": result["dry_run"], "counts": result["counts"]},
            default=str,
        )
    )
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
