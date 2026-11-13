"""Phase 14 golden tests (independent tester): the APIs behind the new staff screens.

Black-box over HTTP wherever a screen calls the server; services are used only to build the
world (the sanitized fixture workbook, the demo exchange rate, demo addresses). Air only.

1. ``GET /shipments/{id}/quotes/{version}/document``: customer-safe content only (a deep scan
   of every key and value), totals equal the finalised version's customer figures, drafts
   refused, roles as the route declares (``QuoteReader``: shipment:read + tariff:read +
   financial:read, so Operations and Admin; Marketing and the read-only manager 403), and a
   Customer Account session reaches nothing.
2. Settings -> Pricing: every field the screen edits, PATCHed as the screen sends it, incl.
   the policy kind ``default``.
3. Master milestones: fan-out to every active member, visible on each member's timeline,
   double submit as the API defines it (same type, same or no stated time = duplicate).
4. Complete / cancel rules; item PATCH validation; staff notification preferences with their
   audit; finance invoice due days.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from app.core.enums import Role
from app.models import AuditEvent, QuoteVersion
from app.services import pricing_service as ps
from app.services import shipment_item_service as items
from tests.conftest import see_committed_changes
from tests.test_quote_offers import FORBIDDEN
from tests.test_quotes import priced_world  # noqa: F401 - fixture

#: Words that must not appear anywhere (keys or values) of the printable quote.
DOC_FORBIDDEN = (*FORBIDDEN, "override", "negative_margin", "vnd", "₫")
OVERRIDE_REASON = "SENTINEL-OVERRIDE-REASON"
MARGIN_REASON = "SENTINEL-MARGIN-REASON"


def _url(shipment_id: int, version: int) -> str:
    return f"/api/v1/shipments/{shipment_id}/quotes/{version}/document"


def _finalize_with_override(db, shipment, *, rate="17", fee_qty=1):
    item = items.add_item(db, shipment, {"description": "Watch"}, actor=None)
    ps.add_fee_line(
        db,
        shipment,
        {"item_id": item.id, "section": "hcm_air", "stt": 18, "quantity": fee_qty},
        actor=None,
    )
    ps.reprice(db, shipment, actor=None)
    ps.confirm_rate(db, shipment, rate=rate, reason=OVERRIDE_REASON, actor=None)
    version = ps.finalize(db, shipment, negative_margin_reason=MARGIN_REASON, actor=None)
    db.commit()
    return version


def _walk(node, path=""):
    """Every (path, key-or-value string) in a JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", str(key)
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    elif node is not None:
        yield path, str(node)


# --- 1. The printable quote ----------------------------------------------------------------


def test_document_deep_scan_is_customer_safe(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    version = _finalize_with_override(db, kids[2])
    body = api_for(Role.OPERATIONS).get(_url(kids[2].id, version.version))
    assert body.status_code == 200, body.text
    doc = body.json()
    leaks = []
    for path, text in _walk(doc):
        lowered = text.lower()
        for word in DOC_FORBIDDEN:
            if word in lowered:
                leaks.append((path, word, text))
        if OVERRIDE_REASON.lower() in lowered or MARGIN_REASON.lower() in lowered:
            leaks.append((path, "reason", text))
        # No VND-sized figure (the vendor's prices are in the tens of thousands of VND).
        for number in re.findall(r"\d[\d,.]*", text):
            digits = number.replace(",", "").replace(".", "")
            if path.endswith(("business_number", "company_address", "finalized_at")):
                continue
            if len(digits) >= 7 and not path.endswith("_reference"):
                leaks.append((path, "large figure", text))
    assert leaks == [], leaks
    # The cost-side figures of this version are nowhere in the document.
    raw = body.text
    for figure in (version.allocated_cost_cad, version.gross_profit_cad, version.default_rate_cad):
        if figure is not None and figure != version.selling_rate_cad:
            assert f'"{Decimal(figure):.2f}"' not in raw, figure


def test_document_totals_equal_the_finalised_customer_figures(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    version = _finalize_with_override(db, kids[2], fee_qty=2)
    ops = api_for(Role.OPERATIONS)
    doc = ops.get(_url(kids[2].id, version.version)).json()
    staff = next(
        v
        for v in ops.get(f"/api/v1/shipments/{kids[2].id}/quotes").json()
        if v["version"] == version.version
    )
    assert staff["status"] == "finalized"
    assert Decimal(doc["total_cad"]) == Decimal(staff["total_revenue_cad"])
    assert Decimal(doc["base_charge_cad"]) == Decimal(staff["base_revenue_cad"])
    assert sum((Decimal(s["amount_cad"]) for s in doc["surcharges"]), Decimal(0)) == Decimal(
        staff["surcharge_revenue_cad"]
    )
    assert Decimal(doc["rate_per_kg_cad"]) == Decimal(staff["selling_rate_cad"]) == Decimal("17")
    assert Decimal(doc["billable_weight_kg"]) == Decimal(staff["billable_weight_kg"])
    assert doc["version"] == version.version and doc["shipment_reference"] == kids[2].public_id
    assert doc["currency"] == "CAD" and doc["tax_included"] is False
    assert doc["finalized_at"] is not None

    # The same figures the customer is sent in the 13G offer.
    sent = ops.post(f"/api/v1/shipments/{kids[2].id}/quotes/send", json={})
    assert sent.status_code == 201, sent.text
    view = sent.json()["customer_view"]
    for key in ("service", "billable_weight_kg", "rate_per_kg_cad", "base_charge_cad", "total_cad"):
        assert doc[key] == view[key], key
    assert doc["surcharges"] == view["surcharges"]


def test_document_refuses_drafts_and_keeps_old_finalised_versions(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    v1 = _finalize_with_override(db, kids[1])
    ops = api_for(Role.OPERATIONS)
    # A later change opens a new draft: v2 is not printable, v1 still is and is unchanged.
    first = ops.get(_url(kids[1].id, v1.version)).json()
    item = ops.post(f"/api/v1/shipments/{kids[1].id}/items", json={"description": "Shoes"})
    assert item.status_code == 201
    draft = ops.post(f"/api/v1/shipments/{kids[1].id}/quotes")
    assert draft.status_code == 201, draft.text
    draft_version = draft.json()["version"]
    assert draft.json()["status"] == "draft" and draft_version == v1.version + 1
    refused = ops.get(_url(kids[1].id, draft_version))
    assert refused.status_code == 409, refused.text
    assert "total_cad" not in refused.text
    again = ops.get(_url(kids[1].id, v1.version))
    assert again.status_code == 200 and again.json() == first
    # Wrong or malformed version numbers.
    assert ops.get(_url(kids[1].id, 0)).status_code == 404
    assert ops.get(f"/api/v1/shipments/{kids[1].id}/quotes/abc/document").status_code == 422
    # A version of another shipment is not reachable through this one.
    assert ops.get(_url(kids[0].id, v1.version)).status_code in (404, 409)


def test_document_roles_follow_the_quote_reader_permission(api_for, client, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    version = _finalize_with_override(db, kids[0])
    url = _url(kids[0].id, version.version)
    for role in (Role.OPERATIONS, Role.ADMIN):
        assert api_for(role).get(url).status_code == 200, role
    # Marketing has no tariff:read / financial:read; the read-only manager no tariff:read.
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        response = api_for(role).get(url)
        assert response.status_code == 403, role
        assert "total_cad" not in response.text
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_a_customer_account_session_cannot_reach_the_document(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup
    from tests.test_quote_offers import _account_world, _fee, _finalize

    _reference, me = _setup(account_client, account_users, captured_mail)
    owner = _customer(account_db)
    kids = _account_world(account_db, owner)
    mine = kids[2]
    _fee(account_db, mine)
    version = _finalize(account_db, mine)
    url = _url(mine.id, version.version)
    # Signed in as the customer who owns the shipment: still nothing on the staff route.
    response = account_client.get(url)
    assert response.status_code == 401, response.text
    assert "total_cad" not in response.text
    # And no account-side twin of the route.
    assert me.get(f"/shipments/{mine.id}/quotes/{version.version}/document").status_code in (
        401,
        403,
        404,
        405,
    )


# --- 2. Settings -> Pricing ----------------------------------------------------------------


def test_pricing_settings_every_screen_field(as_admin, db, priced_world):  # noqa: F811
    patch = as_admin.patch
    # The screen sends trimmed strings for rates and numbers for the share.
    response = patch(
        "/api/v1/pricing/settings",
        json={
            "air_standard_default_rate_cad": "19.5",
            "air_express_default_rate_cad": "26",
            "trigger_share_numerator": 1,
            "trigger_share_denominator": 2,
            "default_markup_kind": "fixed_cad",
            "default_markup_value": "1.25",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["air_standard_default_rate_cad"]) == Decimal("19.5")
    assert Decimal(body["air_express_default_rate_cad"]) == Decimal("26")
    assert (body["trigger_share_numerator"], body["trigger_share_denominator"]) == (1, 2)
    assert (body["default_markup_kind"], Decimal(body["default_markup_value"])) == (
        "fixed_cad",
        Decimal("1.25"),
    )
    # The owner-confirmed flag is not on the screen; it survives an edit.
    assert body["defaults_owner_confirmed"] is True
    # An emptied Express rate is sent as null and clears it.
    cleared = patch("/api/v1/pricing/settings", json={"air_express_default_rate_cad": None})
    assert cleared.status_code == 200 and cleared.json()["air_express_default_rate_cad"] is None
    assert Decimal(cleared.json()["air_standard_default_rate_cad"]) == Decimal("19.5")
    # Pass-through without a value (the screen sends none): value becomes 0.
    passed = patch("/api/v1/pricing/settings", json={"default_markup_kind": "pass_through"})
    assert passed.status_code == 200, passed.text
    assert Decimal(passed.json()["default_markup_value"]) == 0
    # Back to percent with a value.
    pct = patch(
        "/api/v1/pricing/settings",
        json={"default_markup_kind": "percent", "default_markup_value": "3.5"},
    )
    assert pct.status_code == 200 and Decimal(pct.json()["default_markup_value"]) == Decimal("3.5")
    # Only the numerator changing is checked against the stored denominator.
    assert patch("/api/v1/pricing/settings", json={"trigger_share_numerator": 3}).status_code == 422
    # Refusals name a field.
    for payload, field in (
        ({"trigger_share_numerator": 3, "trigger_share_denominator": 2}, "trigger_share_numerator"),
        ({"air_standard_default_rate_cad": "0"}, "air_standard_default_rate_cad"),
        ({"air_express_default_rate_cad": "-1"}, "air_express_default_rate_cad"),
        ({"default_markup_value": "101"}, "default_markup_value"),
        ({"default_markup_kind": "default"}, "default_markup_kind"),
    ):
        refused = patch("/api/v1/pricing/settings", json=payload)
        assert refused.status_code == 422, (payload, refused.text)
        assert field in refused.text, (payload, refused.text)
    # Nothing refused changed anything.
    final = as_admin.get("/api/v1/pricing/settings").json()
    assert (final["trigger_share_numerator"], final["trigger_share_denominator"]) == (1, 2)
    see_committed_changes(db)
    actions = [a.action for a in db.query(AuditEvent)]
    assert "pricing.markup_default_update" in actions
    assert any(a.startswith("pricing.settings") for a in actions), actions


def test_surcharge_policy_every_kind_including_default(as_admin, api_for, db, priced_world):  # noqa: F811
    url = "/api/v1/pricing/surcharge-policies/hcm_air/18"
    for kind, value in (("percent", "5"), ("fixed_cad", "3.00"), ("pass_through", "0")):
        response = as_admin.patch(
            url,
            json={
                "markup_kind": kind,
                "markup_value": value,
                "scope_override": "full_carton",
                "note": f"Owner asked {kind}",
            },
        )
        assert response.status_code == 200, (kind, response.text)
        body = response.json()
        assert body["markup_kind"] == kind and Decimal(body["markup_value"]) == Decimal(value)
        assert body["scope_override"] == "full_carton" and body["note"] == f"Owner asked {kind}"
    # "Default" as the screen sends it: value '0', no scope, no note -> inherit, cleared.
    reset = as_admin.patch(
        url,
        json={"markup_kind": "default", "markup_value": "0", "scope_override": None, "note": None},
    )
    assert reset.status_code == 200, reset.text
    body = reset.json()
    assert body["markup_kind"] == "default" and Decimal(body["markup_value"]) == 0
    assert body["scope_override"] is None and body["note"] is None
    listed = {
        (p["section"], p["stt"]): p
        for p in as_admin.get("/api/v1/pricing/surcharge-policies").json()
    }
    assert listed[("hcm_air", 18)]["markup_kind"] == "default"
    # A default with a stray value is still stored as 0.
    stray = as_admin.patch(url, json={"markup_kind": "default", "markup_value": "9"})
    assert stray.status_code == 200 and Decimal(stray.json()["markup_value"]) == 0
    # Refusals: unknown kind, negative value, sea section, tiered rule made master-wide.
    assert as_admin.patch(url, json={"markup_kind": "bonus"}).status_code == 422
    assert (
        as_admin.patch(url, json={"markup_kind": "percent", "markup_value": "-1"}).status_code
        == 422
    )
    assert (
        as_admin.patch("/api/v1/pricing/surcharge-policies/sea_ca_au_uk_eu/1", json={}).status_code
        == 422
    )
    master_wide = as_admin.patch(
        "/api/v1/pricing/surcharge-policies/hcm_air/27", json={"scope_override": "full_master"}
    )
    assert master_wide.status_code == 422 and "scope_override" in master_wide.text
    assert (
        as_admin.patch("/api/v1/pricing/surcharge-policies/hcm_air/999", json={}).status_code == 404
    )
    # Operations reads, never writes.
    ops = api_for(Role.OPERATIONS)
    assert ops.get("/api/v1/pricing/surcharge-policies").status_code == 200
    assert ops.patch(url, json={"markup_kind": "percent", "markup_value": "1"}).status_code == 403


# --- 3. Master milestones ------------------------------------------------------------------


def _timeline(api, shipment_id):
    response = api.get(f"/api/v1/shipments/{shipment_id}/events")
    assert response.status_code == 200, response.text
    return response.json()


def test_master_event_fans_out_to_every_member_timeline(api_for, db, priced_world):  # noqa: F811
    con, kids = priced_world
    ops = api_for(Role.OPERATIONS)
    response = ops.post(
        f"/api/v1/consolidations/{con.id}/events",
        json={
            "event_type": "departed_origin",
            "location_label": "SGN",
            "is_public_update": True,
            "public_update_text": "Your parcel left Vietnam.",
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert sorted(result["applied"]) == sorted(k.public_id for k in kids)
    assert result["duplicates"] == [] and result["refused"] == []
    for shipment in kids:
        events = [e for e in _timeline(ops, shipment.id) if e["event_type"] == "departed_origin"]
        assert len(events) == 1, shipment.public_id
        assert events[0]["location_label"] == "SGN"
        assert events[0]["is_public_update"] is True
        assert events[0]["public_update_text"] == "Your parcel left Vietnam."
    see_committed_changes(db)
    audit = db.query(AuditEvent).filter_by(action="consolidation.event_record").all()
    assert len(audit) == 1


def test_master_event_double_submit_without_a_time_is_one_event(api_for, db, priced_world):  # noqa: F811
    con, kids = priced_world
    ops = api_for(Role.OPERATIONS)
    url = f"/api/v1/consolidations/{con.id}/events"
    first = ops.post(url, json={"event_type": "in_transit"})
    second = ops.post(url, json={"event_type": "in_transit"})
    assert first.status_code == 201 and second.status_code == 201, second.text
    assert second.json()["applied"] == []
    assert sorted(second.json()["duplicates"]) == sorted(k.public_id for k in kids)
    for shipment in kids:
        count = sum(1 for e in _timeline(ops, shipment.id) if e["event_type"] == "in_transit")
        assert count == 1, shipment.public_id


def test_master_event_double_submit_with_the_screens_utc_time_is_one_event(
    api_for,
    db,
    priced_world,  # noqa: F811
):
    """The screen sends ``new Date(local).toISOString()``: ``...T10:00:00.000Z``."""
    con, kids = priced_world
    ops = api_for(Role.OPERATIONS)
    url = f"/api/v1/consolidations/{con.id}/events"
    payload = {"event_type": "arrived_destination", "occurred_at": "2026-10-19T10:00:00.000Z"}
    first = ops.post(url, json=payload)
    assert first.status_code == 201 and len(first.json()["applied"]) == 3, first.text
    second = ops.post(url, json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["applied"] == [], second.json()
    assert len(second.json()["duplicates"]) == 3
    # The same instant written with an offset is the same milestone.
    third = ops.post(url, json={**payload, "occurred_at": "2026-10-19T17:00:00+07:00"})
    assert third.json()["applied"] == [], third.json()
    # A different stated time is a different milestone (as the API defines it).
    fourth = ops.post(url, json={**payload, "occurred_at": "2026-10-20T10:00:00.000Z"})
    assert len(fourth.json()["applied"]) == 3
    for shipment in kids:
        count = sum(
            1 for e in _timeline(ops, shipment.id) if e["event_type"] == "arrived_destination"
        )
        assert count == 2, shipment.public_id


def test_master_event_payload_rules(api_for, db, priced_world):  # noqa: F811
    con, kids = priced_world
    ops = api_for(Role.OPERATIONS)
    url = f"/api/v1/consolidations/{con.id}/events"
    assert ops.post(url, json={"event_type": "teleported"}).status_code == 422
    assert ops.post(url, json={"event_type": "in_transit", "package_id": 1}).status_code == 422
    assert ops.post(url, json={}).status_code == 422
    # Template and own wording together: never written on any member.
    both = ops.post(
        url,
        json={
            "event_type": "in_transit",
            "is_public_update": True,
            "public_update_text": "Hello",
            "public_update_template_key": "in_transit_default",
        },
    )
    assert both.status_code in (201, 422), both.text
    if both.status_code == 201:
        assert both.json()["applied"] == []
    for shipment in kids:
        assert not [e for e in _timeline(ops, shipment.id) if e["event_type"] == "in_transit"]
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).post(url, json={"event_type": "in_transit"}).status_code == 403


# --- 4. Complete / cancel ------------------------------------------------------------------


def test_complete_and_cancel_rules(api_for, db, priced_world):  # noqa: F811
    con, kids = priced_world
    ops = api_for(Role.OPERATIONS)
    base = f"/api/v1/consolidations/{con.id}"
    # Open: cannot complete.
    assert ops.post(f"{base}/complete").status_code == 409
    booked = ops.post(f"{base}/book")
    assert booked.status_code == 200, booked.text
    # A reason is required, whitespace is not a reason, unknown fields are refused.
    assert ops.post(f"{base}/cancel", json={}).status_code == 422
    assert ops.post(f"{base}/cancel", json={"reason": "   "}).status_code == 422
    assert ops.post(f"{base}/cancel", json={"reason": "x", "force": True}).status_code == 422
    assert ops.post(f"{base}/cancel", json={"reason": "x" * 256}).status_code == 422
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).post(f"{base}/cancel", json={"reason": "x"}).status_code == 403
        assert api_for(role).post(f"{base}/complete").status_code == 403
    ops = api_for(Role.OPERATIONS)
    cancelled = ops.post(f"{base}/cancel", json={"reason": "  Vendor   flight cancelled "})
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["state"] == "cancelled" and body["member_count"] == 0 and body["members"] == []
    assert body["cancellation_reason"] == "Vendor flight cancelled"
    # Members are released, their bookings untouched.
    for shipment in kids:
        page = ops.get(f"/api/v1/shipments/{shipment.id}").json()
        assert page["consolidation"] is None
        assert page["booking_state"] == "confirmed"
    # Terminal.
    assert ops.post(f"{base}/cancel", json={"reason": "again"}).status_code == 409
    assert ops.post(f"{base}/complete").status_code == 409
    assert ops.post(f"{base}/events", json={"event_type": "in_transit"}).status_code == 409


def test_complete_a_booked_master_then_it_is_closed(api_for, db, priced_world):  # noqa: F811
    con, _kids = priced_world
    ops = api_for(Role.OPERATIONS)
    base = f"/api/v1/consolidations/{con.id}"
    assert ops.post(f"{base}/book").status_code == 200
    done = ops.post(f"{base}/complete")
    assert done.status_code == 200 and done.json()["state"] == "completed"
    assert done.json()["completed_at"] is not None
    assert ops.post(f"{base}/complete").status_code == 409
    assert ops.post(f"{base}/cancel", json={"reason": "late"}).status_code == 409
    assert ops.post(f"{base}/events", json={"event_type": "in_transit"}).status_code == 409


# --- 5. Item PATCH ------------------------------------------------------------------------


def test_item_patch_validation(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    ops = api_for(Role.OPERATIONS)
    sid = kids[0].id
    item = ops.post(
        f"/api/v1/shipments/{sid}/items",
        json={"description": "Watch", "weight_kg": "0.4", "notes": "fragile"},
    ).json()
    url = f"/api/v1/shipments/{sid}/items/{item['id']}"
    # The screen's fields, changed only.
    ok = ops.patch(
        url, json={"description": " Wrist   watch ", "quantity": "2", "unit": "Box", "notes": ""}
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["description"] == "Wrist watch" and Decimal(body["quantity"]) == 2
    assert body["unit"] == "box" and body["notes"] is None
    assert Decimal(body["weight_kg"]) == Decimal("0.4")
    # An emptied weight is cleared.
    cleared = ops.patch(url, json={"weight_kg": None})
    assert cleared.status_code == 200 and cleared.json()["weight_kg"] is None
    for payload in (
        {"description": ""},
        {"description": "   "},
        {"quantity": "0"},
        {"quantity": "-1"},
        {"weight_kg": "0"},
        {"unit": "barrel"},
        {"notes": "x" * 401},
        {"colour": "red"},
        {"quantity": "abc"},
    ):
        refused = ops.patch(url, json=payload)
        assert refused.status_code == 422, (payload, refused.text)
    # Another shipment's item, an unknown item.
    assert (
        ops.patch(
            f"/api/v1/shipments/{kids[1].id}/items/{item['id']}", json={"unit": "box"}
        ).status_code
        == 404
    )
    assert (
        ops.patch(f"/api/v1/shipments/{sid}/items/999999", json={"unit": "box"}).status_code == 404
    )
    # A removed item.
    assert ops.post(f"{url}/remove").status_code == 200
    assert ops.patch(url, json={"description": "Back"}).status_code == 409
    # Roles without shipment:write.
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).patch(url, json={"description": "x"}).status_code == 403
    see_committed_changes(db)
    updates = db.query(AuditEvent).filter_by(action="shipment.item_update").all()
    assert len(updates) == 2
    assert sorted(json.loads(updates[0].detail_json)["fields"]) == sorted(
        ["description", "quantity", "unit", "notes"]
    )


# --- 6. Staff notification preferences -----------------------------------------------------


def test_staff_notification_preferences_and_audit(api_for, db, priced_world, users):  # noqa: F811
    _con, kids = priced_world
    cid = kids[0].customer_id
    url = f"/api/v1/customers/{cid}/notification-preferences"
    ops = api_for(Role.OPERATIONS)
    start = ops.get(url)
    assert start.status_code == 200
    assert set(start.json()["preferences"]) == {
        "received",
        "in_transit",
        "out_for_delivery",
        "delivered",
    }
    saved = ops.patch(url, json={"preferences": {"in_transit": False, "delivered": True}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["preferences"]["in_transit"] is False
    assert ops.get(url).json()["preferences"]["in_transit"] is False
    for payload in (
        {"preferences": {}},
        {"preferences": {"teleported": True}},
        {"preferences": {"in_transit": "yes"}},
        {"preferences": {"in_transit": 1}},
        {"in_transit": False},
    ):
        assert ops.patch(url, json=payload).status_code == 422, payload
    # Marketing and the read-only manager read (customer:read) but cannot change.
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        client = api_for(role)
        assert client.get(url).status_code == 200, role
        assert client.patch(url, json={"preferences": {"received": False}}).status_code == 403
    assert (
        api_for(Role.OPERATIONS)
        .get("/api/v1/customers/999999/notification-preferences")
        .status_code
        == 404
    )
    see_committed_changes(db)
    audit = db.query(AuditEvent).filter_by(action="notification.preferences_update").all()
    assert len(audit) == 1
    detail = json.loads(audit[0].detail_json)
    assert detail["via"] == "staff"
    assert detail["choices"] == {"delivered": True, "in_transit": False}
    assert audit[0].actor_user_id == users[Role.OPERATIONS].id
    assert audit[0].entity_id == str(cid)


# --- 7. Finance invoice due days -----------------------------------------------------------


def test_finance_due_days_validation(as_admin, api_for, db):
    url = "/api/v1/finance/settings"
    assert as_admin.get(url).status_code == 200
    for days in (0, 365, 30):
        response = as_admin.patch(url, json={"invoice_due_days": days})
        assert response.status_code == 200, response.text
        assert response.json()["invoice_due_days"] == days
    for payload in (
        {"invoice_due_days": -1},
        {"invoice_due_days": 366},
        {"invoice_due_days": "abc"},
        {"invoice_due_days": 1.5},
        {"tax_status": "registered"},
    ):
        assert as_admin.patch(url, json=payload).status_code == 422, payload
    assert as_admin.get(url).json()["invoice_due_days"] == 30
    ops = api_for(Role.OPERATIONS)
    assert ops.get(url).status_code == 200
    assert ops.patch(url, json={"invoice_due_days": 10}).status_code == 403
    assert api_for(Role.MARKETING).get(url).status_code == 403
    see_committed_changes(db)
    audit = db.query(AuditEvent).filter_by(action="finance.settings_update").all()
    # Phase 14 review fix 10: a PATCH that changes nothing (0 is the unsaved default) writes no
    # audit entry, so only the two real changes are recorded.
    assert [json.loads(a.detail_json)["invoice_due_days"] for a in audit] == [365, 30]


def test_quote_versions_are_untouched_by_reading_the_document(api_for, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    version = _finalize_with_override(db, kids[2])
    before = (version.total_revenue_cad, version.finalized_at)
    ops = api_for(Role.OPERATIONS)
    for _ in range(2):
        assert ops.get(_url(kids[2].id, version.version)).status_code == 200
    see_committed_changes(db)
    row = db.get(QuoteVersion, version.id)
    assert (row.total_revenue_cad, row.finalized_at) == before
    assert db.query(QuoteVersion).filter_by(shipment_id=kids[2].id).count() == 1
