"""Every link this application generates for a staff member must actually go somewhere.

Why this file exists
--------------------
The shipment-status report shipped a **Returns** row linking to
``/shipments?returns_only=true``. No route accepted ``returns_only`` and no screen read it,
so following the link showed the *unfiltered* shipment list while looking like a list of
returns. It was handed to human testers that way, and three more links in the same class
were found alongside it once anybody looked: ``/shipments?status=active``,
``/follow-ups?status=completed``, and ``/follow-ups?view=open`` and ``?view=due`` — the last
two worse than the rest, because ``view`` *is* read and neither value is one of the
screen's two tab ids, so the page rendered a tab strip with nothing selected and no panel
underneath it.

Spot-checking one link would not have caught the other four. So this file enumerates
**every** link every report and the dashboard can generate, and checks each one against the
routes and query parameters that actually exist.

What the expectations below are, and where they come from
---------------------------------------------------------
``ROUTES`` mirrors ``frontend/src/app/routes.jsx``. ``SUPPORTED_PARAMS`` mirrors the
``params.get`` / ``params.getAll`` calls in the screen behind each route. They are written
out here rather than parsed out of the frontend, because a parser would agree with whatever
the frontend happens to say — including "nothing reads this" — which is the failure being
guarded against. Each entry names its source file so the pairing can be re-checked by hand.

This file does **not** implement ``returns_only``, create a return record, or decide
anything about the return workflow. OD-22 is open, and one of these tests asserts that it
still is.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.core.enums import Role
from app.models import OrganizationSettings, Shipment
from app.services import dashboard_service, report_service
from app.services.activity_service import LifecycleThresholds
from tests.report_fixtures import PERIOD_FROM, PERIOD_TO, TZ, build_dataset

#: Mirrors `frontend/src/app/routes.jsx`. A generated link whose path is not here has no
#: screen behind it and would fall through to NotFoundPage.
ROUTES = {
    "/",
    "/customers",
    "/customers/import",
    "/segments",
    "/shipments",
    "/shipments/new",
    "/follow-ups",
    "/reports",
    "/settings",
}

#: Mirrors the query parameters each screen actually reads.
#:
#: - `/customers`  -> frontend/src/features/customers/CustomerListPage.jsx
#: - `/shipments`  -> frontend/src/features/shipments/ShipmentListPage.jsx
#: - `/follow-ups` -> frontend/src/features/followups/FollowUpsPage.jsx
SUPPORTED_PARAMS: dict[str, set[str]] = {
    "/": set(),
    "/customers": {
        "offset",
        "search",
        "lifecycle_status",
        "preferred_language",
        "primary_route",
        "observed_route",
        "category",
        "owner_user_id",
        "has_overdue_task",
        "has_service_issue",
        "created_from",
        "created_to",
        "include_archived",
        "last_shipment_before_days",
    },
    "/customers/import": set(),
    "/segments": set(),
    "/shipments": {
        "offset",
        "search",
        "route_group",
        "booking_state",
        "operational_state",
        "owner_user_id",
        "exceptions_only",
        "booked_from",
        "booked_to",
    },
    "/shipments/new": set(),
    "/follow-ups": {"view", "offset", "only_open", "only_overdue", "assignee_user_id"},
    "/reports": {"from", "to", "route_group"},
    "/settings": set(),
}

#: `/follow-ups` renders a TabPanel per id and nothing else. A `view` outside this set
#: produces a page with no content at all -- see `frontend/src/components/ui/index.jsx`,
#: `TabPanel` returns null when `id !== active`.
FOLLOW_UP_VIEWS = {"mine", "all"}

#: The parameter that started this. It must not reappear anywhere.
FORBIDDEN_PARAMS = {"returns_only"}


@pytest.fixture
def org(db) -> OrganizationSettings:
    row = db.scalar(select(OrganizationSettings))
    row.office_timezone = TZ
    db.commit()
    return row


@pytest.fixture
def data(db, org):
    return build_dataset(db)


@pytest.fixture
def period(org) -> report_service.ReportPeriod:
    return report_service.resolve_period(from_date=PERIOD_FROM, to_date=PERIOD_TO, org=org)


def all_report_tables(db, period, org) -> list:
    """Every report an Admin can see — the widest set, so nothing is skipped."""
    return report_service.build_all(
        db,
        period=period,
        thresholds=LifecycleThresholds.from_settings(org),
        route_groups=None,
        role=Role.ADMIN.value,
    )


def report_links(db, period, org) -> list[tuple[str, str]]:
    """``(where it came from, the link)`` for every row of every report."""
    found: list[tuple[str, str]] = []
    for table in all_report_tables(db, period, org):
        for row in table.rows:
            link = row.get("link")
            if link:
                found.append(
                    (f"report {table.key} row {row.get('state') or row.get('measure')}", link)
                )
    return found


def dashboard_links(db, period) -> list[tuple[str, str]]:
    summary = dashboard_service.build_summary(
        db,
        org=db.scalar(select(OrganizationSettings)),
        period_start=period.start_utc,
        period_end=period.end_utc,
        viewer_user_id=None,
    )
    found = [(f"dashboard kpi {card.key}", card.link) for card in summary.kpis]
    found += [(f"dashboard queue {card.key}", card.link) for card in summary.queues]
    for row in summary.route_mix:
        if row.get("link"):
            found.append((f"dashboard route_mix {row.get('route_group')}", row["link"]))
    for row in summary.lifecycle_mix:
        if row.get("link"):
            found.append((f"dashboard lifecycle_mix {row.get('status')}", row["link"]))
    return found


def every_generated_link(db, period, org) -> list[tuple[str, str]]:
    return report_links(db, period, org) + dashboard_links(db, period)


# --- The link that started this ----------------------------------------------


def test_no_generated_staff_link_targets_an_unsupported_returns_only_filter(db, data, period, org):
    """The specific defect: a drill-through to a filter that exists nowhere."""
    offenders = []
    for where, link in every_generated_link(db, period, org):
        params = parse_qs(urlsplit(link).query)
        for forbidden in FORBIDDEN_PARAMS & set(params):
            offenders.append(f"{where} -> {link} (uses {forbidden})")
    assert offenders == [], "links naming a filter nothing implements:\n  " + "\n  ".join(offenders)


def test_the_returns_row_carries_no_drill_through_at_all(db, data, period):
    """Not merely "no returns_only" — no link of any kind, to anywhere."""
    table = report_service.shipment_status(db, period, None)
    returns = [row for row in table.rows if row["group"] == "returns"]
    assert len(returns) == 1
    assert "link" not in returns[0], (
        "the returns row must not link anywhere. Every available destination would "
        "answer OD-22 question 1 by implementation."
    )


def test_the_returns_row_is_still_truthful(db, data, period):
    """Value and label are kept, because they are true. Only the dead action went."""
    table = report_service.shipment_status(db, period, None)
    row = next(r for r in table.rows if r["group"] == "returns")

    expected = db.scalar(select(Shipment).where(Shipment.is_return.is_(True)).limit(1))
    assert expected is not None, (
        "the fixture's return shipment is what makes this test mean anything"
    )

    assert row["group_label"] == "Returns"
    assert row["state_label"] == "Return shipments handed over in period"
    assert row["count"] == 1
    # The neutral explanation: unavailable pending the decision, with no suggestion that
    # a return-shipment workflow exists.
    assert "no return-shipment list to open" in row["definition"]
    assert "undecided" in row["definition"]


def test_the_returns_note_does_not_imply_a_return_workflow_exists(db, data, period):
    table = report_service.shipment_status(db, period, None)
    row = next(r for r in table.rows if r["group"] == "returns")
    text = row["definition"].lower()
    for forbidden in ("create a return", "book a return", "coming soon", "not yet available"):
        assert forbidden not in text, f"the note implies a workflow exists: {row['definition']!r}"


# --- Every other drill-through still works -----------------------------------


def test_every_generated_link_names_a_route_that_exists(db, data, period, org):
    offenders = []
    for where, link in every_generated_link(db, period, org):
        path = urlsplit(link).path
        if path not in ROUTES:
            offenders.append(f"{where} -> {link} (path {path!r})")
    assert offenders == [], "links to a path with no screen:\n  " + "\n  ".join(offenders)


def test_every_generated_link_uses_only_parameters_its_screen_reads(db, data, period, org):
    offenders = []
    for where, link in every_generated_link(db, period, org):
        split = urlsplit(link)
        supported = SUPPORTED_PARAMS[split.path]
        for key in parse_qs(split.query):
            if key not in supported:
                offenders.append(f"{where} -> {link} (parameter {key!r} is read by nothing)")
    assert offenders == [], "links naming a parameter nothing reads:\n  " + "\n  ".join(offenders)


def test_every_follow_up_link_names_a_tab_that_renders(db, data, period, org):
    """`view` is read, so a wrong value is worse than an ignored one: no panel renders."""
    offenders = []
    for where, link in every_generated_link(db, period, org):
        split = urlsplit(link)
        if split.path != "/follow-ups":
            continue
        for value in parse_qs(split.query).get("view", []):
            if value not in FOLLOW_UP_VIEWS:
                offenders.append(f"{where} -> {link} (view={value!r} renders no panel)")
    assert offenders == [], "follow-up links that render an empty page:\n  " + "\n  ".join(
        offenders
    )


def test_the_drill_throughs_that_did_work_still_do(db, data, period, org):
    """A named sample, so a regression names itself rather than appearing as a count."""
    by_link = {link for _, link in every_generated_link(db, period, org)}

    assert any(link.startswith("/shipments?operational_state=") for link in by_link)
    assert any(link.startswith("/shipments?booking_state=") for link in by_link)
    assert any(link.startswith("/customers?lifecycle_status=") for link in by_link)
    assert any(link.startswith("/customers?created_from=") for link in by_link)
    assert "/shipments?exceptions_only=true" in by_link
    assert "/segments" in by_link
    assert "/follow-ups" in by_link


def test_the_active_shipments_card_opens_exactly_what_it_counted(db, data, period):
    """The card is built from the same constant as its count, so they cannot disagree."""
    summary = dashboard_service.build_summary(
        db,
        org=db.scalar(select(OrganizationSettings)),
        period_start=period.start_utc,
        period_end=period.end_utc,
        viewer_user_id=None,
    )
    card = next(card for card in summary.kpis if card.key == "active_shipments")
    params = parse_qs(urlsplit(card.link).query)
    assert params["booking_state"] == ["confirmed"]
    assert set(params["operational_state"]) == {
        state.value for state in dashboard_service.ACTIVE_OPERATIONAL_STATES
    }


# --- Nothing was invented to make any of this work ---------------------------


def test_no_return_shipment_was_manufactured_by_this_correction(db, data, period):
    """The fixture's single return is the one that was always there. Nothing was added.

    `tests/report_fixtures.py` builds one deliberate return so the counting rule in
    `CRM.md` section 4 can be pinned. The correction to the report row did not add a
    second, and did not add one anywhere else.
    """
    returns = db.scalars(select(Shipment).where(Shipment.is_return.is_(True))).all()
    assert len(returns) == 1
    assert all(shipment.return_of_shipment_id is not None for shipment in returns)


def test_no_service_writes_is_return_or_return_of_shipment_id():
    """The columns are still read-only in practice. This is what OD-22 is *about*.

    If a workflow is ever built, this test fails and must be deleted deliberately — which
    is the point. It should not be possible to grow a return workflow by accident while
    the decision is open.
    """
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    # `app/models` is excluded on purpose: that is where the two columns are *declared*,
    # and a declaration is not a write. Everywhere a value could be set is covered.
    searched = [app / "services", app / "api", app / "schemas"]
    # An attribute assignment or a keyword argument, but not `==`, and not a dict key
    # (which uses `:` and is how the export names its output column).
    write = re.compile(r"\b(?:is_return|return_of_shipment_id)\s*=(?!=)")

    writers = []
    for root in searched:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for number, line in enumerate(source.splitlines(), start=1):
                if write.search(line):
                    writers.append(f"{path.relative_to(app).as_posix()}:{number}: {line.strip()}")

    assert writers == [], (
        "something now writes a return shipment field while OD-22 is open:\n  "
        + "\n  ".join(writers)
    )


def test_od_22_is_still_open_and_unanswered():
    """The correction removed a dead control. It did not answer the decision."""
    import json
    from pathlib import Path

    register = json.loads(
        (Path(__file__).resolve().parents[2] / "docs" / "OWNER_DECISIONS.json").read_text(
            encoding="utf-8"
        )
    )
    record = next(d for d in register["decisions"] if int(d["id"]) == 22)
    assert record["status"] == "open"
    assert record["owner_answer"] is None
    assert record["date_decided"] is None
    assert record["implementation_status"] == "not_implemented"
    assert len(record["return_questions"]) == 12
