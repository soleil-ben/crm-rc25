"""Every report metric, reconciled against an independent calculation (DEC-0077).

The rule this file follows: **the assertion must not use the code under test to work out
what the answer should be.** Each expected value is recomputed here by loading the rows and
counting them in plain Python, using the definition as written in prose rather than the
service's SQL. A test that called the same query would only prove the query is
deterministic; it would not catch a wrong *definition*, which is the failure that actually
matters in a reporting feature.

The dataset in ``report_fixtures`` is deliberately awkward — drafts, a cancellation, a
cancel-and-rebook pair, a return, a merged customer, a three-package two-leg shipment,
three currencies, and two shipments straddling local midnight — so a metric that quietly
counts the wrong rows has somewhere to go wrong.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.enums import BookingState, LifecycleStatus, OperationalState, Role
from app.core.time_utils import in_zone, local_midnight_utc
from app.models import Customer, OrganizationSettings, Shipment
from app.services import report_service
from app.services.activity_service import LifecycleThresholds
from tests.report_fixtures import PERIOD_FROM, PERIOD_TO, TZ, build_dataset, toronto


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


@pytest.fixture
def thresholds(org) -> LifecycleThresholds:
    return LifecycleThresholds.from_settings(org)


# --- Independent recomputation helpers ---------------------------------------
#
# These load rows and apply the definition in prose. They share nothing with
# ``report_service``.


def _all_shipments(db) -> list[Shipment]:
    return list(db.scalars(select(Shipment)).all())


def _september_window() -> tuple[datetime, datetime]:
    """[start, end) for September 2026 in Toronto, computed here rather than imported."""
    start = local_midnight_utc(date(2026, 9, 1), TZ)
    end = local_midnight_utc(date(2026, 10, 1), TZ)
    return start, end


def _is_qualifying(shipment: Shipment) -> bool:
    return (
        shipment.booking_state == BookingState.CONFIRMED
        and shipment.first_handoff_at is not None
        and shipment.cancelled_at is None
        and shipment.is_return is False
    )


def _qualifying_in_september(db) -> list[Shipment]:
    start, end = _september_window()
    return [
        shipment
        for shipment in _all_shipments(db)
        if _is_qualifying(shipment) and start <= shipment.first_handoff_at < end
    ]


def _rows_by(table: report_service.ReportTable, key: str, value: str) -> list[dict]:
    return [row for row in table.rows if row.get(key) == value]


# --- The fixture itself ------------------------------------------------------


def test_the_fixture_contains_every_edge_case_the_definitions_name(db, data):
    """If this drifts, every reconciliation below is weaker than it looks."""
    shipments = _all_shipments(db)
    assert any(s.booking_state == BookingState.DRAFT for s in shipments)
    assert any(s.cancelled_at is not None for s in shipments)
    assert any(s.rebooked_to_shipment_id is not None for s in shipments)
    assert any(s.is_return for s in shipments)
    assert any(s.currency is None for s in shipments)
    assert len({s.currency for s in shipments if s.currency}) >= 3
    assert (
        db.scalar(select(Customer).where(Customer.merged_into_customer_id.is_not(None))) is not None
    )

    # The multi-package shipment really has three packages and two legs.
    parent = data.shipment("repeat_sep")
    assert len(parent.packages) == 3
    assert len(parent.legs) == 2


# --- Period boundaries -------------------------------------------------------


def test_a_period_is_cut_at_local_midnight_not_utc_midnight(org):
    period = report_service.resolve_period(from_date=PERIOD_FROM, to_date=PERIOD_TO, org=org)
    # Toronto is UTC-4 in September, so local midnight on 1 September is 04:00 UTC.
    assert period.start_utc == datetime(2026, 9, 1, 4, 0)
    assert period.end_utc == datetime(2026, 10, 1, 4, 0)
    # And the end is exclusive: the last instant included is 03:59:59 on 1 October UTC.
    assert period.end_utc > local_midnight_utc(date(2026, 9, 30), TZ)


def test_a_late_evening_handoff_belongs_to_the_local_day_not_the_utc_one(db, data, period):
    late = data.shipment("late_september")
    early = data.shipment("early_october")

    # In UTC both are in October. In Toronto they are in different months, which is what
    # a Toronto operator means.
    assert late.first_handoff_at.month == 10
    assert in_zone(late.first_handoff_at, TZ).month == 9
    assert in_zone(early.first_handoff_at, TZ).month == 10

    volume = report_service.shipment_volume(db, period, None)
    total = sum(row["total"] for row in volume.rows)
    assert late.id in {s.id for s in _qualifying_in_september(db)}
    assert early.id not in {s.id for s in _qualifying_in_september(db)}
    assert total == len(_qualifying_in_september(db))


def test_adjacent_periods_tile_without_gap_or_overlap(db, org):
    september = report_service.resolve_period(
        from_date=date(2026, 9, 1), to_date=date(2026, 9, 30), org=org
    )
    october = report_service.resolve_period(
        from_date=date(2026, 10, 1), to_date=date(2026, 10, 31), org=org
    )
    assert september.end_utc == october.start_utc


@pytest.mark.parametrize(
    ("from_date", "to_date"),
    [
        (date(2026, 9, 30), date(2026, 9, 1)),  # reversed
        (date(2020, 1, 1), date(2026, 9, 30)),  # too long
    ],
)
def test_an_unbounded_or_reversed_range_is_refused(org, from_date, to_date):
    from app.services.errors import ValidationError

    with pytest.raises(ValidationError):
        report_service.resolve_period(from_date=from_date, to_date=to_date, org=org)


@pytest.mark.parametrize(
    ("span", "expected"),
    [(1, "day"), (31, "day"), (32, "week"), (182, "week"), (183, "month"), (731, "month")],
)
def test_granularity_follows_the_span_rather_than_a_guess(span, expected):
    assert report_service.granularity_for(span) == expected


# --- Customer growth ---------------------------------------------------------


def test_customer_growth_counts_creations_and_excludes_merged_records(db, data, period):
    table = report_service.customer_growth(db, period)
    start, end = _september_window()

    expected_created = sum(
        1
        for customer in db.scalars(select(Customer)).all()
        if customer.merged_into_customer_id is None and start <= customer.created_at < end
    )
    assert sum(row["created"] for row in table.rows) == expected_created

    # The absorbed record was created in August and merged, so it appears in neither the
    # created column nor the cumulative one.
    absorbed = data.customer("absorbed")
    assert absorbed.merged_into_customer_id is not None
    expected_cumulative = sum(
        1
        for customer in db.scalars(select(Customer)).all()
        if customer.merged_into_customer_id is None and customer.created_at < end
    )
    assert table.rows[-1]["cumulative"] == expected_cumulative


def test_customer_growth_emits_every_bucket_including_the_empty_ones(db, data, period):
    table = report_service.customer_growth(db, period)
    assert len(table.rows) == 30  # one per day in September
    assert [row["bucket"] for row in table.rows][0] == "2026-09-01"
    assert [row["bucket"] for row in table.rows][-1] == "2026-09-30"
    # A quiet day is a true zero, not a missing value.
    quiet = [row for row in table.rows if row["bucket"] == "2026-09-09"]
    assert quiet and quiet[0]["created"] == 0


def test_cumulative_is_computed_independently_of_the_created_column(db, data, period):
    """A running sum of `created` would be wrong for anyone created before the period."""
    table = report_service.customer_growth(db, period)
    assert table.rows[0]["cumulative"] > table.rows[0]["created"]


# --- Lifecycle ---------------------------------------------------------------


def test_lifecycle_distribution_counts_each_living_customer_exactly_once(
    db, data, period, thresholds
):
    table = report_service.customer_lifecycle(db, period, thresholds)
    living = [
        customer
        for customer in db.scalars(select(Customer)).all()
        if customer.merged_into_customer_id is None
    ]
    assert sum(row["count"] for row in table.rows) == len(living)
    assert table.summary["total_customers"] == len(living)
    assert table.scope == report_service.CURRENT


def test_a_customer_with_no_qualifying_shipment_is_a_prospect(db, data, period, thresholds):
    table = report_service.customer_lifecycle(db, period, thresholds)
    prospects = _rows_by(table, "status", LifecycleStatus.PROSPECT)[0]["count"]
    expected = 0
    for customer in db.scalars(select(Customer)).all():
        if customer.merged_into_customer_id is not None or customer.is_archived:
            continue
        qualifying = [
            s for s in _all_shipments(db) if s.customer_id == customer.id and _is_qualifying(s)
        ]
        if not qualifying:
            expected += 1
    assert prospects == expected


# --- Route mix ---------------------------------------------------------------


def test_route_mix_counts_qualifying_shipments_once_each(db, data, period):
    table = report_service.route_mix(db, period, None)
    expected: dict[str, int] = {}
    for shipment in _qualifying_in_september(db):
        expected[shipment.route_group] = expected.get(shipment.route_group, 0) + 1

    actual = {row["route_group"]: row["count"] for row in table.rows if row["count"]}
    assert actual == expected
    assert table.summary["total"] == len(_qualifying_in_september(db))


def test_route_mix_shares_sum_to_one_and_are_none_when_nothing_shipped(db, data, org):
    period = report_service.resolve_period(from_date=PERIOD_FROM, to_date=PERIOD_TO, org=org)
    table = report_service.route_mix(db, period, None)
    shares = [row["share"] for row in table.rows if row["count"]]
    assert abs(sum(shares) - 1.0) < 0.001

    quiet = report_service.resolve_period(
        from_date=date(2019, 1, 1), to_date=date(2019, 1, 31), org=org
    )
    empty = report_service.route_mix(db, quiet, None)
    assert all(row["share"] is None for row in empty.rows)
    assert all(row["count"] == 0 for row in empty.rows)


def test_route_mix_honours_a_route_filter(db, data, period):
    from app.core.enums import RouteGroup

    table = report_service.route_mix(db, period, [RouteGroup.CAV.value])
    assert {row["route_group"] for row in table.rows} == {RouteGroup.CAV.value}
    expected = sum(1 for s in _qualifying_in_september(db) if s.route_group == RouteGroup.CAV.value)
    assert table.rows[0]["count"] == expected


def test_an_unknown_route_filter_is_refused(db, period):
    from app.services.errors import ValidationError

    with pytest.raises(ValidationError):
        report_service.route_mix(db, period, ["NOPE"])


# --- Volume ------------------------------------------------------------------


def test_shipment_volume_totals_match_the_qualifying_set(db, data, period):
    table = report_service.shipment_volume(db, period, None)
    assert sum(row["total"] for row in table.rows) == len(_qualifying_in_september(db))


def test_shipment_volume_buckets_by_local_date(db, data, period):
    table = report_service.shipment_volume(db, period, None)
    by_bucket = {row["bucket"]: row["total"] for row in table.rows}
    expected: dict[str, int] = {}
    for shipment in _qualifying_in_september(db):
        label = in_zone(shipment.first_handoff_at, TZ).date().isoformat()
        expected[label] = expected.get(label, 0) + 1
    for label, count in expected.items():
        assert by_bucket[label] == count


# --- Packages and legs are never shipments -----------------------------------


def test_a_three_package_two_leg_shipment_counts_once_everywhere(db, data, period):
    parent = data.shipment("repeat_sep")
    assert len(parent.packages) == 3
    assert len(parent.legs) == 2

    volume = report_service.shipment_volume(db, period, None)
    day = in_zone(parent.first_handoff_at, TZ).date().isoformat()
    bucket = next(row for row in volume.rows if row["bucket"] == day)
    # That day holds exactly this one shipment, and it contributes 1 — not 3, not 2.
    assert bucket["total"] == 1

    # The guard reports packages and legs alongside the shipment count precisely so the
    # difference is visible. This shipment alone accounts for three of the packages and
    # both of the legs, and still contributes 1 to every shipment figure.
    guard = report_service.package_and_leg_guard(db, period)
    expected_packages = sum(len(shipment.packages) for shipment in _qualifying_in_september(db))
    expected_legs = sum(len(shipment.legs) for shipment in _qualifying_in_september(db))
    assert guard["qualifying_shipments"] == len(_qualifying_in_september(db))
    assert guard["packages_on_those_shipments"] == expected_packages == 3
    assert guard["legs_on_those_shipments"] == expected_legs
    # This shipment supplies both of its own legs and all three packages, yet the
    # qualifying-shipment count is the number of shipments, not of packages or legs.
    assert guard["qualifying_shipments"] < guard["packages_on_those_shipments"] + 4


# --- Drafts, cancellations, rebookings, returns -------------------------------


def test_a_draft_appears_only_in_the_booking_state_distribution(db, data, period):
    draft = data.shipment("draft")
    assert draft.public_id is None

    volume = report_service.shipment_volume(db, period, None)
    assert sum(row["total"] for row in volume.rows) == len(_qualifying_in_september(db))
    assert draft.id not in {s.id for s in _qualifying_in_september(db)}

    status = report_service.shipment_status(db, period, None)
    drafts = _rows_by(status, "state", BookingState.DRAFT.value)
    assert drafts[0]["count"] == 1


def test_a_cancelled_booking_is_excluded_from_qualifying_figures(db, data, period):
    cancelled = data.shipment("cancelled")
    assert cancelled.id not in {s.id for s in _qualifying_in_september(db)}

    status = report_service.shipment_status(db, period, None)
    row = _rows_by(status, "state", BookingState.CANCELLED.value)[0]
    expected = sum(
        1
        for s in _all_shipments(db)
        if s.booking_state == BookingState.CANCELLED
        and _september_window()[0] <= s.booking_date < _september_window()[1]
    )
    assert row["count"] == expected


def test_a_cancel_and_rebook_pair_contributes_exactly_one_shipment(db, data, period):
    original = data.shipment("rebooked_from")
    replacement = data.shipment("rebooked_to")
    assert original.rebooked_to_shipment_id == replacement.id

    qualifying_ids = {s.id for s in _qualifying_in_september(db)}
    assert original.id not in qualifying_ids
    assert replacement.id in qualifying_ids

    from app.core.enums import RouteGroup

    table = report_service.route_mix(db, period, [RouteGroup.XUS.value])
    # XUS holds the cancelled original, the replacement, and the cancelled booking from
    # `first_timer`. Only the replacement qualifies.
    assert table.rows[0]["count"] == 1


def test_a_return_is_reported_separately_and_never_added_to_volume(db, data, period):
    returned = data.shipment("return_leg")
    assert returned.is_return is True
    assert returned.id not in {s.id for s in _qualifying_in_september(db)}

    status = report_service.shipment_status(db, period, None)
    row = _rows_by(status, "group", "returns")[0]
    expected = sum(
        1
        for s in _all_shipments(db)
        if s.is_return
        and s.booking_state == BookingState.CONFIRMED
        and s.cancelled_at is None
        and s.first_handoff_at is not None
        and _september_window()[0] <= s.first_handoff_at < _september_window()[1]
    )
    assert row["count"] == expected == 1

    volume = report_service.shipment_volume(db, period, None)
    assert returned.id not in {s.id for s in _qualifying_in_september(db)}
    assert sum(r["total"] for r in volume.rows) == len(_qualifying_in_september(db))


def test_operational_state_distribution_covers_the_qualifying_cohort(db, data, period):
    table = report_service.shipment_status(db, period, None)
    rows = [row for row in table.rows if row["group"] == "operational_state"]
    total = sum(row["count"] for row in rows)
    assert total == len(_qualifying_in_september(db))

    expected: dict[str, int] = {}
    for shipment in _qualifying_in_september(db):
        expected[shipment.operational_state] = expected.get(shipment.operational_state, 0) + 1
    actual = {row["state"]: row["count"] for row in rows}
    assert actual == expected


# --- Merged customers --------------------------------------------------------


def test_a_merged_customer_is_counted_once_not_twice(db, data, period, thresholds):
    survivor = data.customer("survivor")
    absorbed = data.customer("absorbed")
    assert absorbed.merged_into_customer_id == survivor.id

    # The merge moved the absorbed record's shipment to the survivor.
    moved = data.shipment("absorbed_sep")
    db.refresh(moved)
    assert moved.customer_id == survivor.id

    lifecycle = report_service.customer_lifecycle(db, period, thresholds)
    living = [c for c in db.scalars(select(Customer)).all() if c.merged_into_customer_id is None]
    assert sum(row["count"] for row in lifecycle.rows) == len(living)

    repeat = report_service.repeat_customers(db, period, None)
    shipping_ids = {s.customer_id for s in _qualifying_in_september(db)}
    living_ids = {c.id for c in living}
    assert repeat.summary["shipping_customers"] == len(shipping_ids & living_ids)


# --- Repeat share ------------------------------------------------------------


def test_repeat_share_matches_an_independent_lifetime_count(db, data, period):
    table = report_service.repeat_customers(db, period, None)
    _, end = _september_window()

    living_ids = {
        c.id for c in db.scalars(select(Customer)).all() if c.merged_into_customer_id is None
    }
    shipping = {s.customer_id for s in _qualifying_in_september(db)} & living_ids

    expected_repeat = 0
    for customer_id in shipping:
        lifetime = [
            s
            for s in _all_shipments(db)
            if s.customer_id == customer_id and _is_qualifying(s) and s.first_handoff_at < end
        ]
        if len(lifetime) >= 2:
            expected_repeat += 1

    assert table.summary["shipping_customers"] == len(shipping)
    assert table.summary["repeat_customers"] == expected_repeat
    assert table.summary["first_time_customers"] == len(shipping) - expected_repeat
    assert table.summary["share"] == pytest.approx(round(expected_repeat / len(shipping), 4))


def test_repeat_share_is_none_rather_than_zero_when_nobody_shipped(db, data, org):
    quiet = report_service.resolve_period(
        from_date=date(2019, 1, 1), to_date=date(2019, 1, 31), org=org
    )
    table = report_service.repeat_customers(db, quiet, None)
    assert table.summary["share"] is None
    assert table.summary["shipping_customers"] == 0
    assert any("unknown rather than zero" in note for note in table.notes)


def test_repeat_share_is_never_described_as_retention(db, data, period):
    table = report_service.repeat_customers(db, period, None)
    assert "retention" in table.definition.lower()
    assert "not a cohort retention rate" in table.definition.lower()
    assert table.title.lower().find("retention") == -1


def test_lifetime_count_is_as_of_period_end_not_as_of_today(db, data, org):
    """A shipment after the period must not retroactively make somebody a repeat shipper."""
    early = report_service.resolve_period(
        from_date=date(2026, 8, 1), to_date=date(2026, 8, 31), org=org
    )
    table = report_service.repeat_customers(db, early, None)
    # In August the repeat customer had shipped exactly once, so they were not yet a
    # repeat shipper — even though they are one today.
    assert table.summary["shipping_customers"] == 1
    assert table.summary["repeat_customers"] == 0


# --- Follow-ups --------------------------------------------------------------


def test_follow_up_workload_separates_period_figures_from_current_state(db, data, period):
    table = report_service.follow_up_workload(db, period)
    scopes = {row["measure"]: row["scope"] for row in table.rows}
    assert scopes["created"] == report_service.PERIOD
    assert scopes["completed"] == report_service.PERIOD
    assert scopes["open_now"] == report_service.CURRENT
    assert scopes["overdue_now"] == report_service.CURRENT


# --- Exceptions --------------------------------------------------------------


def test_exception_report_counts_current_exception_states(db, data, period):
    table = report_service.shipment_exceptions(db, period, None)
    expected = sum(
        1
        for s in _all_shipments(db)
        if s.cancelled_at is None
        and s.operational_state
        in {
            OperationalState.EXCEPTION.value,
            OperationalState.DELIVERY_ATTEMPTED.value,
            OperationalState.RETURN_IN_PROGRESS.value,
        }
    )
    assert table.summary["total"] == expected
    assert table.scope == report_service.CURRENT


def test_the_exception_report_never_offers_a_connected_api_column(db, data, period):
    table = report_service.shipment_exceptions(db, period, None)
    source_rows = [row for row in table.rows if row["group"] == "tracking_source"]
    keys = {row["key"] for row in source_rows}
    assert keys == {"manual", "external_link", "none"}
    assert "connected_api" not in keys
    assert any("no provider integration is connected" in n.lower() for n in table.notes)


def test_an_exception_shipment_with_no_tracking_reference_is_reported_as_none(db, data, period):
    """A shipment nobody has assigned a carrier to is reported, not dropped."""
    table = report_service.shipment_exceptions(db, period, None)
    rows = {row["key"]: row["count"] for row in table.rows if row["group"] == "tracking_source"}

    # Two shipments are in an exception-family state: one carrying a manual tracking
    # reference, and the return-in-progress one carrying none at all.
    untracked = [
        shipment
        for shipment in _all_shipments(db)
        if shipment.cancelled_at is None
        and shipment.operational_state
        in {
            OperationalState.EXCEPTION.value,
            OperationalState.DELIVERY_ATTEMPTED.value,
            OperationalState.RETURN_IN_PROGRESS.value,
        }
        and not any(
            reference.is_active for leg in shipment.legs for reference in leg.tracking_references
        )
    ]
    assert rows["manual"] == 1
    assert rows["none"] == len(untracked) == 1


# --- Financials --------------------------------------------------------------


def test_financial_summary_never_combines_currencies(db, data, period):
    table = report_service.financial_summary(db, period, None, include_costs=True)
    currencies = [row["currency"] for row in table.rows]
    assert currencies == sorted(currencies)
    assert len(currencies) == len(set(currencies))

    expected_currencies = {
        s.currency for s in _qualifying_in_september(db) if s.currency is not None
    }
    assert set(currencies) == expected_currencies
    assert len(expected_currencies) >= 2


def test_recorded_revenue_matches_an_independent_sum(db, data, period):
    table = report_service.financial_summary(db, period, None, include_costs=True)
    expected: dict[str, Decimal] = {}
    for shipment in _qualifying_in_september(db):
        if shipment.currency is None or shipment.selling_amount is None:
            continue
        total = Decimal(str(shipment.selling_amount))
        for component, sign in (
            (shipment.surcharges_amount, 1),
            (shipment.discount_amount, -1),
            (shipment.refund_amount, -1),
        ):
            if component is not None:
                total += sign * Decimal(str(component))
        expected[shipment.currency] = expected.get(shipment.currency, Decimal("0")) + total

    actual = {row["currency"]: row["recorded_revenue"] for row in table.rows}
    for currency, value in expected.items():
        assert actual[currency] == value


def test_a_shipment_with_no_currency_is_unknown_and_not_folded_into_a_default(db, data, period):
    table = report_service.financial_summary(db, period, None, include_costs=True)
    unknown = sum(1 for s in _qualifying_in_september(db) if s.currency is None)
    assert unknown >= 1
    assert table.summary["unknown_currency_shipments"] == unknown
    assert any("no recorded currency" in note for note in table.notes)


def test_a_missing_cost_leaves_gross_profit_unknown_rather_than_equal_to_revenue(db, data, period):
    table = report_service.financial_summary(db, period, None, include_costs=True)
    usd = next(row for row in table.rows if row["currency"] == "USD")
    # The USD shipment records revenue and no cost.
    assert usd["recorded_revenue"] is not None
    assert usd["shipments_with_cost"] == 0
    assert usd["recorded_cost"] is None
    assert usd["gross_profit"] is None


def test_cost_columns_are_absent_not_null_for_a_caller_without_cost_permission(db, data, period):
    table = report_service.financial_summary(db, period, None, include_costs=False)
    assert all("recorded_cost" not in row for row in table.rows)
    assert all("gross_profit" not in row for row in table.rows)
    assert all(column.key != "recorded_cost" for column in table.columns)
    # Revenue is still there.
    assert any(row.get("recorded_revenue") is not None for row in table.rows)


def test_the_financial_report_is_absent_entirely_without_financial_read():
    # Marketing is the role without financial:read since the merge (DEC-0088); Operations
    # inherited Customer service's, and is asserted below to receive the report.
    assert report_service.FINANCIAL_REPORT_KEY not in report_service.available_report_keys(
        Role.MARKETING
    )
    assert report_service.FINANCIAL_REPORT_KEY in report_service.available_report_keys(
        Role.OPERATIONS
    )
    assert report_service.FINANCIAL_REPORT_KEY in report_service.available_report_keys(Role.ADMIN)
    assert report_service.FINANCIAL_REPORT_KEY in report_service.available_report_keys(
        Role.READ_ONLY_MANAGER
    )


def test_asking_for_a_report_a_role_may_not_see_reads_as_unknown_not_forbidden(
    db, data, period, thresholds
):
    """A caller without financial:read should not learn a financial report exists."""
    # Marketing, not Operations: see DEC-0088.
    from app.services.errors import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        report_service.build_report(
            db,
            report_service.FINANCIAL_REPORT_KEY,
            period=period,
            thresholds=thresholds,
            route_groups=None,
            role=Role.MARKETING,
        )
    assert "unknown report" in str(excinfo.value).lower()


# --- No invented comparisons -------------------------------------------------


def test_no_report_invents_a_comparison_a_trend_or_a_delta(db, data, period, thresholds):
    tables = report_service.build_all(
        db, period=period, thresholds=thresholds, route_groups=None, role=Role.ADMIN
    )
    forbidden = {
        "change",
        "delta",
        "previous",
        "prior",
        "trend_pct",
        "growth_pct",
        "vs_previous",
        "comparison",
    }
    for table in tables:
        for column in table.columns:
            assert column.key not in forbidden, f"{table.key}.{column.key}"
        for row in table.rows:
            assert not (set(row) & forbidden), f"{table.key}: {set(row) & forbidden}"


def test_the_report_set_says_plainly_that_no_comparison_is_shown(db, data, period):
    notes = report_service.coverage_notes(db, period)
    assert any("no prior-period comparison" in note.lower() for note in notes)


def test_coverage_notes_disclose_drafts_cancellations_and_merges(db, data, period):
    notes = " ".join(report_service.coverage_notes(db, period)).lower()
    assert "draft" in notes
    assert "cancelled" in notes
    assert "merged" in notes


# --- Freshness is never fabricated -------------------------------------------


def test_no_report_reports_a_carrier_freshness_or_sync_time(db, data, period, thresholds):
    """DEC-0075: no provider is connected, so no such value exists to report."""
    tables = report_service.build_all(
        db, period=period, thresholds=thresholds, route_groups=None, role=Role.ADMIN
    )
    banned = ("last_sync", "last_successful_sync", "freshness", "last_carrier_event", "stale_at")
    for table in tables:
        serialized = str(table.to_dict()).lower()
        for term in banned:
            assert term not in serialized, f"{table.key} mentions {term}"


# --- Determinism -------------------------------------------------------------


def test_reports_are_stable_across_repeated_calls(db, data, period, thresholds):
    first = report_service.build_all(
        db, period=period, thresholds=thresholds, route_groups=None, role=Role.ADMIN
    )
    second = report_service.build_all(
        db, period=period, thresholds=thresholds, route_groups=None, role=Role.ADMIN
    )
    assert [t.to_dict() for t in first] == [t.to_dict() for t in second]


def test_every_declared_report_key_builds(db, data, period, thresholds):
    for key in report_service.available_report_keys(Role.ADMIN):
        table = report_service.build_report(
            db,
            key,
            period=period,
            thresholds=thresholds,
            route_groups=None,
            role=Role.ADMIN,
        )
        assert table.key == key
        assert table.definition
        assert table.columns
        assert table.scope in (report_service.PERIOD, report_service.CURRENT)


def test_every_row_carries_every_declared_column(db, data, period, thresholds):
    """A column the rows do not fill would render as an empty table cell."""
    for key in report_service.available_report_keys(Role.ADMIN):
        table = report_service.build_report(
            db,
            key,
            period=period,
            thresholds=thresholds,
            route_groups=None,
            role=Role.ADMIN,
        )
        for row in table.rows:
            for column in table.columns:
                assert column.key in row, f"{key}: row missing {column.key}"


def test_a_report_period_defaults_to_the_last_thirty_days(org):
    period = report_service.resolve_period(from_date=None, to_date=None, org=org)
    assert (period.to_date - period.from_date) == timedelta(days=29)
    assert period.granularity == "day"


def test_toronto_helper_round_trips_through_the_zone():
    """Guards the fixture helper itself: a wrong offset would silently move every row."""
    instant = toronto(2026, 9, 30, 23, 30)
    assert in_zone(instant, TZ).hour == 23
    assert in_zone(instant, TZ).date() == date(2026, 9, 30)
