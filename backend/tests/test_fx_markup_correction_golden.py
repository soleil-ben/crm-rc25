"""Independent golden tests for the owner's correction of 2026-10-20 (OD-73, OD-74, DEC-0212).

* VND -> CAD at Vietcombank's cash-buying rate (``cash_buy_vnd``) for quotes and vendor bills;
  CAD -> VND at the selling rate (``sell_vnd``), which is also what a CAD invoice paid in VND
  uses.
* A configurable default markup (owner: 2 %) on every surcharge whose rule has no policy of
  its own; a per-rule policy overrides it.

Every expected figure is worked out by hand from the rates and the vendor prices, not read
from the product's output. A failing assertion means the product disagrees with the owner.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.core.enums import Role, RouteGroup
from app.core.time_utils import utcnow
from app.models import AuditEvent, MarkupDefault, ShipmentPackage
from app.pricing.engine import FxView, MasterInput, RulePolicy, Settings, estimate
from app.services import consolidation_service as cs
from app.services import finance_service as fs
from app.services import fx_service
from app.services import pricing_method_service as pms
from app.services import pricing_service as ps
from app.services import tariff_import_service as tis
from tests.conftest import booked_shipment, make_customer, see_committed_changes
from tests.shipment_history_fixtures import detail_url, link_account, sign_in_account
from tests.test_fx_service import SAMPLE_XML
from tests.test_pricing_golden import (
    ALL_RULES,
    C1,
    C2,
    C3,
    CASH_BUY,
    FAKE_CLOTHING,
    HCM,
    SELL,
    core_members,
    delivery_l5a3k6,
    live_fx,
    make_product,
    master_fees,
)
from tests.test_quotes import WORKBOOK, _fee, priced_world  # noqa: F401  (fixture)

D = Decimal
CENT = D("0.01")
TWO_PERCENT = RulePolicy("percent", D("2"), None)

# SAMPLE_XML's CAD row (Vietcombank): Buy 17,886.61, Sell 18,645.39.
BANK_BUY = D("17886.61")
BANK_SELL = D("18645.39")

# The workbook's "watch" surcharge (hcm_air row 18) is 50,000 VND per unit. Two watches:
WATCH_VND = D("100000")
WATCH_COST_CAD = D("5.59")  # 100,000 / 17,886.61 = 5.5908...
WATCH_REVENUE_2PCT = D("5.70")  # 5.59 x 1.02 = 5.7018
WATCH_REVENUE_FIXED_150 = D("7.09")  # 5.59 + 1.50

# Method v0.5 (DEC-0252, on by default): Kango's fixed 19,500 VND/CAD and no default markup.
KANGO_FX = D("19500")
WATCH_COST_V05 = D("5.13")  # 100,000 / 19,500 = 5.1282...
WATCH_REVENUE_V05_FIXED_150 = D("6.63")  # 5.13 + 1.50


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _run(members, *, policies=None, settings=None, fx=None):
    return estimate(
        product=make_product(),
        product_refusal=None,
        delivery=delivery_l5a3k6(),
        master=MasterInput(
            actual_weight_kg=D("21"),
            length_cm=None,
            width_cm=None,
            height_cm=None,
            carton_count=1,
            stored_chargeable_kg=D("21"),
        ),
        members=members,
        rules=ALL_RULES,
        rule_section=HCM,
        policies=policies or {},
        fx=fx or live_fx(),
        settings=settings or Settings(),
    )


# --- Engine -------------------------------------------------------------------------------------


def test_engine_surcharge_revenue_is_vnd_over_cash_buy_with_no_markup_by_default():
    est = _run(core_members({C2}))
    assert est.blocking == []
    fee = master_fees(est, FAKE_CLOTHING)[0]
    # 21 kg x 30,000 = 630,000 VND; / 18,000 (buy) = 35.00. Not / 20,000 (sell) = 31.50.
    assert fee.vendor_fee_vnd == D("630000")
    assert fee.customer_base_cad == D("35.00")
    assert fee.customer_total_cad == D("35.00")
    assert fee.markup_kind == "pass_through"
    assert est.members[C2].surcharge_revenue_cad == D("35.00")
    assert _cents(D("630000") / SELL) == D("31.50") != fee.customer_total_cad
    assert D("18000") == CASH_BUY


def test_engine_default_two_percent_on_the_cent_base():
    est = _run(core_members({C2}), settings=Settings(default_policy=TWO_PERCENT))
    fee = master_fees(est, FAKE_CLOTHING)[0]
    assert fee.customer_base_cad == D("35.00")
    assert fee.customer_total_cad == D("35.70")  # 35.00 x 1.02
    assert (fee.markup_kind, fee.markup_value) == ("percent", D("2"))
    assert est.members[C2].surcharge_revenue_cad == D("35.70")
    assert est.members[C1].surcharge_revenue_cad == D("0")
    # Cost is not marked up: still 35.00 in total across the three children.
    assert sum(est.members[s].surcharge_cost_cad for s in (C1, C2, C3)) == D("35.00")


def test_engine_default_two_percent_with_non_round_rates_rounds_half_up():
    fx = FxView(snapshot_id=11, cash_buy_vnd=D("18520"), sell_vnd=D("19105"), freshness="live")
    est = _run(core_members({C2}), settings=Settings(default_policy=TWO_PERCENT), fx=fx)
    fee = master_fees(est, FAKE_CLOTHING)[0]
    # 630,000 / 18,520 = 34.01727 -> 34.02; x 1.02 = 34.7004 -> 34.70.
    assert fee.customer_base_cad == D("34.02")
    assert fee.customer_total_cad == D("34.70")


def test_engine_default_markup_split_between_two_triggers_by_weight():
    est = _run(core_members({C1, C2}), settings=Settings(default_policy=TWO_PERCENT))
    # 35.70 split 3 : 6 between the triggers.
    assert est.members[C1].surcharge_revenue_cad == D("11.90")
    assert est.members[C2].surcharge_revenue_cad == D("23.80")
    assert est.members[C3].surcharge_revenue_cad == D("0")


@pytest.mark.parametrize(
    ("policy", "expected_total", "kind"),
    [
        (RulePolicy("fixed_cad", D("1.50"), None), D("36.50"), "fixed_cad"),  # 35.00 + 1.50
        (RulePolicy("pass_through", D("0"), None), D("35.00"), "pass_through"),
        (RulePolicy("percent", D("10"), None), D("38.50"), "percent"),  # 35.00 x 1.10
    ],
)
def test_engine_a_per_rule_policy_overrides_the_default(policy, expected_total, kind):
    est = _run(
        core_members({C2}),
        policies={(HCM, FAKE_CLOTHING.stt): policy},
        settings=Settings(default_policy=TWO_PERCENT),
    )
    fee = master_fees(est, FAKE_CLOTHING)[0]
    assert fee.customer_base_cad == D("35.00")
    assert fee.customer_total_cad == expected_total
    assert fee.markup_kind == kind
    assert est.members[C2].surcharge_revenue_cad == expected_total


# --- Service ------------------------------------------------------------------------------------


def _watch_line(version):
    return next(line for line in version.lines if line.stt == 18)


def test_service_direct_surcharge_without_policy_carries_no_markup_under_v05(db, priced_world):  # noqa: F811
    """DEC-0252: under method v0.5 the OD-74 2 % default no longer applies and the watch is
    converted at Kango's fixed 19,500, not Vietcombank's cash-buy rate."""
    _con, kids = priced_world
    snapshot = fx_service.latest_snapshot(db)
    assert (snapshot.cash_buy_vnd, snapshot.sell_vnd) == (BANK_BUY, BANK_SELL)
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    final = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    watch = _watch_line(final)
    assert watch.markup_kind == "none" and D(watch.markup_value) == D("0")
    assert D(watch.cost_vnd) == WATCH_VND
    assert watch.cost_cad == WATCH_COST_V05 == _cents(WATCH_VND / KANGO_FX)
    assert watch.revenue_cad == WATCH_COST_V05
    # 3 kg x 19.00 (under 21 kg) base + the watch.
    assert final.total_revenue_cad == D("57.00") + WATCH_COST_V05


def test_service_rc25_method_still_carries_two_percent(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    pms.update_method_settings(db, {"pricing_method": "rc25"}, actor=None)
    db.commit()
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    final = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    watch = _watch_line(final)
    assert watch.markup_kind == "percent" and D(watch.markup_value) == D("2.00")
    assert watch.cost_cad == WATCH_COST_CAD
    assert watch.revenue_cad == WATCH_REVENUE_2PCT
    assert final.total_revenue_cad == D("54.00") + WATCH_REVENUE_2PCT


def test_changing_the_default_moves_a_new_estimate_not_a_finalised_version(db, priced_world):  # noqa: F811
    con, kids = priced_world
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    final = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    frozen_total = final.total_revenue_cad
    frozen_snapshot = final.snapshot_json

    # Under v0.5 the markup is the method setting (DEC-0252), not the RC-UAT-25 default row.
    pms.update_method_settings(db, {"markup_kind": "fixed_cad", "markup_value": "1.50"}, actor=None)
    db.commit()
    est, _ = ps.estimate_for(db, con)
    fee = next(f for f in est.fees if f.stt == 18)
    assert fee.customer_base_cad == WATCH_COST_V05
    assert fee.customer_total_cad == WATCH_REVENUE_V05_FIXED_150
    assert fee.markup_kind == "fixed_cad"

    db.refresh(final)
    watch = _watch_line(final)
    assert (watch.markup_kind, D(watch.markup_value)) == ("none", D("0"))
    assert watch.revenue_cad == WATCH_COST_V05
    assert final.total_revenue_cad == frozen_total
    assert final.snapshot_json == frozen_snapshot
    assert final.status == "finalized"


# --- API ----------------------------------------------------------------------------------------


def _markup_rows(db) -> int:
    see_committed_changes(db)
    return db.query(MarkupDefault).count()


def test_admin_reads_and_patches_the_default_markup_and_it_is_audited(as_admin, db, priced_world):  # noqa: F811
    before = as_admin.get("/api/v1/pricing/settings")
    assert before.status_code == 200
    body = before.json()
    assert body["default_markup_kind"] == "percent"
    assert D(body["default_markup_value"]) == D("2.00")
    assert _markup_rows(db) == 0  # reading never writes

    changed = as_admin.patch(
        "/api/v1/pricing/settings",
        json={"default_markup_kind": "fixed_cad", "default_markup_value": "1.50"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["default_markup_kind"] == "fixed_cad"
    assert D(changed.json()["default_markup_value"]) == D("1.50")
    assert _markup_rows(db) == 1
    events = db.query(AuditEvent).filter_by(action="pricing.markup_default_update").all()
    assert len(events) == 1
    detail = json.loads(events[0].detail_json)
    assert detail["markup_kind"] == "fixed_cad" and D(detail["markup_value"]) == D("1.50")
    assert events[0].actor_user_id is not None

    again = as_admin.get("/api/v1/pricing/settings").json()
    assert again["default_markup_kind"] == "fixed_cad"
    assert D(again["default_markup_value"]) == D("1.50")
    assert _markup_rows(db) == 1


def test_invalid_kind_or_negative_value_is_422_and_changes_nothing(as_admin, db, priced_world):  # noqa: F811
    for body in (
        {"default_markup_kind": "bonus"},
        {"default_markup_value": "-1"},
        {"default_markup_kind": "percent", "default_markup_value": "-0.01"},
    ):
        response = as_admin.patch("/api/v1/pricing/settings", json=body)
        assert response.status_code == 422, (body, response.text)
    assert _markup_rows(db) == 0
    after = as_admin.get("/api/v1/pricing/settings").json()
    assert (after["default_markup_kind"], D(after["default_markup_value"])) == (
        "percent",
        D("2.00"),
    )
    assert db.query(AuditEvent).filter_by(action="pricing.markup_default_update").count() == 0


def test_pass_through_zeroes_the_value(as_admin, db, priced_world):  # noqa: F811
    response = as_admin.patch(
        "/api/v1/pricing/settings",
        json={"default_markup_kind": "pass_through", "default_markup_value": "5"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["default_markup_kind"] == "pass_through"
    assert D(response.json()["default_markup_value"]) == D("0")
    see_committed_changes(db)
    row = db.query(MarkupDefault).one()
    assert (row.markup_kind, D(row.markup_value)) == ("pass_through", D("0"))
    # A later value alone while pass-through stays zero.
    later = as_admin.patch("/api/v1/pricing/settings", json={"default_markup_value": "3"})
    assert later.status_code == 200
    assert D(later.json()["default_markup_value"]) == D("0")


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING, Role.READ_ONLY_MANAGER])
def test_only_admin_may_patch_the_default_markup(api_for, db, priced_world, role):  # noqa: F811
    client = api_for(role)
    response = client.patch(
        "/api/v1/pricing/settings",
        json={"default_markup_kind": "fixed_cad", "default_markup_value": "9.99"},
    )
    assert response.status_code == 403, response.text
    assert _markup_rows(db) == 0
    assert db.query(AuditEvent).filter_by(action="pricing.markup_default_update").count() == 0


# --- Finance ------------------------------------------------------------------------------------


def test_a_vnd_vendor_bill_converts_each_line_at_cash_buy_and_freezes_it(db, priced_world):  # noqa: F811
    con, _kids = priced_world
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    # Per line: 100,042 / 17,886.61 = 5.5931 -> 5.59; 777,777 / 17,886.61 = 43.4838 -> 43.48.
    # Sum of lines 49.07, whereas converting the total (877,819) would give 49.08.
    lines = [
        {"kind": "base", "amount": "100042"},
        {"kind": "other", "description": "Handling", "amount": "777777"},
    ]
    bill = fs.enter_vendor_invoice(db, con, {"currency": "VND", "lines": lines}, actor=None)
    db.commit()
    assert bill.fx_cash_buy_vnd == BANK_BUY
    assert bill.total_amount == D("877819")
    assert bill.total_cad == D("49.07")
    # Not the selling rate (5.37 + 41.71 = 47.08).
    assert bill.total_cad != D("47.08")

    newer = SAMPLE_XML.replace(b"17,886.61", b"18,500.00").replace(b"18,645.39", b"19,300.00")
    fx_service.sync_once(
        db, fetcher=lambda _u: newer, clock=lambda: utcnow() + timedelta(minutes=5), worker_name="t"
    )
    db.commit()
    assert fx_service.latest_snapshot(db).cash_buy_vnd == D("18500.00")
    fs.approve_vendor_invoice(db, bill, {"variance_reason": "handling"}, actor=None)
    db.commit()
    db.refresh(bill)
    assert bill.fx_cash_buy_vnd == BANK_BUY and bill.total_cad == D("49.07")
    allocations = fs.allocations_for(db, bill.id)
    assert sum(allocations.values()) == D("49.07")


def test_a_vnd_customer_payment_converts_at_sell_of_the_invoice_date(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    assert invoice.total_cad == D("57.00")  # 3 kg x 19.00 under v0.5 (DEC-0252)
    # A reading two days later (a different selling rate) must not be used.
    later = SAMPLE_XML.replace(b"17,886.61", b"18,100.00").replace(b"18,645.39", b"19,000.00")
    fx_service.sync_once(
        db, fetcher=lambda _u: later, clock=lambda: utcnow() + timedelta(days=2), worker_name="t"
    )
    db.commit()
    payment = fs.record_payment(
        db,
        invoice,
        {"currency": "VND", "amount_vnd": "500000", "method": "bank_transfer"},
        actor=None,
    )
    db.commit()
    # 500,000 / 18,645.39 = 26.8164 -> 26.82 (not / 17,886.61 = 27.95, not / 19,000 = 26.32).
    assert payment.amount_cad == D("26.82")
    assert payment.currency == "VND"
    assert fs.balance(invoice) == D("30.18")
    receipt = fs.receipt_document(db, payment)
    assert receipt["conversion_vnd_per_cad"] == BANK_SELL


# --- Leakage ------------------------------------------------------------------------------------

DISTINCT_DEFAULT = "7.37"  # a markup value that appears nowhere else
LEAK_EMAIL = "leak.check@demo.example.com"


def _account_world(db, owner):
    version = tis.import_workbook(
        db,
        WORKBOOK.read_bytes(),
        file_name="k.xlsx",
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    tis.activate_version(db, version, actor=None)
    fx_service.sync_once(db, fetcher=lambda _u: SAMPLE_XML, clock=utcnow, worker_name="t")
    db.commit()
    kids = []
    for i, kg in enumerate((3, 6, 12)):
        customer = owner if i == 0 else make_customer(db, email=f"leak{i}@demo.example.com")
        shipment = booked_shipment(db, customer, RouteGroup.VCA)
        for package in db.query(ShipmentPackage).filter_by(shipment_id=shipment.id):
            package.weight_kg = D(kg)
            package.weight_value = D(kg)
            package.length_cm = package.width_cm = package.height_cm = None
        kids.append(shipment)
    db.commit()
    con = cs.create_consolidation(
        db,
        {
            "solaris_service": "air_standard",
            "origin": "HCM",
            "vendor_reference": "BBBBB",
            "actual_weight_kg": "21",
        },
        actor=None,
    )
    for shipment in kids:
        cs.add_member(db, con, shipment, actor=None)
    db.commit()
    return con, kids


def _forbidden_in(text: str, extra: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    hits = [w for w in ("markup", "cash_buy", "cost", "vendor", "17886", "18645") if w in lowered]
    hits += [w for w in extra if w in text]
    return hits


def test_no_account_or_public_response_carries_markup_or_vendor_cost(
    account_client, account_db, account_users, captured_mail
):
    db = account_db
    owner = make_customer(db, full_name="Leak Check", email=LEAK_EMAIL)
    link_account(
        account_client, captured_mail, account_users, email_address=LEAK_EMAIL, customer=owner
    )
    _con, kids = _account_world(db, owner)
    pms.update_method_settings(
        db, {"markup_kind": "percent", "markup_value": DISTINCT_DEFAULT}, actor=None
    )
    db.commit()
    _fee(db, kids[0], "hcm_air", 18, description="Watch", quantity=2)
    ps.confirm_rate(db, kids[0], rate=None, reason=None, actor=None)
    final = ps.finalize(db, kids[0], negative_margin_reason=None, actor=None)
    db.commit()
    watch = _watch_line(final)
    # v0.5: 5.13 x 1.0737 = 5.508 -> 5.51: the method's markup setting was applied.
    assert (watch.markup_kind, D(watch.markup_value)) == ("percent", D(DISTINCT_DEFAULT))
    assert watch.revenue_cad == D("5.51")
    invoice = fs.issue_invoice(db, kids[0], actor=None)
    db.commit()
    fs.record_payment(db, invoice, {"amount_cad": "10.00", "method": "cash"}, actor=None)
    db.commit()
    see_committed_changes(db)

    extra = (DISTINCT_DEFAULT, "100000", str(WATCH_COST_V05), "5103000", "285.30", "19500")
    sign_in_account(account_client, LEAK_EMAIL)
    reference = kids[0].public_id
    urls = (
        "/api/v1/account/me",
        "/api/v1/account/profile",
        "/api/v1/account/notifications",
        "/api/v1/account/shipments",
        detail_url(reference),
    )
    for url in urls:
        response = account_client.get(url)
        assert response.status_code == 200, (url, response.text)
        assert _forbidden_in(response.text, extra) == [], url
    listed = account_client.get("/api/v1/account/shipments").json()
    assert reference in json.dumps(listed)  # the shipment really is in the account's view

    account_client.cookies.clear()
    public = account_client.get(f"/api/v1/public/track/{reference}")
    assert public.status_code == 200, public.text
    assert _forbidden_in(public.text, extra) == []
