"""Demonstrate the integration worker against synthetic fixtures, in ``--once`` mode.

Run it to see, in one pass, the behaviours ``PROJECT_STATUS.md`` claims: a verified
notification applied, a duplicate producing no second effect, a forged event refused, an
unsigned notification answered by an authenticated read rather than believed, a provider
outage leaving a delivered parcel delivered, and a crashed worker's lease reclaimed.

**Nothing here touches a real provider, and nothing here is a production capability.**

* The adapter is ``tests.fakes.fake_provider_adapter.FakeProviderAdapter``. Its provider
  key is ``fake``, its statuses are invented words no carrier uses, and its signature
  scheme was made up in that file. It is not ShipStation and does not model it.
* The registry it is put into is **created here** and passed in. The production registry
  is untouched and stays empty; ``AdapterRegistry.register`` refuses outright while the
  environment is production.
* The database is a scratch file in a temporary directory, created and thrown away. No
  configured database is opened.
* **No unattended service is started.** Every pass is one bounded ``run_once``.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/integration_worker_demo.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

SCRATCH = Path(tempfile.mkdtemp(prefix="solaris-worker-demo-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(SCRATCH / 'demo.db').as_posix()}"
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "demo-only-secret-not-a-credential")

from app.core.enums import IntegrationJobStatus  # noqa: E402
from app.integrations.registry import AdapterRegistry  # noqa: E402
from app.integrations.registry import registry as production_registry  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    IntegrationJob,
    IntegrationProviderEvent,
    IntegrationWebhookInboxItem,
    OrganizationSettings,
    ShipmentEvent,
)
from app.services import integration_inbox_service as inbox  # noqa: E402
from app.services import integration_job_service as jobs  # noqa: E402
from app.workers import integration_worker  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from tests.fakes import fake_provider_adapter as fake  # noqa: E402
from tests.fakes.fake_provider_adapter import (  # noqa: E402
    FakeProviderAdapter,
    make_payload,
    sign,
    signed_headers,
    unsigned_headers,
)
from tests.integration_fixtures import FAKE_TRACKING_NUMBER, tracked_shipment  # noqa: E402

BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)
OCCURRED = "2026-09-01T08:00:00+00:00"


def clock_at(moment: datetime = BASE_TIME):
    return lambda: moment


def heading(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def line(label: str, value: object) -> None:
    print(f"  {label:<44} {value}")


def deliver(db, adapter, headers=None, **payload):
    payload.setdefault("occurred_at", OCCURRED)
    payload.setdefault("reference", FAKE_TRACKING_NUMBER)
    body = make_payload(**payload)
    result = inbox.accept_delivery(
        db,
        adapter=adapter,
        body=body,
        headers=headers if headers is not None else signed_headers(body),
        clock=clock_at(),
    )
    db.commit()
    return result, body


def run_once(db, adapter, *, at=BASE_TIME, worker_name="demo-worker"):
    result = integration_worker.run_once(
        db,
        worker_name=worker_name,
        registry=AdapterRegistry({adapter.capabilities().provider_key: adapter}),
        clock=clock_at(at),
        jitter=lambda: 0.0,
    )
    db.commit()
    return result


def provider_event_count(db) -> int:
    return db.query(ShipmentEvent).filter(ShipmentEvent.source == "provider").count()


_ENGINES = []


def fresh_session(_unused=None):
    """A brand-new database for each scenario.

    One shared database would be wrong here, and quietly so: the fake adapter emits the
    same event id and the same tracking reference every time, so a second scenario's
    delivery would deduplicate against the first scenario's inbox row and every later
    section would report the *first* section's outcome. Isolation is what makes each block
    below a demonstration of the thing it names rather than an echo.
    """
    import uuid

    from app.core.db import build_engine as _build

    url = f"sqlite:///{(SCRATCH / f'scenario-{uuid.uuid4().hex[:8]}.db').as_posix()}"
    engine = _build(url)
    Base.metadata.create_all(engine)
    _ENGINES.append(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)()
    session.add(OrganizationSettings())
    session.commit()
    return session


def main() -> int:
    print("Solaris Express CRM — integration worker demonstration")
    print("=" * 66)
    line("production adapter registry", f"empty={production_registry.is_empty()}")
    line("adapter used here", "tests.fakes.FakeProviderAdapter (provider_key='fake')")
    line("real provider requests made", "0")
    line("scratch databases", f"{SCRATCH} (one per scenario, discarded)")

    # --- 1. A verified notification is applied ---------------------------
    heading("1. A verified notification becomes a shipment event")
    db = fresh_session()
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    deliver(db, adapter, status="FAKE_MOVING")
    result = run_once(db, adapter)
    db.refresh(tracked.shipment)
    line("jobs claimed / succeeded", f"{result.claimed} / {result.succeeded}")
    line("shipment operational state", tracked.shipment.operational_state)
    line("normalized provider events", db.query(IntegrationProviderEvent).count())
    line("shipment events with source=provider", provider_event_count(db))
    db.close()

    # --- 2. A duplicate produces no second effect ------------------------
    heading("2. A duplicate delivery produces exactly one downstream effect")
    db = fresh_session()
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    deliver(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run_once(db, adapter)
    duplicate, _ = deliver(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run_once(db, adapter, at=BASE_TIME + timedelta(minutes=1))
    db.refresh(tracked.shipment)
    db.refresh(tracked.package)
    line("second delivery recognized as duplicate", duplicate.is_duplicate)
    line("inbox rows", db.query(IntegrationWebhookInboxItem).count())
    line("shipment events with source=provider", provider_event_count(db))
    line("packages delivered", 1 if tracked.package.delivered_to_recipient_at else 0)
    line("shipment operational state", tracked.shipment.operational_state)
    db.close()

    # --- 3. A forged event cannot mutate state ---------------------------
    heading("3. A forged event cannot mutate shipment or package state")
    db = fresh_session()
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    before = tracked.shipment.operational_state
    body = make_payload(
        reference=FAKE_TRACKING_NUMBER, status="FAKE_HANDED_TO_RECIPIENT", occurred_at=OCCURRED
    )
    forged = dict(signed_headers(body))
    forged["x-fake-signature"] = sign(body, secret="an-attacker-secret")
    item = inbox.accept_delivery(db, adapter=adapter, body=body, headers=forged, clock=clock_at())
    db.commit()
    result = run_once(db, adapter)
    db.refresh(tracked.shipment)
    line("verification state", item.item.verification_state)
    line("processing state", item.item.processing_state)
    line("jobs created for it", db.query(IntegrationJob).count())
    line("shipment events with source=provider", provider_event_count(db))
    line("shipment state before / after", f"{before} / {tracked.shipment.operational_state}")
    db.close()

    # --- 4. An unsigned notification is verified, not believed ------------
    heading("4. An unsigned notification is verified by an authenticated read")
    db = fresh_session()
    adapter = FakeProviderAdapter(verifies_signatures=False, read_status="FAKE_MOVING")
    tracked = tracked_shipment(db)
    body = make_payload(
        reference=FAKE_TRACKING_NUMBER, status="FAKE_HANDED_TO_RECIPIENT", occurred_at=OCCURRED
    )
    item = inbox.accept_delivery(
        db, adapter=adapter, body=body, headers=unsigned_headers(), clock=clock_at()
    )
    db.commit()
    line("notification claims", "FAKE_HANDED_TO_RECIPIENT (delivered)")
    line("verification state on arrival", item.item.verification_state)
    line("job enqueued", db.query(IntegrationJob).one().job_type)
    run_once(db, adapter)
    db.refresh(tracked.package)
    record = db.query(IntegrationProviderEvent).one()
    line("authenticated reads performed", len(adapter.read_calls))
    line("provider answered", record.raw_status)
    line("applied from", record.verification_source)
    line("package delivered", bool(tracked.package.delivered_to_recipient_at))
    db.close()

    # --- 5. A provider outage preserves the last known state --------------
    heading("5. A provider outage preserves the last known tracking state")
    db = fresh_session()
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    deliver(db, adapter, status="FAKE_HANDED_TO_RECIPIENT")
    run_once(db, adapter)
    db.refresh(tracked.shipment)
    line("state after delivery", tracked.shipment.operational_state)

    adapter.read_error = fake.TIMEOUT
    job = jobs.enqueue(
        db,
        job_type="reconcile_tracking_assignment",
        provider_key="fake",
        tracking_assignment_id=tracked.assignment.id,
        dedupe_key=f"reconcile:{tracked.assignment.id}",
        clock=clock_at(),
    )
    db.commit()
    at = BASE_TIME + timedelta(minutes=1)
    attempts = 0
    while attempts < 12:
        run_once(db, adapter, at=at)
        db.refresh(job)
        attempts += 1
        if job.status == IntegrationJobStatus.FAILED_TERMINAL:
            break
        at = job.available_at + timedelta(seconds=1)
    db.refresh(tracked.shipment)
    line("failed attempts before terminal", job.attempt_count)
    line("job status", job.status)
    line("requires operator review", job.requires_review)
    line("error code recorded", job.error_code)
    line("error summary (redacted)", job.error_summary)
    line("state after the outage", tracked.shipment.operational_state)
    line("delivered_at preserved", tracked.shipment.delivered_at is not None)
    db.close()

    # --- 6. A crashed worker strands nothing ------------------------------
    heading("6. A crashed worker leaves a lease that expires and is reclaimed")
    db = fresh_session()
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    deliver(db, adapter, status="FAKE_MOVING")
    claimed = jobs.claim_next(db, worker_name="worker-that-crashes", clock=clock_at())
    db.commit()
    line("claimed by", claimed.job.lease_owner)
    line("job status while held", claimed.job.status)
    line("provider events applied so far", provider_event_count(db))

    from app.core.config import settings

    later = BASE_TIME + timedelta(seconds=settings.integration_job_lease_seconds + 60)
    result = run_once(db, adapter, at=later, worker_name="replacement-worker")
    db.refresh(tracked.shipment)
    line("expired leases reclaimed", result.reclaimed)
    line("jobs succeeded after recovery", result.succeeded)
    line("shipment operational state", tracked.shipment.operational_state)
    db.close()

    # --- 7. With no adapter, nothing happens and nothing breaks -----------
    heading("7. With no provider configured, the worker changes nothing")
    db = fresh_session()
    adapter = FakeProviderAdapter()
    tracked = tracked_shipment(db)
    before = tracked.shipment.operational_state
    deliver(db, adapter, status="FAKE_MOVING")
    result = integration_worker.run_once(
        db,
        worker_name="demo-worker",
        registry=AdapterRegistry({}),
        clock=clock_at(),
        jitter=lambda: 0.0,
    )
    db.commit()
    db.refresh(tracked.shipment)
    line("jobs skipped for want of an adapter", result.skipped_no_adapter)
    line("provider events applied", provider_event_count(db))
    line("shipment state before / after", f"{before} / {tracked.shipment.operational_state}")
    line("public tracking still resolves", tracked.shipment.public_id)
    db.close()

    for engine in _ENGINES:
        engine.dispose()
    print(f"\n{'=' * 66}")
    print("No provider is connected. No request has ever been made to a carrier or to")
    print("ShipStation by this application. Every pass above was `run_once`.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
