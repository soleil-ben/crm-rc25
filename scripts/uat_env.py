"""Build, reset, inspect and destroy the isolated UAT environment.

UAT needs a database that is repeatable and unmistakably not the real one. This builds it,
and refuses to build it anywhere it could be mistaken for the development or production
database.

Safety, in the order the checks run
-----------------------------------
1. `ENVIRONMENT=production` is refused outright. Nothing here runs against production.
2. The target path must sit inside the UAT directory *and* carry the `.uat.db` suffix. A
   plain `.db` somewhere convenient is still a database somebody could later mistake for a
   real one; the suffix makes the throwaway obvious in a file listing and in an error.
3. The development database path and whatever `DATABASE_URL` currently points at are
   refused by name, resolved, so a symlink or a relative path cannot slip past.
4. `--destroy` deletes only a path that passed all of the above.

Every check is on the resolved path, and a destination has to defeat all four rather than
one.

What the data is
----------------
`app.seed` builds the synthetic base: four staff roles, Vietnamese customers with full
diacritics, all four route groups, drafts, confirmed shipments, a cancellation, a
rebooking, packages, events, follow-up tasks, and saved segments. Every
record is fictional and flagged, and every identity is on the reserved `example.com`
domain (DEC-0027), which is also what stops any of it authenticating in production
(`app.core.demo_identity`).

The seed leaves six workflows the UAT pack exercises with no data at all, so the build
adds them **through the services**, never by writing rows -- the data then obeys the same
rules the API enforces, which is the only way it is worth testing against:

* a global contact suppression;
* an external-link tracking reference, which is what makes the public carrier link
  reachable (the nine `PUBLIC_CARRIER_LINK_HOSTS` are retained for UAT under OD-07);
* a generated label document, recorded as a print job;
* a customer merge, which leaves the tombstone alias behind (DEC-0013);
* one committed customer import, so import history and the retry screen have a batch.

The sixth it cannot add. **Returns are not implemented.** `shipments.is_return` and
`shipments.return_of_shipment_id` exist in the schema and are read by reports and exports,
but nothing in the application ever sets either one -- no service, no schema, no route.
Writing those rows directly would manufacture a workflow that does not exist and hand a
tester a screen to "verify" that no code produces. `--check` reports returns as absent for
that reason, and says so.

Usage, from the repository root (on Linux and macOS the interpreter is
``backend/.venv/bin/python`` rather than ``backend/.venv/Scripts/python``)::

    backend/.venv/Scripts/python scripts/uat_env.py --create
    backend/.venv/Scripts/python scripts/uat_env.py --reset     # destroy, rebuild, reseed
    backend/.venv/Scripts/python scripts/uat_env.py --check     # coverage report only
    backend/.venv/Scripts/python scripts/uat_env.py --destroy
    backend/.venv/Scripts/python scripts/uat_env.py --refresh-fx  # new demo FX reading

`--check` exits 1 when a required category is missing, so the environment cannot be handed
to a tester while it is silently incomplete.

**A build that fails part-way leaves a partial database: run ``--reset``**, which deletes it
and starts again. The air dataset is idempotent only on a complete build (it skips when its
first master exists), so re-running it over a half-built one is not a repair. ``--path`` may
name another ``.uat.db`` file, but only directly inside ``data/uat/`` (the mail and intake
folders are shared and sit there).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

#: Everything UAT writes lives here, and nothing here is committed (see .gitignore).
UAT_DIR = REPO_ROOT / "data" / "uat"

#: The one database this script will build, and the only one `--destroy` will delete.
UAT_DB = UAT_DIR / "solaris_uat.uat.db"

#: A destination must carry this. See the module docstring.
UAT_DB_SUFFIX = ".uat.db"

#: Where Customer Account mail lands during UAT, when the stack is started as
#: `docs/UAT/ENVIRONMENT.md` section 3a says to start it. It is kept beside the UAT
#: database rather than in the development capture directory for one reason: a captured
#: verification link is a live credential, and `--reset` must be able to throw the whole
#: environment away without a tester having to remember a second directory.
UAT_MAIL_DIR = UAT_DIR / "account_mail"

#: The vendor rate-email folder the intake worker reads during UAT (``TARIFF_INTAKE_DIR``),
#: beside the database for the same reason as the mail: ``--reset`` throws it away. The
#: Phase 17 seed leaves two sample emails in ``samples/`` and the worker's ``processed/``.
UAT_INTAKE_DIR = UAT_DIR / "tariff_intake"

#: The Phase 17 air dataset (``scripts/uat_seed_phase13.py``), run after the base seed.
PHASE13_SEED = REPO_ROOT / "scripts" / "uat_seed_phase13.py"

#: Refused by name, resolved.
DEV_DB = REPO_ROOT / "data" / "solaris_crm.db"

#: The password every seeded account uses. Printed here because it is already printed by
#: the seed and written in the documentation -- and because a tester needs it. It is safe
#: to print precisely because these accounts cannot authenticate in production.
UAT_PASSWORD = "SolarisDemo!2026"

UAT_ACCOUNTS = [
    ("admin", "admin@demo.example.com"),
    ("operations", "ops@demo.example.com"),
    ("marketing", "marketing@demo.example.com"),
    ("read_only_manager", "manager@demo.example.com"),
]

#: The two Customer Accounts the Phase 17 seed links (A1 Vietnamese, A2 English), and their
#: shared password. Reserved domain, so refused in production like the staff accounts.
UAT_CUSTOMER_ACCOUNTS = [
    ("A1, Vietnamese", "trang.air@example.com"),
    ("A2, English", "emily.air@example.com"),
]
UAT_CUSTOMER_PASSWORD = "SolarisUatCustomer!2026"


class SafetyError(RuntimeError):
    """A path or an environment was refused before anything was created or deleted."""


@dataclass
class Category:
    """One thing the UAT pack needs the dataset to contain."""

    name: str
    query: str
    required: bool = True
    note: str = ""

    def count(self, connection: sqlite3.Connection) -> int:
        try:
            return connection.execute(self.query).fetchone()[0]
        except sqlite3.Error:
            return -1


COVERAGE = [
    Category("staff roles", "select count(distinct role) from users"),
    Category("customers", "select count(*) from customers"),
    Category(
        "customers with Vietnamese diacritics",
        r"select count(*) from customers where full_name glob '*[ăâđêôơưàáảãạ]*'"
        r" or full_name glob '*[ĂÂĐÊÔƠƯễịậ]*'",
    ),
    Category("route groups", "select count(distinct route_group) from shipments"),
    Category("draft shipments", "select count(*) from shipments where booking_state='draft'"),
    Category(
        "confirmed shipments", "select count(*) from shipments where booking_state='confirmed'"
    ),
    Category(
        "cancelled shipments", "select count(*) from shipments where booking_state='cancelled'"
    ),
    Category(
        "rebooked shipments",
        "select count(*) from shipments where rebooked_from_shipment_id is not null",
    ),
    Category("packages", "select count(*) from shipment_packages"),
    Category("shipment events", "select count(*) from shipment_events"),
    Category("follow-up tasks", "select count(*) from follow_up_tasks"),
    Category("saved segments", "select count(*) from saved_segments"),
    Category("import batches", "select count(*) from import_batches"),
    Category("consent events", "select count(*) from consent_events"),
    Category("contact suppressions", "select count(*) from contact_suppressions"),
    Category(
        "manual tracking references",
        "select count(*) from leg_tracking_references where source_mode='manual'",
    ),
    Category(
        "external-link tracking references",
        "select count(*) from leg_tracking_references where source_mode='external_link'",
    ),
    Category("label print jobs", "select count(*) from label_print_jobs"),
    Category("merge tombstone aliases", "select count(*) from customer_id_aliases"),
    # Fix pack of 2026-10-14, item 12: the data the packs name.
    Category(
        "UAT test people P1-P5",
        "select count(*) from customers where email_normalized in ("
        "'hanh.uat@example.com','tuan.uat@example.com','daniel.uat@example.com',"
        "'hanh.dup@example.com','maianh.uat@example.com')",
        note="P1 and P4 share a phone; P5 has none",
    ),
    Category(
        "customers with cancelled and rebooked shipments",
        "select count(*) from (select customer_id from shipments "
        "where booking_state='cancelled' group by customer_id "
        "having sum(case when rebooked_to_shipment_id is not null then 1 else 0 end) > 0 "
        "and sum(case when rebooked_to_shipment_id is null then 1 else 0 end) > 0)",
    ),
    Category(
        "customers with 25+ shipments (paging)",
        "select count(*) from (select customer_id from shipments "
        "group by customer_id having count(*) >= 25)",
    ),
    Category(
        "distinct operational states",
        "select count(distinct operational_state) from shipments",
    ),
    Category(
        "non-demo shipments for the first customer",
        "select count(*) from shipments where is_demo_record=0 "
        "and customer_id=(select min(id) from customers)",
        note="the Customer Account excludes demo shipments; this is what a linked account sees",
    ),
    Category(
        "late-evening Toronto booking for the first customer",
        # Booked 23:30 Toronto time, which is the next UTC day: subtracting five hours (the
        # larger Toronto offset) lands on an earlier date than the stored UTC one.
        "select count(*) from shipments where is_demo_record=0 "
        "and booking_reference='UAT-CA-SHP-10' "
        "and customer_id=(select min(id) from customers) "
        "and date(booking_date, '-5 hours') < date(booking_date)",
        note="CA-SHP-10: 23:30 Toronto time, stored on the next UTC date",
    ),
    Category(
        "shipments whose last event is unpublished",
        "select count(*) from shipments s where s.operational_state='exception' and not exists("
        "select 1 from shipment_events e where e.shipment_id=s.id and e.is_public_update=1 "
        "and e.operational_state='exception')",
        note="UAT-XX-02: the public page must say In transit, never Delayed, for these",
    ),
    # Phase 17: the air dataset (scripts/uat_seed_phase13.py, docs/UAT/AIR_UAT_PACK.md).
    Category(
        "active tariff version",
        "select count(*) from tariff_versions where status='active'",
    ),
    Category(
        "draft tariff awaiting the approver",
        "select count(*) from tariff_versions v join tariff_email_intakes i "
        "on i.tariff_version_id=v.id where v.status='draft' and i.status='imported'",
        note="from vendor-rates.example.com, three prices changed",
    ),
    Category(
        "rate email held (unknown sender)",
        "select count(*) from tariff_email_intakes where status='held_sender'",
    ),
    Category(
        "demo exchange-rate readings",
        "select count(*) from fx_rate_snapshots",
    ),
    Category(
        "saved default markup (2 %)",
        "select count(*) from markup_defaults where markup_kind='percent' and markup_value=2",
    ),
    Category(
        "air masters UAT-AWB-*",
        "select count(*) from consolidations where vendor_reference like 'UAT-AWB-%'",
        note="OPEN, BOOKED, TRANSIT, DELIVERED and CLOSED; 5 expected",
    ),
    Category(
        "open master with item and surcharge lines",
        "select count(*) from consolidations c where c.vendor_reference='UAT-AWB-OPEN' "
        "and c.state='open' and exists(select 1 from consolidation_memberships m "
        "join shipment_fee_lines f on f.shipment_id=m.shipment_id "
        "where m.consolidation_id=c.id)",
    ),
    Category(
        "quote offer awaiting the customer",
        "select count(*) from quote_offers where status='sent'",
    ),
    Category(
        "quotes accepted in the Customer Account",
        "select count(*) from quote_offers where status='accepted'",
    ),
    Category(
        "accepted, not invoiced",
        "select count(*) from quote_offers o where o.status='accepted' and not exists("
        "select 1 from customer_invoices i where i.shipment_id=o.shipment_id "
        "and i.status!='void')",
    ),
    Category(
        "invoice tax choices (GST/HST 0, 5 %)",
        "select count(distinct tax_status) from customer_invoices",
        # RC-UAT-20 (DEC-0227): A1's VN-CA invoice is zero-rated by route (13 % in RC-UAT-19).
        note="2 expected",
    ),
    # RC-UAT-20 (DEC-0227): domestic Canada -> Canada drafts take the destination province's
    # rate, included (UAT-AIR-DOM-NS / -NB / -UNK, accepted by A2).
    Category(
        "domestic draft invoice at 14 % (NS)",
        "select count(*) from invoice_drafts d join shipments s on s.id=d.shipment_id "
        "where s.route_group='CAD' and d.tax_rate_percent=14 and d.status='draft'",
        note="UAT-AIR-DOM-NS, Halifax B3H 1A1",
    ),
    Category(
        "domestic draft invoice at 15 % (NB)",
        "select count(*) from invoice_drafts d join shipments s on s.id=d.shipment_id "
        "where s.route_group='CAD' and d.tax_rate_percent=15 and d.status='draft'",
        note="UAT-AIR-DOM-NB, Moncton E1C 4M3",
    ),
    Category(
        "domestic draft awaiting a rate (unknown province)",
        "select count(*) from invoice_drafts d join invoice_draft_tax_route r "
        "on r.draft_id=d.id where d.status='draft' and r.rate_required=1 "
        "and r.rate_chosen_at is null",
        note="UAT-AIR-DOM-UNK: no province, no postal code; staff must choose",
    ),
    Category(
        "part-paid invoice",
        "select count(*) from customer_invoices where paid_cad>0 and paid_cad<total_cad",
    ),
    Category(
        "VND payments",
        "select count(*) from customer_payments where currency='VND'",
    ),
    Category(
        "refunds",
        "select count(*) from customer_payments where kind='refund'",
    ),
    Category(
        "vendor bill with a variance, reconciled",
        "select count(*) from vendor_invoices where variance_cad!=0 "
        "and variance_reason is not null and status='paid'",
    ),
    Category(
        "closed month",
        "select count(*) from period_closes where reopened_at is null",
    ),
    Category(
        "linked Customer Accounts (vi and en)",
        "select count(distinct i.preferred_language) from customer_identities i "
        "join customer_identity_links l on l.identity_id=i.id where l.status='active'",
        note="2 expected: A1 vi, A2 en",
    ),
    Category(
        "milestone emails captured (UAT-AIR shipments)",
        "select count(*) from notification_outbox o join shipments s on s.id=o.shipment_id "
        "where o.status='sent' and s.booking_reference like 'UAT-AIR-%'",
        note="11 on a fresh reset; the base seed's own milestone emails are not counted",
    ),
    Category(
        "milestone opt-out (A2, in transit)",
        "select count(*) from notification_preferences where enabled=0",
    ),
    Category(
        "returns",
        "select count(*) from shipments where is_return=1",
        required=False,
        note="not implemented: nothing in the application sets is_return",
    ),
    Category(
        "connected_api tracking references",
        "select count(*) from leg_tracking_references where source_mode='connected_api'",
        required=False,
        note="must stay 0 -- connected_api is refused (DEC-0075)",
    ),
    Category(
        "integration connections",
        "select count(*) from integration_connections",
        required=False,
        note="must stay 0 -- no provider is configured",
    ),
]

#: Categories that are a failure when they are *not* zero.
MUST_BE_ZERO = {
    "connected_api tracking references",
    "integration connections",
}


def refuse_production() -> None:
    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment.startswith("prod"):
        raise SafetyError(
            f"ENVIRONMENT={environment!r}. This script never runs against production."
        )


def validated_target(path: Path) -> Path:
    """Resolve and check the target, or refuse it by name."""
    refuse_production()
    resolved = path.resolve()

    if resolved.suffix != ".db" or not resolved.name.endswith(UAT_DB_SUFFIX):
        raise SafetyError(
            f"{resolved} does not end in {UAT_DB_SUFFIX}. A UAT database must be obviously "
            "disposable in a file listing."
        )

    try:
        resolved.relative_to(UAT_DIR.resolve())
    except ValueError:
        raise SafetyError(f"{resolved} is outside the UAT directory {UAT_DIR}.") from None
    if resolved.parent != UAT_DIR.resolve():
        # The air dataset keeps its mail and intake folders beside the database, inside the
        # UAT directory, and refuses folders outside the database's own directory; a target
        # in a sub-directory would build the base data and then fail half-way.
        raise SafetyError(
            f"{resolved} is in a sub-directory; a UAT database sits directly in {UAT_DIR}."
        )

    if resolved == DEV_DB.resolve():
        raise SafetyError(f"{resolved} is the development database.")

    configured = os.environ.get("DATABASE_URL", "")
    if configured.startswith("sqlite"):
        current = Path(configured.split("///", 1)[-1]).expanduser()
        try:
            if current.resolve() == resolved:
                raise SafetyError(
                    f"{resolved} is what DATABASE_URL currently points at. Point UAT at its "
                    "own database."
                )
        except OSError:
            pass

    return resolved


def database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def run_backend(args: list[str], path: Path) -> None:
    """Run a backend module against the UAT database, with the demo guardrails set."""
    env = {
        **os.environ,
        "DATABASE_URL": database_url(path),
        "ENVIRONMENT": "development",
        "ALLOW_DEMO_SEED": "true",
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, *args], cwd=BACKEND_ROOT, env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"{' '.join(args)} failed with exit {result.returncode}")


def augment(path: Path) -> list[str]:
    """Add the workflows the base seed leaves empty, through the services.

    Returns a list of what it added, for the report. Each step is independent and reports
    what it could not do rather than aborting, so one unavailable fixture does not cost the
    whole environment.
    """
    script = r"""
import sys
from sqlalchemy import select

from app.core.db import session_scope
from app.core.enums import ContactChannel, TrackingSourceMode
from app.models import Customer, ShipmentLeg, User
from app.services import (
    consent_service,
    customer_service,
    label_service,
    leg_service,
)
from app.api.deps import get_org_settings

added = []

with session_scope() as db:
    admin = db.scalar(select(User).where(User.email == "admin@demo.example.com"))

    # 1. A global contact suppression, so suppression is visible in UAT. A named demo
    #    customer rather than "the newest one": the seed now ends with the UAT test
    #    people (P1-P5) and the paging customer, none of whom may be suppressed, merged
    #    or otherwise pre-decided for a tester (fix pack of 2026-10-14, item 12).
    target = db.scalar(
        select(Customer).where(Customer.email_normalized == "minh.tuan.demo@demo.example.com")
    ) or db.scalar(
        select(Customer)
        .where(
            Customer.email_normalized.is_not(None),
            Customer.email_normalized.like("%@demo.example.com"),
        )
        .order_by(Customer.id.desc())
    )
    if target and target.email_normalized:
        consent_service.add_suppression(
            db,
            channel=ContactChannel.EMAIL.value,
            address_value=target.email_normalized,
            reason="UAT fixture: suppressed so the suppression screens have something to show",
            actor=admin,
        )
        added.append(f"suppression on {target.email_normalized}")
    else:
        added.append("SKIPPED suppression: no contactable customer")

    # 2. An external-link tracking reference, so the public carrier link is reachable.
    leg = db.scalar(select(ShipmentLeg).order_by(ShipmentLeg.id))
    if leg:
        leg_service.add_tracking_reference(
            db,
            leg,
            {
                "carrier_name": "Canada Post",
                "tracking_number": "UATEXTLINK0001",
                "source_mode": TrackingSourceMode.EXTERNAL_LINK,
                "public_url": "https://www.canadapost-postescanada.ca/track-reperage/en#/search?searchFor=UATEXTLINK0001",
            },
            actor=admin,
        )
        added.append("external-link tracking reference on a transport leg")
    else:
        added.append("SKIPPED external link: no transport leg")

    # 3. A generated label document, recorded as a print job.
    from app.models import Shipment
    from app.core.enums import BookingState

    shipment = db.scalar(
        select(Shipment)
        .where(Shipment.booking_state == BookingState.CONFIRMED)
        .order_by(Shipment.id)
    )
    if shipment:
        org = get_org_settings(db)
        document, packages, kind = label_service.build_label_document(db, shipment, org=org)
        label_service.record_generation(
            db, shipment, packages, document, kind=kind, actor=admin
        )
        added.append(f"label print job for {shipment.public_id} ({document.page_count} page(s))")
    else:
        added.append("SKIPPED label: no confirmed shipment")

    # 4. A merge, which leaves the tombstone alias behind (DEC-0013). The same two demo
    #    records it always merged, named explicitly: the one with no shipments into its
    #    neighbour. Never P1/P4 -- that pair is UAT-AD-04's to merge -- and never the
    #    paging customer.
    source = db.scalar(
        select(Customer).where(Customer.email_normalized == "minh.tuan.demo@demo.example.com")
    )
    dest = db.scalar(
        select(Customer).where(Customer.email_normalized == "ahmed.demo@demo.example.com")
    )
    if source is not None and dest is not None and source.archived_at is None:
        customer_service.merge_customers(db, source=source, target=dest, actor=admin)
        added.append(f"merge of {source.public_id} into {dest.public_id}")
    else:
        added.append("SKIPPED merge: the two named demo customers were not both present")

    # 5. One committed import, so import history and the retry screen have a batch.
    from app.services import customer_import_service as importer

    header = "full_name,email,phone,country_code,city,preferred_language,source_record_id\r\n"
    body = (
        "Đặng Thị Hồng UAT,hong.uat@demo.example.com,,CA,Toronto,vi,UAT-IMP-1\r\n"
        "Phạm Quốc Huy UAT,huy.uat@demo.example.com,,CA,Mississauga,vi,UAT-IMP-2\r\n"
    )
    content = (header + body).encode("utf-8")
    if admin:
        importer.commit_import(
            db,
            content,
            expected_sha256=importer.content_digest(content),
            actor=admin,
            file_name="uat-fixture.csv",
        )
        added.append("committed customer import (2 rows) so import history exists")
    else:
        added.append("SKIPPED import: no admin account")

print("\n".join(added))
"""
    env = {
        **os.environ,
        "DATABASE_URL": database_url(path),
        "ENVIRONMENT": "development",
        "ALLOW_DEMO_SEED": "true",
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"augmentation failed with exit {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def report(path: Path) -> int:
    """Print the coverage table. Exit status 1 when a required category is missing."""
    if not path.exists():
        print(f"No UAT database at {path}. Run with --create.")
        return 1

    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = [(category, category.count(connection)) for category in COVERAGE]
    finally:
        connection.close()

    width = max(len(category.name) for category, _ in rows)
    missing: list[str] = []

    print(f"UAT dataset coverage -- {path}")
    print()
    for category, count in rows:
        if category.name in MUST_BE_ZERO:
            ok = count == 0
        elif category.required:
            ok = count > 0
        else:
            ok = True

        status = "ok  " if ok else "MISSING"
        suffix = f"   ({category.note})" if category.note else ""
        print(f"  {status:<7} {category.name:<{width}}  {count}{suffix}")
        if not ok:
            missing.append(category.name)

    print()
    print("UAT accounts -- all on reserved domains, refused in production:")
    for role, email in UAT_ACCOUNTS:
        print(f"  {role:<20} {email}")
    print(f"  password for every account: {UAT_PASSWORD}")
    print("Customer Accounts (Phase 17 air dataset), at /account/sign-in:")
    for label, email in UAT_CUSTOMER_ACCOUNTS:
        print(f"  {label:<20} {email}")
    print(f"  password for both: {UAT_CUSTOMER_PASSWORD}")

    print()
    if missing:
        print(f"{len(missing)} required categor(ies) missing: {', '.join(missing)}")
        return 1
    print("Every required category is present.")
    return 0


def create(path: Path, *, reset: bool) -> None:
    if reset and path.exists():
        print(f"Removing {path}")
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                candidate.unlink()

    if reset:
        captured = clear_captured_mail()
        if captured:
            print(f"Removing {captured} captured Customer Account message(s)")
        emails = clear_intake_folder()
        if emails:
            print(f"Removing {emails} file(s) from the UAT rate-email intake folder")

    path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Migrating {path}")
    run_backend(["-m", "alembic", "upgrade", "head"], path)

    print("Seeding synthetic data")
    run_backend(["-m", "app.seed"], path)

    print("Adding the workflows the base seed leaves empty")
    for line in augment(path):
        print(f"  {line}")

    print("Adding the air dataset (pricing, quotes, finance, tariffs, milestone emails)")
    for line in seed_air(path):
        print(f"  {line}")
    print()


def seed_air(path: Path, *extra: str) -> list[str]:
    """Run ``scripts/uat_seed_phase13.py`` against the UAT database, mail and intake folder.

    The capture transport is set for this run only, so the verification links the seed reads
    and the quote and milestone emails it sends land in ``UAT_MAIL_DIR``, never anywhere a
    development backend writes. The seed refuses a capture or intake folder outside the
    database's own directory.
    """
    env = {
        **os.environ,
        "DATABASE_URL": database_url(path),
        "ENVIRONMENT": "development",
        "ALLOW_DEMO_SEED": "true",
        "ACCOUNT_EMAIL_TRANSPORT": "capture",
        "ACCOUNT_EMAIL_CAPTURE_DIR": str(UAT_MAIL_DIR),
        "TARIFF_INTAKE_DIR": str(UAT_INTAKE_DIR),
        "LOG_LEVEL": "WARNING",
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(PHASE13_SEED), *extra],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"the air dataset failed with exit {result.returncode}")
    # The JSON lines are the application's own startup warnings (no help URL, development
    # tracking address), expected in UAT; the report keeps the seed's plain lines.
    return [
        line for line in result.stdout.splitlines() if line.strip() and not line.startswith("{")
    ]


def clear_captured_mail() -> int:
    """Delete captured Customer Account mail. Only ever inside the UAT directory.

    A capture file holds a verification or password-reset link, which is a live credential
    for whatever account it was issued against. Leaving yesterday's links behind for
    today's tester is how a case passes against the wrong message.
    """
    directory = UAT_MAIL_DIR.resolve()
    if directory.parent != UAT_DIR.resolve():
        raise SafetyError(f"{directory} is not inside {UAT_DIR.resolve()}")
    if not directory.exists():
        return 0
    removed = 0
    for captured in directory.glob("*.json"):
        captured.unlink()
        removed += 1
    if not any(directory.iterdir()):
        directory.rmdir()
    return removed


def clear_intake_folder() -> int:
    """Delete the UAT rate-email intake folder. Only ever the one inside the UAT directory."""
    directory = UAT_INTAKE_DIR.resolve()
    if directory.parent != UAT_DIR.resolve():
        raise SafetyError(f"{directory} is not inside {UAT_DIR.resolve()}")
    if not directory.exists():
        return 0
    removed = sum(1 for entry in directory.rglob("*") if entry.is_file())
    shutil.rmtree(directory)
    return removed


def destroy(path: Path) -> None:
    removed = []
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate.name)
    print(f"Removed: {', '.join(removed) if removed else 'nothing (no UAT database present)'}")

    captured = clear_captured_mail()
    print(f"Removed {captured} captured Customer Account message(s) from {UAT_MAIL_DIR}")
    emails = clear_intake_folder()
    print(f"Removed {emails} file(s) from {UAT_INTAKE_DIR}")

    uat_dir = UAT_DIR.resolve()
    if uat_dir.exists() and not any(uat_dir.iterdir()):
        shutil.rmtree(uat_dir)
        print(f"Removed the empty {uat_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the isolated UAT environment.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true", help="Build it if it is not there.")
    action.add_argument("--reset", action="store_true", help="Destroy and rebuild from scratch.")
    action.add_argument("--check", action="store_true", help="Coverage report only.")
    action.add_argument("--destroy", action="store_true", help="Delete the UAT database.")
    action.add_argument(
        "--refresh-fx",
        action="store_true",
        help="Add a fresh demo exchange-rate reading (no network); one counts as live for a day.",
    )
    parser.add_argument("--path", type=Path, default=UAT_DB, help=f"Default: {UAT_DB}")
    args = parser.parse_args(argv)

    try:
        target = validated_target(args.path)
    except SafetyError as refused:
        print(f"Refused: {refused}", file=sys.stderr)
        return 2

    if args.destroy:
        destroy(target)
        return 0
    if args.refresh_fx:
        if not target.exists():
            print(f"No UAT database at {target}. Run with --reset.")
            return 1
        for line in seed_air(target, "--refresh-fx"):
            print(line)
        return 0
    if args.check:
        return report(target)

    if args.create and target.exists():
        print(f"{target} already exists. Use --reset to rebuild it.")
        return report(target)

    create(target, reset=args.reset)
    return report(target)


if __name__ == "__main__":
    raise SystemExit(main())
