"""Owner answers of 22 October 2026 (Louis Tong, on Ben's behalf): RC-UAT-19.

1. **GST/HST on the draft invoice** (DEC-0223): a new draft starts at 13 %, included in the
   price (backed out of the all-in lines); staff change the rate and the mode; Save and Send
   need the tax confirmed for the saved revision (422 ``tax_unconfirmed``); Send issues the
   invoice with the mode's subtotal, tax and total; the documents say "Prices include
   GST/HST 13 %"; an old draft without a tax row reads as tax added, unconfirmed.
2. **Tracking links** (DEC-0224): a last-mile carrier link stays visible to the customer
   under a generic name even when its stored label names the vendor; a link whose host names
   the vendor stays hidden.
3. **Generic leg names** (DEC-0224): "Master Tracking" / "Last Mile Tracking" ("Theo dõi
   chặng chính" / "Theo dõi chặng cuối", proposed) wherever a customer reads a tracking name.
4. **Costume jewellery** (HCM air row 27, DEC-0225): a manual amount per line, no kilograms,
   no master-wide share; a line without an amount blocks finalising.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.core.config import settings as app_settings
from app.core.enums import Role, SurchargeSection, TrackingSourceMode
from app.models import (
    AuditEvent,
    Customer,
    CustomerInvoice,
    InvoiceDraftTax,
    LegTrackingReference,
    ShipmentFeeLine,
    ShipmentLeg,
)
from app.pricing.kango_semantics import CURATED_RULES
from app.pricing.kango_workbook import parse_workbook
from app.services import finance_service as fs
from app.services import invoice_draft_service as drafts
from app.services import invoice_pdf_service as pdfs
from app.services import pricing_service as ps
from app.services import public_tracking_service as pts
from app.services import tariff_import_service as tis
from app.services.errors import ConflictError, ValidationError
from tests.conftest import see_committed_changes, shown_tax
from tests.test_fixpack_f_lock_expiry_drafts import _accepted
from tests.test_quotes import WORKBOOK, _fee, priced_world  # noqa: F401 - fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
D = Decimal


def _audits(db, action):
    return db.query(AuditEvent).filter_by(action=action).order_by(AuditEvent.id).all()


def _ontario(db, shipment):
    """RC-UAT-20 (owner, 2026-10-23; DEC-0227): a draft's GST/HST follows the route, and 13 %
    included is the rate of a domestic shipment delivered in Ontario. The tests below pin the
    included mechanics of DEC-0223 on such a shipment (an international one is 0 %)."""
    shipment.origin_country_code = "CA"
    shipment.destination_country_code = "CA"
    shipment.recipient_country_code = "CA"
    shipment.recipient_province_state = "ON"
    db.commit()
    return shipment


def _pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF")
    return "".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


# === 1. GST/HST on the draft invoice =============================================================


@pytest.mark.parametrize(
    ("total", "rate", "subtotal", "tax", "whole_total_tax"),
    [
        ("113.00", 13, "100.00", "13.00", "13.00"),
        # DEC-0235 (per line): net 88.50 + tax 11.51 is a cent over, so the net is nudged; the
        # whole-total rule of DEC-0223 read 11.504... -> 11.50.
        ("100.00", 13, "88.49", "11.51", "11.50"),
        ("10.00", 13, "8.85", "1.15", "1.15"),  # 1.1504... -> 1.15
        ("0.05", 13, "0.04", "0.01", "0.01"),  # 0.00575 -> 0.01 (up)
        # DEC-0235: net 0.04 -> tax 0.01, nudged to 0.03 (DEC-0223: 0.0046 -> 0.00).
        ("0.04", 13, "0.03", "0.01", "0.00"),
        ("1234.56", 13, "1092.53", "142.03", "142.03"),  # 142.0291... -> 142.03
        ("10.00", 5, "9.52", "0.48", "0.48"),  # 0.4761... -> 0.48
        ("105.00", 5, "100.00", "5.00", "5.00"),
        ("250.00", 0, "250.00", "0.00", "0.00"),
    ],
)
def test_included_tax_is_backed_out_of_the_all_in_total(
    total, rate, subtotal, tax, whole_total_tax
):
    """One all-in line, backed out by the per-line rule of DEC-0235; ``included_tax_of`` keeps
    the whole-total rule of DEC-0223 (what an invoice issued before holds)."""
    got = drafts.totals(D(total), rate, "included")
    assert got == (D(subtotal), D(tax), D(total))
    assert got[0] + got[1] == D(total)  # the parts always add up to what the customer pays
    assert drafts.included_tax_of(D(total), rate) == D(whole_total_tax)


def test_added_tax_is_charged_on_top_as_before():
    assert drafts.totals(D("100.00"), 13, "added") == (D("100.00"), D("13.00"), D("113.00"))
    assert drafts.totals(D("10.01"), 5, "added") == (D("10.01"), D("0.50"), D("10.51"))


def test_a_new_draft_to_ontario_starts_at_13_percent_included_and_unconfirmed(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, _ontario(db, kids[2]))
    assert draft.tax_rate_percent == 13
    row = db.query(InvoiceDraftTax).filter_by(draft_id=draft.id).one()
    assert (row.mode, row.rate_percent, row.confirmed_revision) == ("included", 13, None)
    view = drafts.view(db, draft)
    lines_total = drafts.subtotal_of(drafts.lines_of(draft))
    assert view["tax_mode"] == "included" and view["tax_confirmed"] is False
    assert D(view["total_cad"]) == lines_total == D(view["quote_total_cad"])
    # DEC-0235: backed out line by line.
    assert D(view["tax_cad"]) == drafts.totals(drafts.lines_of(draft), 13, "included")[1]
    assert D(view["subtotal_cad"]) + D(view["tax_cad"]) == D(view["total_cad"])
    assert view["lines_total_cad"] == str(lines_total)
    created = json.loads(_audits(db, "invoice.draft_created")[-1].detail_json)
    assert (created["tax_rate_percent"], created["tax_mode"]) == (13, "included")


def test_save_needs_the_tax_confirmed_and_records_it_for_the_new_revision(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    _offer, draft = _accepted(db, _ontario(db, kids[2]))
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)

    refused = ops.patch(url, json={"expected_revision": 1, "notes": "Thanks"})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "tax_unconfirmed"
    assert refused.json()["field"] == "tax_confirmed"
    unticked = ops.patch(url, json={"expected_revision": 1, "notes": "x", "tax_confirmed": False})
    assert unticked.status_code == 422
    assert ops.get(url).json()["revision"] == 1

    # Confirming an unchanged draft records the confirmation without a new revision.
    confirmed = ops.patch(url, json={"expected_revision": 1, "tax_confirmed": True})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["revision"] == 1 and body["tax_confirmed"] is True
    assert body["tax_confirmed_by"] == "operations@demo.example.com"

    saved = ops.patch(url, json={"expected_revision": 1, "notes": "Thanks", "tax_confirmed": True})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2 and saved.json()["tax_confirmed"] is True
    see_committed_changes(db)
    audits = _audits(db, "invoice.draft_tax_confirmed")
    assert [json.loads(a.detail_json)["revision"] for a in audits] == [1, 2]
    detail = json.loads(audits[-1].detail_json)
    assert (detail["tax_mode"], detail["tax_rate_percent"]) == ("included", 13)
    edit = json.loads(_audits(db, "invoice.draft_edited")[-1].detail_json)
    assert edit["tax"] == {"mode": "included", "rate_percent": 13}


def test_a_change_of_rate_mode_or_line_needs_a_fresh_confirmation(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    """The confirmation of revision N never covers revision N+1: a save that changes the rate,
    the mode or a line is refused unless it carries the tick again, and a revision moved on by
    anything else is unconfirmed until confirmed."""
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[2])
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    assert ops.patch(url, json={"expected_revision": 1, "tax_confirmed": True}).status_code == 200
    lines = ops.get(url).json()["lines"]
    lines[0]["description"] = "Air freight"
    for change in ({"tax_rate_percent": 5}, {"tax_mode": "added"}, {"lines": lines}):
        refused = ops.patch(url, json={"expected_revision": 1, **change})
        assert refused.status_code == 422, (change, refused.text)
        assert refused.json()["detail"]["code"] == "tax_unconfirmed"
    assert ops.get(url).json()["tax_confirmed"] is True  # nothing was saved

    # A revision moved on without a confirming save (simulated) is unconfirmed: Send refuses.
    see_committed_changes(db)
    draft = drafts.get(db, draft.id)
    draft.revision += 1
    db.commit()
    assert drafts.view(db, draft)["tax_confirmed"] is False
    with pytest.raises(ValidationError) as caught:
        drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    assert caught.value.detail["code"] == "tax_unconfirmed"
    db.rollback()


def test_send_is_refused_until_the_saved_revision_is_confirmed(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[2])
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    refused = ops.post(f"{url}/send", json={"expected_revision": 1})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "tax_unconfirmed"
    see_committed_changes(db)
    assert db.query(CustomerInvoice).count() == 0
    assert ops.patch(url, json={"expected_revision": 1, "tax_confirmed": True}).status_code == 200
    sent = ops.post(f"{url}/send", json={"expected_revision": 1})
    assert sent.status_code == 200, sent.text


def test_send_included_issues_the_backed_out_figures_and_the_documents_say_so(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    english = db.get(Customer, kids[0].customer_id)
    english.preferred_language = "en"
    db.commit()
    _offer, draft = _accepted(db, _ontario(db, kids[0]))
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    view = ops.patch(url, json={"expected_revision": 1, "tax_confirmed": True}).json()

    draft_pdf = _pdf_text(ops.get(f"{url}/pdf", params={"revision": 1}).content)
    # DEC-0235: the Solaris Invoicing layout -- each line "HST ON", the row "HST ON @ 13%", no
    # "Prices include" sentence (the lines print before tax).
    assert "HST ON @ 13%" in draft_pdf and "HST ON" in draft_pdf
    assert "Prices include" not in draft_pdf and "Subtotal before GST/HST" not in draft_pdf

    sent = ops.post(f"{url}/send", json={"expected_revision": 1})
    assert sent.status_code == 200, sent.text
    see_committed_changes(db)
    invoice = db.get(CustomerInvoice, sent.json()["invoice_id"])
    # DEC-0235: each line stores its net; the invoice is the per-line figures the screen showed.
    nets = sum((line.amount_cad for line in invoice.lines), D(0))
    lines_total = drafts.subtotal_of(drafts.lines_of(draft))
    assert invoice.total_cad == lines_total == D(view["total_cad"])
    assert invoice.tax_cad == drafts.totals(drafts.lines_of(draft), 13, "included")[1]
    assert invoice.tax_cad == D(view["tax_cad"])
    assert invoice.subtotal_cad == nets == lines_total - invoice.tax_cad == D(view["subtotal_cad"])
    assert invoice.tax_status == "gst_hst_13"
    sent_audit = json.loads(_audits(db, "invoice.draft_sent")[-1].detail_json)
    assert (sent_audit["tax_mode"], sent_audit["tax_rate_percent"]) == ("included", 13)

    document = ops.get(f"/api/v1/invoices/{invoice.id}/document").json()
    assert document["tax_mode"] == "included"
    # DEC-0235: no "Prices include" sentence on the new layout; the summary row's label.
    assert document["tax_included_note"] is None
    assert (document["tax_label"], document["tax_line_label"]) == ("HST", "HST ON @ 13%")
    issued_pdf = _pdf_text(ops.get(f"/api/v1/invoices/{invoice.id}/pdf").content)
    assert "HST ON @ 13%" in issued_pdf and "Prices include" not in issued_pdf

    # Profitability keeps using the subtotal: the tax is not revenue.
    report = fs.profitability(db, invoice.period_month)
    assert report["summary"]["revenue_cad"] == invoice.subtotal_cad


def test_a_vietnamese_customer_reads_the_invoice_in_english_without_the_note(db, priced_world):  # noqa: F811
    """DEC-0235: the invoice and its PDF are in English for every customer, with no "Prices
    include" sentence (it read "Giá đã bao gồm HST 13 %" for a Vietnamese customer)."""
    _con, kids = priced_world
    _offer, draft = _accepted(db, _ontario(db, kids[2]))
    drafts.update_draft(db, draft, {"tax_confirmed": True}, expected_revision=1, actor=None)
    db.commit()
    text = _pdf_text(pdfs.draft_pdf(db, draft))
    assert "HST ON @ 13%" in text and "bao gồm" not in text and "Prices include" not in text
    invoice = drafts.send(db, draft, expected_revision=1, actor=None)
    db.commit()
    assert fs.invoice_document(db, invoice)["tax_included_note"] is None


def test_switching_to_added_on_top_is_diffed_and_sent_as_before(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    _offer, draft = _accepted(db, _ontario(db, kids[1]))
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    saved = ops.patch(
        url,
        json={
            "expected_revision": 1,
            "tax_mode": "added",
            "tax_rate_percent": 5,
            "tax_confirmed": True,
            **shown_tax(drafts.lines_of(draft), 5, "added"),
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    lines_total = D(body["lines_total_cad"])
    assert body["tax_mode"] == "added" and body["revision"] == 2
    assert D(body["subtotal_cad"]) == lines_total
    assert D(body["tax_cad"]) == drafts.tax_of(lines_total, 5)
    assert D(body["total_cad"]) == lines_total + D(body["tax_cad"])
    see_committed_changes(db)
    changes = json.loads(_audits(db, "invoice.draft_edited")[-1].detail_json)["changes"]
    assert changes["tax_mode"] == {"from": "included", "to": "added"}
    assert changes["tax_rate_percent"] == {"from": 13, "to": 5}
    assert db.query(InvoiceDraftTax).filter_by(draft_id=draft.id).one().rate_percent == 5

    sent = ops.post(f"{url}/send", json={"expected_revision": 2})
    assert sent.status_code == 200, sent.text
    see_committed_changes(db)
    invoice = db.get(CustomerInvoice, sent.json()["invoice_id"])
    assert (invoice.subtotal_cad, invoice.tax_cad) == (lines_total, drafts.tax_of(lines_total, 5))
    assert invoice.total_cad == invoice.subtotal_cad + invoice.tax_cad
    document = ops.get(f"/api/v1/invoices/{invoice.id}/document").json()
    assert document["tax_mode"] == "added" and document["tax_included_note"] is None
    text = _pdf_text(ops.get(f"/api/v1/invoices/{invoice.id}/pdf").content)
    assert "include GST/HST" not in text and "bao gồm GST/HST" not in text


def test_an_old_draft_without_a_tax_row_reads_as_added_and_unconfirmed(db, priced_world):  # noqa: F811
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[2])
    db.query(InvoiceDraftTax).filter_by(draft_id=draft.id).delete()
    draft.tax_rate_percent = 5  # as saved before the owner's answer
    db.commit()
    view = drafts.view(db, draft)
    lines_total = drafts.subtotal_of(drafts.lines_of(draft))
    assert (view["tax_mode"], view["tax_rate_percent"], view["tax_confirmed"]) == (
        "added",
        5,
        False,
    )
    assert D(view["total_cad"]) == lines_total + drafts.tax_of(lines_total, 5)
    with pytest.raises(ValidationError, match="GST/HST"):
        drafts.send(db, draft, expected_revision=draft.revision, actor=None)
    db.rollback()
    drafts.update_draft(db, draft, {"tax_confirmed": True}, expected_revision=1, actor=None)
    db.commit()
    row = db.query(InvoiceDraftTax).filter_by(draft_id=draft.id).one()
    assert (row.mode, row.rate_percent, row.confirmed_revision) == ("added", 5, 1)
    invoice = drafts.send(db, draft, expected_revision=1, actor=None)
    db.commit()
    assert invoice.total_cad == lines_total + drafts.tax_of(lines_total, 5)


def test_the_manual_issue_path_is_unchanged(db, priced_world):  # noqa: F811
    from tests.test_quote_offers import _finalize

    _con, kids = priced_world
    version = _finalize(db, kids[1])
    invoice = fs.issue_invoice(db, kids[1], actor=None, tax_rate_percent=13)
    db.commit()
    revenue = sum((line.revenue_cad for line in version.lines if line.revenue_cad), D(0))
    assert invoice.subtotal_cad == revenue
    assert invoice.total_cad == revenue + drafts.tax_of(revenue, 13)
    assert fs.invoice_document(db, invoice)["tax_mode"] == "added"


def test_the_migration_adds_only_the_tax_table_and_round_trips(tmp_path):
    import sqlite3

    from tests.test_migrations_phase13c import _alembic, _tables

    path = tmp_path / "m.db"
    url = f"sqlite:///{path.as_posix()}"
    assert _alembic(url, "upgrade", "d4f7a2c9e1b8").returncode == 0
    before = _tables(path)
    with sqlite3.connect(path) as c:
        schema_before = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
    # RC-UAT-20's f7c2d9e3a1b5 revises this one, so upgrade to it by name.
    assert _alembic(url, "upgrade", "e6b1c4a8d2f3").returncode == 0
    assert "e6b1c4a8d2f3" in _alembic(url, "current").stdout
    assert _tables(path) - before == {"invoice_draft_tax"}
    with sqlite3.connect(path) as c:
        schema_after = dict(c.execute("select name, sql from sqlite_master where sql is not null"))
        fks = {r[3]: (r[2], r[6]) for r in c.execute("pragma foreign_key_list(invoice_draft_tax)")}
    for name, sql in schema_before.items():
        assert schema_after[name] == sql, name  # nothing existing altered
    assert fks["draft_id"] == ("invoice_drafts", "CASCADE")
    assert fks["confirmed_by_user_id"] == ("users", "SET NULL")
    assert _alembic(url, "upgrade", "head").returncode == 0
    check = _alembic(url, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert _alembic(url, "downgrade", "d4f7a2c9e1b8").returncode == 0
    assert "invoice_draft_tax" not in _tables(path)


# === 2 and 3. Tracking links and generic leg names ===============================================


def _link(db, shipment, *, leg_type, label, url, sequence=1):
    leg = ShipmentLeg(shipment_id=shipment.id, sequence=sequence, leg_type=leg_type)
    leg.provider_name = label
    db.add(leg)
    db.flush()
    db.add(
        LegTrackingReference(
            leg_id=leg.id,
            carrier_name=label,
            tracking_number=f"TN-{sequence}-0001",
            public_url=url,
            source_mode=TrackingSourceMode.EXTERNAL_LINK,
            is_active=True,
        )
    )
    db.commit()


UPS = "https://www.ups.com/track?loc=en_CA&tracknum=1Z999AA10123456784"
DHL = "https://www.dhl.com/ca-en/home/tracking.html?tracking-id=1234567890"


def test_leg_types_map_to_the_two_generic_names():
    assert pts.tracking_name_key("origin_pickup") == "master_tracking"
    assert pts.tracking_name_key("consolidation_linehaul") == "master_tracking"
    for leg_type in ("destination_handling", "final_delivery", "last_mile", None):
        assert pts.tracking_name_key(leg_type) == "last_mile_tracking"
    assert pts.TRACKING_NAMES == {
        "master_tracking": {"en": "Master Tracking", "vi": "Theo dõi chặng chính"},
        "last_mile_tracking": {"en": "Last Mile Tracking", "vi": "Theo dõi chặng cuối"},
    }


def test_both_screens_carry_the_generic_names_in_both_languages():
    """The public page and the Customer Account render the name from the key, vi and en."""
    files = {
        "frontend/src/public/locales/en.js": ("Master Tracking", "Last Mile Tracking"),
        "frontend/src/public/locales/vi.js": ("Theo dõi chặng chính", "Theo dõi chặng cuối"),
        "frontend/src/account/i18n/en.js": ("Master Tracking", "Last Mile Tracking"),
        "frontend/src/account/i18n/vi.js": ("Theo dõi chặng chính", "Theo dõi chặng cuối"),
    }
    for path, names in files.items():
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        for name in names:
            assert name in text, (path, name)


def test_public_a_carrier_link_labelled_with_the_vendor_shows_under_a_generic_name(
    client,
    db,
    priced_world,  # noqa: F811
):
    _con, kids = priced_world
    shipment = kids[2]
    _link(db, shipment, leg_type="final_delivery", label="Kango Express UPS", url=UPS)
    body = client.get(f"/api/v1/public/track/{shipment.public_id}").json()
    link = body["carrier_link"]
    assert link == {
        "carrier_name": "Last Mile Tracking",
        "tracking_name_key": "last_mile_tracking",
        "url": UPS,
    }
    assert "kango" not in json.dumps(body, ensure_ascii=False).lower()
    assert "TN-1-0001" not in json.dumps(body)


def test_public_a_master_leg_link_reads_master_tracking(client, db, priced_world):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[1]
    _link(db, shipment, leg_type="consolidation_linehaul", label="Kango air master", url=DHL)
    link = client.get(f"/api/v1/public/track/{shipment.public_id}").json()["carrier_link"]
    assert (link["carrier_name"], link["tracking_name_key"]) == (
        "Master Tracking",
        "master_tracking",
    )


def test_a_link_whose_host_names_the_vendor_stays_hidden(
    client,
    db,
    priced_world,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(
        app_settings, "public_carrier_link_hosts", "track.kango.vn,www.ups.com,www.dhl.com"
    )
    _con, kids = priced_world
    shipment = kids[0]
    _link(db, shipment, leg_type="final_delivery", label="UPS", url="https://track.kango.vn/x?id=1")
    url = f"/api/v1/public/track/{shipment.public_id}"
    assert client.get(url).json()["carrier_link"] is None
    # The next safe link is shown instead.
    _link(db, shipment, leg_type="final_delivery", label="UPS", url=UPS, sequence=2)
    link = client.get(url).json()["carrier_link"]
    assert link["url"] == UPS and link["carrier_name"] == "Last Mile Tracking"


def test_account_carrier_link_is_generic_and_names_no_vendor(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup
    from tests.test_quote_offers import _account_world

    _reference, me = _setup(account_client, account_users, captured_mail)
    owner = _customer(account_db)
    kids = _account_world(account_db, owner)
    mine = kids[2]
    _link(account_db, mine, leg_type="final_delivery", label="Kango Logistics last mile", url=UPS)
    response = me.get(f"/shipments/{mine.public_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["carrier_link"] == {
        "carrier_name": "Last Mile Tracking",
        "tracking_name_key": "last_mile_tracking",
        "url": UPS,
    }
    assert "kango" not in response.text.lower()
    # Staff screens are unchanged: the stored label is still the staff's.
    see_committed_changes(account_db)
    stored = account_db.query(LegTrackingReference).one()
    assert stored.carrier_name == "Kango Logistics last mile"


# === 4. Costume jewellery: a manual amount per line ==============================================


def test_row_27_is_a_manual_amount_with_no_kilograms_and_no_prefill():
    sem = CURATED_RULES[(SurchargeSection.HCM_AIR, 27)]
    assert (sem.pricing_status, sem.basis, sem.scope) == (
        "manual_quote",
        "manual_amount",
        "per_unit",
    )
    assert sem.unit_price_vnd is None and "DEC-0225" in sem.note
    row = next(
        r
        for r in parse_workbook(WORKBOOK.read_bytes()).surcharge_rows
        if r.section == SurchargeSection.HCM_AIR and r.stt == 27
    )
    resolved = tis.resolve_rule(row, [])
    assert (resolved["basis"], resolved["scope"], resolved["unit_price_vnd"]) == (
        "manual_amount",
        "per_unit",
        None,
    )
    assert resolved["min_charge_kg"] is None


def _jewellery(db, shipment, **extra):
    return _fee(db, shipment, "hcm_air", 27, description="Bông tai mỹ ký", **extra)


def test_a_jewellery_line_without_an_amount_blocks_finalising(db, priced_world):  # noqa: F811
    con, kids = priced_world
    line = _jewellery(db, kids[2], weight_kg="2.5", quantity="3")
    assert line.weight_kg is None and line.quantity == D(1)  # no kilograms, no quantity
    est, _ = ps.estimate_for(db, con)
    issue = next(i for i in est.blocking if i.fee_line_id == line.id)
    # RC-UAT-20 (DEC-0228): the line needs the vendor's cost and the customer price.
    assert "enter the vendor's cost (VND) and the customer price (CAD)" in issue.message
    ps.reprice(db, kids[2], actor=None)
    ps.confirm_rate(db, kids[2], rate=None, reason=None, actor=None)
    with pytest.raises(ConflictError):
        ps.finalize(db, kids[2], negative_margin_reason="test", actor=None)
    db.rollback()


def test_a_jewellery_line_is_priced_from_the_entered_amount_like_any_surcharge(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    ops = api_for(Role.OPERATIONS)
    url = f"/api/v1/shipments/{shipment.id}/fee-lines/{line.id}"
    assert ops.patch(url, json={"manual_unit_price_vnd": "0"}).status_code == 422
    entered = ops.patch(url, json={"manual_unit_price_vnd": "450000"})
    assert entered.status_code == 200, entered.text
    assert D(entered.json()["manual_unit_price_vnd"]) == D(450000)
    see_committed_changes(db)
    audit = _audits(db, "shipment.fee_line_amount")[-1]
    assert json.loads(audit.detail_json)["to"] == "450000.00"
    # RC-UAT-20 (DEC-0228): the VND alone still blocks; the customer price is needed too.
    est, _ = ps.estimate_for(db, con)
    issue = next(i for i in est.blocking if i.fee_line_id == line.id)
    assert "enter the customer price (CAD)" in issue.message
    assert ops.patch(url, json={"customer_price_cad": "40.00"}).status_code == 200
    see_committed_changes(db)

    est, _ = ps.estimate_for(db, con)
    assert not [i for i in est.blocking if i.fee_line_id == line.id]
    fee = next(f for f in est.fees if f.section == "hcm_air" and f.stt == 27)
    assert fee.vendor_fee_vnd == D(450000) and fee.master_wide is False
    # The cost is the triggering shipment's alone (no master-wide share), at Kango's fixed
    # 19,500 VND/CAD under method v0.5 (DEC-0252): 450,000 / 19,500 = 23.08.
    assert set(fee.cost_alloc_vnd) == {shipment.id}
    assert fee.cost_alloc_cad == {shipment.id: (D(450000) / D(19500)).quantize(D("0.01"))}
    assert fee.cost_alloc_cad == {shipment.id: D("23.08")}
    # The customer is billed exactly the entered price: no conversion, no markup (DEC-0228).
    assert fee.customer_base_cad == fee.customer_total_cad == D("40.00")
    assert fee.revenue_alloc_cad == {shipment.id: D("40.00")}


def test_only_a_case_by_case_line_takes_an_amount_this_way(db, priced_world, api_for):  # noqa: F811
    _con, kids = priced_world
    shipment = kids[1]
    other = _fee(db, shipment, "hcm_air", 18, quantity=1)  # a priced rule
    ops = api_for(Role.OPERATIONS)
    refused = ops.patch(
        f"/api/v1/shipments/{shipment.id}/fee-lines/{other.id}",
        json={"manual_unit_price_vnd": "100000"},
    )
    assert refused.status_code == 422 and refused.json()["field"] == "manual_unit_price_vnd"
    see_committed_changes(db)
    assert db.get(ShipmentFeeLine, other.id).manual_unit_price_vnd is None
    # Marketing cannot write fee lines at all.
    line = _jewellery(db, shipment)
    marketing = api_for(Role.MARKETING)
    assert (
        marketing.patch(
            f"/api/v1/shipments/{shipment.id}/fee-lines/{line.id}",
            json={"manual_unit_price_vnd": "1"},
        ).status_code
        == 403
    )


# === Review findings (2026-10-22) ===============================================================


def test_a_quoted_amount_is_rounded_before_it_must_be_positive_and_capped(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    ops = api_for(Role.OPERATIONS)
    url = f"/api/v1/shipments/{shipment.id}/fee-lines/{line.id}"
    for bad in ("0.001", "1e-9", "0.004", "1e30", "1000000000000", "NaN", "Infinity", "-5"):
        refused = ops.patch(url, json={"manual_unit_price_vnd": bad})
        assert refused.status_code == 422, (bad, refused.text)
    see_committed_changes(db)
    assert db.get(ShipmentFeeLine, line.id).manual_unit_price_vnd is None
    rounded = ops.patch(url, json={"manual_unit_price_vnd": "0.005"})
    assert rounded.status_code == 200 and D(rounded.json()["manual_unit_price_vnd"]) == D("0.01")
    # The same rules on add.
    item = db.get(ShipmentFeeLine, line.id).item_id
    added = ops.post(
        f"/api/v1/shipments/{shipment.id}/fee-lines",
        json={"item_id": item, "section": "hcm_air", "stt": 13, "manual_unit_price_vnd": "0.001"},
    )
    assert added.status_code == 422, added.text
    with pytest.raises(ValidationError):
        ps.vnd_amount("1e30")


def test_a_line_priced_per_kg_under_the_old_reading_must_be_re_entered(
    db,
    priced_world,  # noqa: F811
):
    """S-8: a row-27 line carrying kilograms and a price from the old per-kg reading is never
    reread as the line's amount; it blocks until staff re-enter the amount."""
    con, kids = priced_world
    shipment = kids[2]
    line = _jewellery(db, shipment)
    line.weight_kg = D("2.5")  # as stored under the old item-weight reading
    line.manual_unit_price_vnd = D("150000")  # a price per kg then
    db.commit()
    est, _ = ps.estimate_for(db, con)
    issue = next(i for i in est.blocking if i.fee_line_id == line.id)
    assert "re-enter the quoted amount" in issue.message
    # RC-UAT-20 (DEC-0228): the customer price (CAD) is entered with it.
    ps.set_fee_line_amount(db, shipment, line.id, "400000", customer_price_cad="35", actor=None)
    db.commit()
    assert db.get(ShipmentFeeLine, line.id).weight_kg is None
    est, _ = ps.estimate_for(db, con)
    assert not [i for i in est.blocking if i.fee_line_id == line.id]
    fee = next(f for f in est.fees if f.stt == 27)
    assert fee.vendor_fee_vnd == D(400000)


def test_a_changing_save_must_echo_the_tax_the_screen_showed(
    db,
    priced_world,  # noqa: F811
    api_for,
):
    _con, kids = priced_world
    _offer, draft = _accepted(db, kids[2])
    url = f"/api/v1/invoice-drafts/{draft.id}"
    ops = api_for(Role.OPERATIONS)
    lines = drafts.lines_of(draft)
    change = {"expected_revision": 1, "tax_rate_percent": 5, "tax_confirmed": True}
    missing = ops.patch(url, json=change)
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "tax_unconfirmed"
    stale_figures = shown_tax(lines, 13, "included")  # what the screen showed before the change
    wrong = ops.patch(url, json={**change, **stale_figures})
    assert wrong.status_code == 422, wrong.text
    detail = wrong.json()["detail"]
    assert detail["code"] == "tax_unconfirmed" and detail["tax_rate_percent"] == 5
    assert ops.get(url).json()["revision"] == 1  # nothing saved
    right = ops.patch(url, json={**change, **shown_tax(lines, 5, "included")})
    assert right.status_code == 200, right.text
    assert right.json()["tax_confirmed"] is True and right.json()["revision"] == 2
    # A notes-only save needs no echo; an echo sent anyway is still checked.
    assert (
        ops.patch(
            url, json={"expected_revision": 2, "notes": "Fragile", "tax_confirmed": True}
        ).status_code
        == 200
    )
    off = {**shown_tax(lines, 5, "included"), "confirmed_total_cad": "1.00"}
    echoed = ops.patch(url, json={"expected_revision": 3, "tax_confirmed": True, **off})
    assert echoed.status_code == 422


def test_no_included_note_at_zero_percent():
    assert fs.tax_included_note("included", "gst_hst_0", "en") is None
    assert fs.tax_included_note("included", "gst_hst_5", "en") == "Prices include GST/HST 5 %"


def test_master_and_last_mile_links_both_reach_the_customer_one_each_in_leg_order(
    client,
    db,
    priced_world,  # noqa: F811
):
    _con, kids = priced_world
    shipment = kids[2]
    _link(db, shipment, leg_type="consolidation_linehaul", label="Kango air", url=DHL)
    _link(db, shipment, leg_type="final_delivery", label="UPS", url=UPS, sequence=2)
    _link(db, shipment, leg_type="final_delivery", label="UPS 2", url=UPS + "9", sequence=3)
    body = client.get(f"/api/v1/public/track/{shipment.public_id}").json()
    assert [(x["tracking_name_key"], x["url"]) for x in body["carrier_links"]] == [
        ("master_tracking", DHL),
        ("last_mile_tracking", UPS),
    ]
    assert body["carrier_link"] == body["carrier_links"][0]
    assert "kango" not in json.dumps(body).lower()


def test_the_account_shows_both_tracking_links(
    account_client, account_db, account_users, captured_mail
):
    from tests.test_account_profile import _customer, _setup
    from tests.test_quote_offers import _account_world

    _reference, me = _setup(account_client, account_users, captured_mail)
    mine = _account_world(account_db, _customer(account_db))[2]
    _link(account_db, mine, leg_type="origin_pickup", label="Kango pickup", url=DHL)
    _link(account_db, mine, leg_type="destination_handling", label="UPS", url=UPS, sequence=2)
    body = me.get(f"/shipments/{mine.public_id}").json()
    assert [x["carrier_name"] for x in body["carrier_links"]] == [
        "Master Tracking",
        "Last Mile Tracking",
    ]
