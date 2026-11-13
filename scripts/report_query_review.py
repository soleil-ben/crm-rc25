"""Measure the Phase 5A reports against a realistic synthetic dataset.

Phase 5A left one open question, recorded as known limitation 4: reports are computed on
request with no caching, which is correct and honest and was only ever measured against a
seeded database of a few dozen rows. This answers the question with numbers instead.

**The target is stated before the measurement**, because a target chosen afterwards is a
description rather than a target:

    A report set must render in under 1000 ms at the documented dataset size, and no
    single report may exceed 500 ms. Caching is warranted only if that is missed.

What is measured
----------------
* wall-clock time per report, and for the whole set;
* the number of SQL statements each report issues, counted by a driver-level hook;
* whether statement counts grow with the number of *rows* -- a per-row query -- or only
  with the number of *buckets*, which the granularity rule bounds;
* peak memory during the run, via `tracemalloc`;
* that the 731-day limit still refuses a wider period;
* that packages and transport legs do not multiply shipment counts;
* that financial gating is structural rather than cosmetic.

The dataset
-----------
Deliberately larger than the business is expected to be. Solaris Express is a small
shipping operation; 24,000 shipments across two years is roughly 33 a day every day,
which is comfortably beyond its current volume. Measuring at a size the business is
unlikely to reach means the conclusion survives it growing.

Everything is synthetic, generated into a **temporary database**. The development
database is never opened.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/report_query_review.py
    backend/.venv/Scripts/python scripts/report_query_review.py --shipments 50000
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

os.environ.setdefault("ENVIRONMENT", "review")
os.environ.setdefault("SECRET_KEY", "review-only-secret-not-a-production-value")

#: Stated in advance. See the module docstring.
TARGET_TOTAL_MS = 1000.0
TARGET_SINGLE_MS = 500.0

#: The documented dataset. Two years so the 731-day cap is actually reachable.
DEFAULT_CUSTOMERS = 6_000
DEFAULT_SHIPMENTS = 24_000
DEFAULT_PACKAGES_PER_SHIPMENT = 2
DEFAULT_EVENTS_PER_SHIPMENT = 2
PERIOD_DAYS = 730

ROUTE_GROUPS = ("CAV", "CAD", "XUS", "VCA")
OPERATIONAL_STATES = (
    "in_transit",
    "delivered",
    "exception",
    "delivery_attempted",
    "awaiting_parcel",
    "return_in_progress",
)
CURRENCIES = ("CAD", "USD", "VND", None)


# --- Statement counting -----------------------------------------------------------------


class StatementCounter:
    """Counts SQL statements at the driver level.

    Driver-level rather than ORM-level on purpose: the question is how many round trips
    the database is asked to make, and an ORM that lazily loads a relationship makes one
    without any call in the service naming it.
    """

    def __init__(self) -> None:
        self.count = 0
        self.statements: list[str] = []

    def reset(self) -> None:
        self.count = 0
        self.statements = []


@contextmanager
def counting(engine, counter: StatementCounter):
    from sqlalchemy import event

    def before(conn, cursor, statement, parameters, context, executemany):
        counter.count += 1
        counter.statements.append(statement.split("\n")[0][:90])

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", before)


# --- Dataset ------------------------------------------------------------------------------


def build_dataset(path: Path, *, customers: int, shipments: int, seed: int = 20260914):
    """Generate the dataset with Core bulk inserts.

    The ORM is the right tool for the application and the wrong one for twenty-four
    thousand rows; this is fixture generation, and the reports read the tables rather
    than the mapper.
    """
    from app.core.db import build_engine
    from app.models import Base, OrganizationSettings
    from sqlalchemy.orm import sessionmaker

    rng = random.Random(seed)
    engine = build_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    db = factory()
    org = OrganizationSettings()
    org.office_timezone = "America/Toronto"
    db.add(org)
    db.commit()
    db.close()

    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=None)
    start = today - timedelta(days=PERIOD_DAYS)

    raw = sqlite3.connect(path)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA synchronous=OFF")

    customer_rows = []
    for index in range(customers):
        created = start + timedelta(days=rng.uniform(0, PERIOD_DAYS))
        customer_rows.append(
            (
                index + 1,
                f"CUS-{index + 1:07d}",
                f"Synthetic Customer {index + 1}",
                # The `contactable` CHECK constraint requires one of these. Supplying a
                # normalized email keeps the fixture legal without inventing a phone
                # number shape the normalizer would disagree with.
                f"synthetic{index + 1}@demo.example.com",
                "en",
                "individual",
                "personal",
                "occasional",
                0,
                0,
                1,
                created.isoformat(sep=" "),
                created.isoformat(sep=" "),
            )
        )
    raw.executemany(
        "INSERT INTO customers (id, public_id, full_name, email_normalized, "
        "preferred_language, category, primary_shipping_purpose, shipping_frequency, "
        "is_archived, do_not_contact, is_demo_record, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        customer_rows,
    )

    shipment_rows = []
    package_rows = []
    event_rows = []
    package_id = 0
    event_id = 0
    for index in range(shipments):
        handoff = start + timedelta(days=rng.uniform(0, PERIOD_DAYS))
        booking = handoff - timedelta(days=1)
        route = rng.choice(ROUTE_GROUPS)
        state = rng.choice(OPERATIONAL_STATES)
        currency = rng.choice(CURRENCIES)
        shipment_id = index + 1
        shipment_rows.append(
            (
                shipment_id,
                rng.randint(1, customers),
                f"SX-{route}-{index:012X}"[:20],
                route,
                "standard",
                "air",
                "confirmed",
                state,
                "unpaid",
                DEFAULT_PACKAGES_PER_SHIPMENT,
                0,
                1,
                booking.date().isoformat(),
                handoff.isoformat(sep=" "),
                currency,
                round(rng.uniform(40, 400), 2),
                round(rng.uniform(20, 250), 2),
                handoff.isoformat(sep=" "),
                handoff.isoformat(sep=" "),
            )
        )
        for sequence in range(DEFAULT_PACKAGES_PER_SHIPMENT):
            package_id += 1
            package_rows.append(
                (
                    package_id,
                    shipment_id,
                    sequence + 1,
                    f"SX-{route}-{index:012X}"[:20] + f"-{sequence + 1:02d}",
                    1,
                    "cm",
                    "kg",
                    state,
                    handoff.isoformat(sep=" "),
                    handoff.isoformat(sep=" "),
                )
            )
        for step in range(DEFAULT_EVENTS_PER_SHIPMENT):
            event_id += 1
            occurred = handoff + timedelta(hours=step * 6)
            event_rows.append(
                (
                    event_id,
                    shipment_id,
                    "in_transit",
                    state,
                    occurred.isoformat(sep=" "),
                    occurred.isoformat(sep=" "),
                    1,
                    0,
                    "manual",
                    0,
                )
            )

    raw.executemany(
        "INSERT INTO shipments (id, customer_id, public_id, route_group, service_type, "
        "transport_mode, booking_state, operational_state, payment_state, package_count, "
        "is_return, is_demo_record, booking_date, first_handoff_at, currency, "
        "selling_amount, shipping_cost, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        shipment_rows,
    )
    raw.executemany(
        "INSERT INTO shipment_packages (id, shipment_id, sequence, package_reference, "
        "is_active, dimension_unit, weight_unit, operational_state, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        package_rows,
    )
    raw.executemany(
        "INSERT INTO shipment_events (id, shipment_id, event_type, operational_state, "
        "occurred_at, recorded_at, is_public_update, is_final_recipient_delivery, source, "
        "is_voided) VALUES (?,?,?,?,?,?,?,?,?,?)",
        event_rows,
    )
    raw.commit()

    counts = {
        "customers": raw.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "shipments": raw.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
        "packages": raw.execute("SELECT COUNT(*) FROM shipment_packages").fetchone()[0],
        "shipment_events": raw.execute("SELECT COUNT(*) FROM shipment_events").fetchone()[0],
    }
    raw.close()
    engine.dispose()
    return counts


# --- Measurement ----------------------------------------------------------------------------


def measure(path: Path, *, days: int, repeats: int = 3):
    from app.core.db import build_engine
    from app.core.enums import Role
    from app.models import OrganizationSettings
    from app.services import report_service
    from app.services.activity_service import LifecycleThresholds
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    engine = build_engine(f"sqlite:///{path.as_posix()}")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    db = factory()
    org = db.scalar(select(OrganizationSettings))

    to_date = datetime.now(UTC).date()
    from_date = to_date - timedelta(days=days - 1)
    period = report_service.resolve_period(from_date=from_date, to_date=to_date, org=org)

    counter = StatementCounter()
    results = []

    for key in report_service.available_report_keys(Role.ADMIN):
        timings = []
        counter.reset()
        statements = 0
        for _attempt in range(repeats):
            counter.reset()
            started = time.perf_counter()
            with counting(engine, counter):
                table = report_service.build_report(
                    db,
                    key,
                    period=period,
                    thresholds=LifecycleThresholds(),
                    route_groups=None,
                    role=Role.ADMIN,
                )
            timings.append((time.perf_counter() - started) * 1000)
            statements = counter.count
            db.expire_all()
        results.append(
            {
                "key": key,
                "median_ms": statistics.median(timings),
                "max_ms": max(timings),
                "statements": statements,
                "rows": len(table.rows),
            }
        )

    # The whole set, as the API serves it.
    set_timings = []
    counter.reset()
    set_statements = 0
    for _ in range(repeats):
        counter.reset()
        started = time.perf_counter()
        with counting(engine, counter):
            report_service.build_all(
                db,
                period=period,
                thresholds=LifecycleThresholds(),
                route_groups=None,
                role=Role.ADMIN,
            )
        set_timings.append((time.perf_counter() - started) * 1000)
        set_statements = counter.count
        db.expire_all()

    tracemalloc.start()
    report_service.build_all(
        db,
        period=period,
        thresholds=LifecycleThresholds(),
        route_groups=None,
        role=Role.ADMIN,
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    db.close()
    engine.dispose()
    return {
        "period_days": days,
        "granularity": period.granularity,
        "buckets": len(report_service.bucket_series(period)),
        "reports": results,
        "set_median_ms": statistics.median(set_timings),
        "set_max_ms": max(set_timings),
        "set_statements": set_statements,
        "peak_memory_mb": peak / (1024 * 1024),
    }


def check_invariants(path: Path):
    """The contracts the phase brief names, re-confirmed at this dataset size."""
    from app.core.db import build_engine
    from app.core.enums import Role
    from app.models import OrganizationSettings
    from app.services import report_service
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    engine = build_engine(f"sqlite:///{path.as_posix()}")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    db = factory()
    org = db.scalar(select(OrganizationSettings))
    findings = {}

    # 1. The 731-day limit.
    to_date = datetime.now(UTC).date()
    try:
        report_service.resolve_period(
            from_date=to_date - timedelta(days=report_service.MAX_PERIOD_DAYS),
            to_date=to_date,
            org=org,
        )
        findings["range_limit_731"] = "NOT ENFORCED"
    except Exception as exc:  # noqa: BLE001 - any refusal is the result being checked
        findings["range_limit_731"] = f"refused ({type(exc).__name__})"

    # 2. Packages and legs do not multiply shipment counts.
    period = report_service.resolve_period(
        from_date=to_date - timedelta(days=29), to_date=to_date, org=org
    )
    guard = report_service.package_and_leg_guard(db, period)
    findings["package_leg_guard"] = guard

    # 3. Financial gating is structural: the report is absent, not masked.
    # The invariant is not "these roles cannot see it" -- that would hardcode today's
    # permission matrix, which is still an open owner decision (DEC-0082). It is that
    # visibility follows the *permission*, exactly. Since the role merge (DEC-0088),
    # `operations` and `read_only_manager` genuinely hold `financial:read` and genuinely
    # should receive the report; only `admin` holds `financial_cost:read`, so only `admin`
    # sees cost.
    from app.core.permissions import Permission, permissions_for

    for role in Role:
        held = permissions_for(role)
        keys = set(report_service.available_report_keys(role))
        present = "financial_summary" in keys
        allowed = Permission.FINANCIAL_READ in held
        findings[f"financial_gating_{role.value}"] = (
            f"{'shown' if present else 'absent':>6s} / "
            f"{'may read' if allowed else 'may not':>8s}   "
            f"{'consistent' if present == allowed else '*** INCONSISTENT ***'}"
        )

    db.close()
    engine.dispose()
    return findings


# --- Report ---------------------------------------------------------------------------------


def print_report(counts, measured, invariants, *, scaled=None):
    line = "=" * 82
    print(line)
    print("SOLARIS CRM - REPORT QUERY REVIEW")
    print(line)
    print()
    print("Target, stated before measuring:")
    print(
        f"  report set under {TARGET_TOTAL_MS:.0f} ms; "
        f"no single report over {TARGET_SINGLE_MS:.0f} ms"
    )
    print()
    print("-- Machine (all timings MEASURED here) " + "-" * 43)
    print(f"  {platform.system()} {platform.release()} / {platform.machine()}")
    print(f"  Python {platform.python_version()} / SQLite {sqlite3.sqlite_version}")
    print()
    print("-- Synthetic dataset " + "-" * 61)
    for name, value in counts.items():
        print(f"  {name:24s} {value:>10,}")
    print(f"  {'period':24s} {measured['period_days']:>10,} days")
    print(f"  {'granularity':24s} {measured['granularity']:>10s}")
    print(f"  {'buckets':24s} {measured['buckets']:>10,}")
    print()
    print("-- Per report " + "-" * 68)
    print(f"  {'report':28s} {'median ms':>10s} {'max ms':>9s} {'SQL':>6s} {'rows':>7s}   verdict")
    for row in measured["reports"]:
        verdict = "ok" if row["max_ms"] <= TARGET_SINGLE_MS else "*** OVER TARGET ***"
        print(
            f"  {row['key']:28s} {row['median_ms']:>10.1f} {row['max_ms']:>9.1f} "
            f"{row['statements']:>6,} {row['rows']:>7,}   {verdict}"
        )
    print()
    print("-- Whole set " + "-" * 69)
    print(f"  median                   {measured['set_median_ms']:>10.1f} ms   [MEASURED]")
    print(f"  slowest of the repeats   {measured['set_max_ms']:>10.1f} ms   [MEASURED]")
    print(f"  SQL statements           {measured['set_statements']:>10,}")
    print(f"  peak memory              {measured['peak_memory_mb']:>10.1f} MiB   [MEASURED]")
    within = measured["set_max_ms"] <= TARGET_TOTAL_MS
    print(f"  target                   {'MET' if within else 'MISSED'}")
    print()
    if scaled:
        print("-- Do statement counts follow rows, or buckets? " + "-" * 34)
        print("  A per-row query would make these two columns differ.")
        print(f"  {'dataset':28s} {'shipments':>10s} {'SQL (set)':>10s}")
        for label, shipments, statements in scaled:
            print(f"  {label:28s} {shipments:>10,} {statements:>10,}")
        print()
    print("-- Invariants " + "-" * 68)
    for name, value in invariants.items():
        print(f"  {name:34s} {value}")
    print()
    print(line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Measure the Phase 5A reports.")
    parser.add_argument("--customers", type=int, default=DEFAULT_CUSTOMERS)
    parser.add_argument("--shipments", type=int, default=DEFAULT_SHIPMENTS)
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)

    scratch = Path(tempfile.mkdtemp(prefix="solaris-report-review-"))
    try:
        path = scratch / "review.db"
        print(f"Generating {args.shipments:,} shipments into {path} ...", flush=True)
        started = time.perf_counter()
        counts = build_dataset(path, customers=args.customers, shipments=args.shipments)
        print(f"  built in {time.perf_counter() - started:.1f} s", flush=True)

        measured = measure(path, days=args.days, repeats=args.repeats)
        invariants = check_invariants(path)

        # Half the data, same period: if statement counts are identical the queries are
        # bucket-bound rather than row-bound.
        half = scratch / "half.db"
        half_counts = build_dataset(
            half,
            customers=max(1, args.customers // 2),
            shipments=max(1, args.shipments // 2),
        )
        half_measured = measure(half, days=args.days, repeats=1)
        scaled = [
            ("half", half_counts["shipments"], half_measured["set_statements"]),
            ("full", counts["shipments"], measured["set_statements"]),
        ]

        print_report(counts, measured, invariants, scaled=scaled)
        return 0 if measured["set_max_ms"] <= TARGET_TOTAL_MS else 1
    finally:
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
