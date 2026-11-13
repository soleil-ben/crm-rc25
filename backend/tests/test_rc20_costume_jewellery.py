"""Costume jewellery (HCM air row 27, ``manual_amount``): the vendor's cost and the customer
price, both entered by staff (owner Ben, 2026-10-23; DEC-0228, after DEC-0225).

* The line needs **both** the vendor's cost (VND, ``shipment_fee_lines.manual_unit_price_vnd``)
  and the customer price (CAD, ``fee_line_manual_prices``); no prefilled value. Until both are
  entered a blocking issue names what is missing.
* The customer is billed exactly the CAD price (no conversion, no markup); the cost is the VND
  at the buy rate. Quote lines, totals, profitability and the customer view agree.
* ``PATCH /shipments/{id}/fee-lines/{line_id}`` takes either or both; validated, only for a
  ``manual_amount`` line, refused on a locked master, audited with from/to.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.core.enums import Role
from app.models import AuditEvent, FeeLineManualPrice, ShipmentFeeLine
from app.services import consolidation_service as cs
from app.services import fx_service
from app.services import pricing_service as ps
from app.services import quote_offer_service as qos
from app.services.errors import ConflictError, ValidationError
from tests.conftest import see_committed_changes
from tests.test_quotes import _fee, priced_world  # noqa: F401 - fixture

D = Decimal
CENT = D("0.01")


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _jewellery(db, shipment, **extra):
    return _fee(db, shipment, "hcm_air", 27, description="Bông tai mỹ ký", **extra)


def _audits(db, action):
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _issue(est, line_id):
    found = [i for i in est.blocking if i.fee_line_id == line_id]
    return found[0].message if found else None


def _url(shipment, line):
    return f"/api/v1/shipments/{shipment.id}/fee-lines/{line.id}"


# --- Blocking until both are entered ---------------------------------------------------------


def test_a_new_line_has_no_prefilled_value_and_names_both_missing(db, priced_world):  # noqa: F811
    con, kids = priced_world
    line = _jewellery(db, kids[2])
    assert line.manual_unit_price_vnd is None and line.weight_kg is None
    assert db.query(FeeLineManualPrice).filter_by(fee_line_id=line.id).count() == 0
    message = _issue(ps.estimate_for(db, con)[0], line.id)
    assert message is not None
    assert "the vendor's cost (VND) and the customer price (CAD)" in message
    ps.confirm_rate(db, kids[2], rate=None, reason=None, actor=None)
    with pytest.raises(ConflictError):
        ps.finalize(db, kids[2], negative_margin_reason="test", actor=None)
    db.rollback()


def test_only_the_vnd_cost_entered_names_the_customer_price(db, priced_world):  # noqa: F811
    con, kids = priced_world
    line = _jewellery(db, kids[2])
    ps.set_fee_line_amount(db, kids[2], line.id, "450000", actor=None)
    db.commit()
    message = _issue(ps.estimate_for(db, con)[0], line.id)
    assert "enter the customer price (CAD) for this line" in message
    assert "VND" not in message


def test_only_the_customer_price_entered_names_the_vnd_cost(db, priced_world):  # noqa: F811
    con, kids = priced_world
    line = _jewellery(db, kids[2])
    ps.set_fee_line_amount(db, kids[2], line.id, customer_price_cad="49.99", actor=None)
    db.commit()
    message = _issue(ps.estimate_for(db, con)[0], line.id)
    assert "enter the vendor's cost (VND) for this line" in message
    assert "CAD" not in message
    ps.confirm_rate(db, kids[2], rate=None, reason=None, actor=None)
    with pytest.raises(ConflictError) as refused:
        ps.finalize(db, kids[2], negative_margin_reason="test", actor=None)
    assert "vendor's cost (VND)" in json.dumps(refused.value.detail)
    db.rollback()


# --- Both entered: billed at the CAD price, cost at the buy rate -----------------------------


def test_both_entered_bill_the_cad_price_exactly_and_cost_the_vnd_at_the_buy_rate(
    db,
    priced_world,  # noqa: F811
):
    con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    ps.set_fee_line_amount(db, shipment, line.id, "450000", customer_price_cad="49.99", actor=None)
    db.commit()
    buy = D(19500)  # method v0.5 costs at Kango's fixed rate (DEC-0252)
    cost_cad = _cents(D(450000) / buy)

    est, _ = ps.estimate_for(db, con)
    assert _issue(est, line.id) is None
    fee = next(f for f in est.fees if f.section == "hcm_air" and f.stt == 27)
    assert fee.vendor_fee_vnd == D(450000) and fee.master_wide is False
    assert fee.cost_alloc_vnd == {shipment.id: D(450000)}
    assert fee.cost_alloc_cad == {shipment.id: cost_cad}
    # Exactly the entered price: no conversion and no 2 % default markup on top.
    assert fee.customer_price_cad == D("49.99")
    assert fee.customer_base_cad == fee.customer_total_cad == D("49.99")
    assert fee.revenue_alloc_cad == {shipment.id: D("49.99")}
    assert (fee.markup_kind, fee.markup_value) == ("manual_price", D(0))

    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    final = ps.finalize(db, shipment, negative_margin_reason="test", actor=None)
    db.commit()
    assert final.status == "finalized"
    row27 = [x for x in final.lines if x.section == "hcm_air" and x.stt == 27]
    assert len(row27) == 1
    assert row27[0].revenue_cad == D("49.99")
    assert (row27[0].cost_vnd, row27[0].cost_cad) == (D(450000), cost_cad)
    assert row27[0].markup_kind == "manual_price"
    # Totals and profitability use the same figure.
    assert final.surcharge_revenue_cad == D("49.99")
    assert final.total_revenue_cad == final.base_revenue_cad + D("49.99")
    assert final.gross_profit_cad == final.total_revenue_cad - final.allocated_cost_cad
    # The customer view shows the entered price.
    view = qos.build_customer_view(shipment, final)
    assert [s["amount_cad"] for s in view["surcharges"]] == ["49.99"]
    assert D(view["total_cad"]) == final.total_revenue_cad


def test_changing_the_customer_price_revokes_the_rate_confirmation(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    ps.set_fee_line_amount(db, shipment, line.id, "450000", customer_price_cad="40", actor=None)
    draft = ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    db.commit()
    assert draft.rate_confirmed_at is not None
    ps.set_fee_line_amount(db, shipment, line.id, customer_price_cad="41", actor=None)
    draft, _ = ps.reprice(db, shipment, actor=None)
    db.commit()
    assert draft.rate_confirmed_at is None
    assert draft.surcharge_revenue_cad == D("41.00")


def test_a_line_priced_per_kg_under_the_old_reading_keeps_its_re_enter_block(
    db,
    priced_world,  # noqa: F811
):
    con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    line.weight_kg = D("2.5")
    line.manual_unit_price_vnd = D("150000")
    db.commit()
    message = _issue(ps.estimate_for(db, con)[0], line.id)
    assert "re-enter the quoted amount" in message and "customer price (CAD)" in message
    # The CAD price alone does not clear it: the VND must be re-entered.
    ps.set_fee_line_amount(db, shipment, line.id, customer_price_cad="30", actor=None)
    db.commit()
    message = _issue(ps.estimate_for(db, con)[0], line.id)
    assert "re-enter the quoted amount" in message and "customer price" not in message
    ps.set_fee_line_amount(db, shipment, line.id, "400000", actor=None)
    db.commit()
    assert db.get(ShipmentFeeLine, line.id).weight_kg is None
    assert _issue(ps.estimate_for(db, con)[0], line.id) is None


# --- PATCH validation, scope, lock, permissions, audit ---------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["0", "0.001", "0.004", "-5", "NaN", "Infinity", "-Infinity", "1e30", "10000000000", "abc"],
)
def test_customer_price_refusals_are_422(db, priced_world, api_for, bad):  # noqa: F811
    _con, kids = priced_world
    line = _jewellery(db, kids[2])
    ops = api_for(Role.OPERATIONS)
    refused = ops.patch(_url(kids[2], line), json={"customer_price_cad": bad})
    assert refused.status_code == 422, (bad, refused.text)
    see_committed_changes(db)
    assert db.query(FeeLineManualPrice).filter_by(fee_line_id=line.id).count() == 0


def test_customer_price_rounding_cap_and_empty_body(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    line = _jewellery(db, kids[2])
    ops = api_for(Role.OPERATIONS)
    url = _url(kids[2], line)
    assert ops.patch(url, json={}).status_code == 422
    assert ops.patch(url, json={"customer_price_cad": None}).status_code == 422
    assert (
        ops.patch(url, json={"manual_unit_price_vnd": "1000", "customer_price_cad": None})
    ).status_code == 422
    rounded = ops.patch(url, json={"customer_price_cad": "0.005"})
    assert rounded.status_code == 200, rounded.text
    assert D(rounded.json()["customer_price_cad"]) == D("0.01")
    top = ops.patch(url, json={"customer_price_cad": "9999999999.99"})
    assert top.status_code == 200, top.text
    with pytest.raises(ValidationError):
        ps.cad_price("10000000000")
    with pytest.raises(ValidationError):
        ps.cad_price("0.001")


def test_both_in_one_request_are_stored_exposed_and_audited(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    ops = api_for(Role.OPERATIONS)
    url = _url(shipment, line)
    saved = ops.patch(url, json={"manual_unit_price_vnd": "450000", "customer_price_cad": "49.99"})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert D(body["manual_unit_price_vnd"]) == D(450000)
    assert D(body["customer_price_cad"]) == D("49.99")
    listed = ops.get(f"/api/v1/shipments/{shipment.id}/fee-lines").json()
    assert D(next(x for x in listed if x["id"] == line.id)["customer_price_cad"]) == D("49.99")

    changed = ops.patch(url, json={"customer_price_cad": "55"})
    assert changed.status_code == 200, changed.text
    see_committed_changes(db)
    prices = [json.loads(a.detail_json) for a in _audits(db, "shipment.fee_line_customer_price")]
    assert [(p["from"], p["to"]) for p in prices] == [(None, "49.99"), ("49.99", "55.00")]
    assert all(p["fee_line_id"] == line.id for p in prices)
    amounts = [json.loads(a.detail_json) for a in _audits(db, "shipment.fee_line_amount")]
    assert [(a["from"], a["to"]) for a in amounts] == [(None, "450000.00")]
    row = db.query(FeeLineManualPrice).filter_by(fee_line_id=line.id).one()
    assert row.customer_price_cad == D("55.00") and row.updated_by_user_id is not None


def test_customer_price_only_on_a_manual_amount_line(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[1]
    other = _fee(db, shipment, "hcm_air", 18, quantity=1)  # a priced rule
    ops = api_for(Role.OPERATIONS)
    refused = ops.patch(_url(shipment, other), json={"customer_price_cad": "10"})
    assert refused.status_code == 422 and refused.json()["field"] == "customer_price_cad"
    # Nor on add.
    item = db.get(ShipmentFeeLine, other.id).item_id
    added = ops.post(
        f"/api/v1/shipments/{shipment.id}/fee-lines",
        json={"item_id": item, "section": "hcm_air", "stt": 13, "customer_price_cad": "10"},
    )
    assert added.status_code == 422, added.text
    see_committed_changes(db)
    assert db.query(FeeLineManualPrice).count() == 0


def test_a_locked_master_refuses_the_customer_price(db, priced_world, api_for):  # noqa: F811
    con, kids = priced_world
    line = _jewellery(db, kids[2])
    cs.book_consolidation(db, con, actor=None)
    db.commit()
    ops = api_for(Role.OPERATIONS)
    locked = ops.patch(_url(kids[2], line), json={"customer_price_cad": "40"})
    assert locked.status_code == 409, locked.text
    assert "locked" in locked.text.lower()
    see_committed_changes(db)
    assert db.query(FeeLineManualPrice).count() == 0


def test_marketing_cannot_enter_a_customer_price(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    line = _jewellery(db, kids[2])
    marketing = api_for(Role.MARKETING)
    assert (
        marketing.patch(_url(kids[2], line), json={"customer_price_cad": "40"}).status_code == 403
    )


def test_add_fee_takes_both_values_and_audits_them(db, priced_world, api_for):  # noqa: F811
    con, kids = priced_world
    shipment = kids[2]
    blank = _jewellery(db, shipment)
    ops = api_for(Role.OPERATIONS)
    added = ops.post(
        f"/api/v1/shipments/{shipment.id}/fee-lines",
        json={
            "item_id": blank.item_id,
            "section": "hcm_air",
            "stt": 27,
            "manual_unit_price_vnd": "300000",
            "customer_price_cad": "25.50",
        },
    )
    # The same item already carries row 27: refused as a duplicate; use a fresh item.
    assert added.status_code == 409, added.text
    ps.remove_fee_line(db, shipment, blank.id, actor=None)
    db.commit()
    added = ops.post(
        f"/api/v1/shipments/{shipment.id}/fee-lines",
        json={
            "item_id": blank.item_id,
            "section": "hcm_air",
            "stt": 27,
            "manual_unit_price_vnd": "300000",
            "customer_price_cad": "25.50",
        },
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert D(body["customer_price_cad"]) == D("25.50")
    see_committed_changes(db)
    detail = json.loads(_audits(db, "shipment.fee_line_add")[-1].detail_json)
    assert (detail["manual_unit_price_vnd"], detail["customer_price_cad"]) == (
        "300000.00",
        "25.50",
    )
    est, _ = ps.estimate_for(db, con)
    assert _issue(est, body["id"]) is None
    fee = next(f for f in est.fees if f.stt == 27)
    assert fee.customer_total_cad == D("25.50")


# --- Review, 2026-10-24: the negative-margin rule applies ----------------------------------------


def test_a_customer_price_below_the_vnd_cost_needs_a_negative_margin_reason(db, priced_world):  # noqa: F811
    from app.pricing import engine as pe

    con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    # 450,000 VND at the buy rate is far above CAD 1.00.
    ps.set_fee_line_amount(db, shipment, line.id, "450000", customer_price_cad="1.00", actor=None)
    db.commit()
    buy = fx_service.latest_snapshot(db).cash_buy_vnd
    assert _cents(D(450000) / buy) > D("1.00")
    est, _ = ps.estimate_for(db, con)
    fee = next(f for f in est.fees if f.section == "hcm_air" and f.stt == 27)
    figures = pe.quote_figures(est, shipment.id, D("10"))
    assert fee.name in figures.negative_margin_fees

    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    with pytest.raises(ConflictError) as caught:
        ps.finalize(db, shipment, negative_margin_reason=None, actor=None)
    problems = caught.value.detail["problems"]
    negative = [p for p in problems if p["code"] == "negative_margin"]
    assert negative and fee.name in negative[0]["message"]
    db.rollback()

    ps.confirm_rate(db, shipment, rate=None, reason=None, actor=None)
    final = ps.finalize(
        db, shipment, negative_margin_reason="Customer agreed a goodwill price", actor=None
    )
    db.commit()
    assert final.status == "finalized"
    assert final.negative_margin_reason == "Customer agreed a goodwill price"
    row27 = next(x for x in final.lines if x.section == "hcm_air" and x.stt == 27)
    assert row27.revenue_cad == D("1.00") and row27.cost_cad > row27.revenue_cad


def test_a_customer_price_above_the_vnd_cost_is_not_a_negative_margin(db, priced_world):  # noqa: F811
    from app.pricing import engine as pe

    con, kids = priced_world
    line = _jewellery(db, kids[2])
    ps.set_fee_line_amount(db, kids[2], line.id, "450000", customer_price_cad="999.00", actor=None)
    db.commit()
    est, _ = ps.estimate_for(db, con)
    fee = next(f for f in est.fees if f.section == "hcm_air" and f.stt == 27)
    assert fee.name not in pe.quote_figures(est, kids[2].id, D("10")).negative_margin_fees
