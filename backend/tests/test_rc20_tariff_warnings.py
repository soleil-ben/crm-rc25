"""RC-20: a tariff version's import warnings on Settings > Tariffs (owner, 2026-10-23).

``GET /tariffs/versions/{id}/warnings`` returns the importer's warnings (the anomalies of the
stored import report), a page at a time, and the three owner-confirmed price steps
(DEC-0222) apart: listed as confirmed, never counted as warnings. Sanitized fixture only.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from app.core.enums import Role
from app.pricing.kango_workbook import CONFIRMED_PRICE_STEPS
from app.services import tariff_import_service as svc

WORKBOOK = (
    Path(__file__).resolve().parent / "fixtures" / "kango_canada_rates_2026-10-12_sanitized.xlsx"
)

#: The sanitized fixture (the one the UAT seed imports) after RC-19 (DEC-0225): every
#: warning the importer stores for it, by code.
EXPECTED_BY_CODE = {
    "express_zone_below_ground": 35,
    "trucking_pallet_fees_not_imported": 2,
    "duplicate_fsa": 1,
    "beyond_code_without_rate": 1,
}
EXPECTED_COUNT = sum(EXPECTED_BY_CODE.values())


@pytest.fixture
def version(db):
    imported = svc.import_workbook(
        db,
        WORKBOOK.read_bytes(),
        file_name=WORKBOOK.name,
        effective_from=date(2026, 10, 12),
        label=None,
        actor=None,
    )
    db.commit()
    return imported


def _url(version_id: int, **params) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/api/v1/tariffs/versions/{version_id}/warnings" + (f"?{query}" if query else "")


def test_count_and_breakdown_match_the_stored_report(as_admin, version):
    body = as_admin.get(_url(version.id, limit=500)).json()
    stored = svc.report(version)["anomalies"]
    assert body["version_public_id"] == version.public_id
    assert body["count"] == len(stored) == EXPECTED_COUNT
    assert body["counts_by_code"] == EXPECTED_BY_CODE
    assert Counter(i["code"] for i in body["items"]) == Counter(EXPECTED_BY_CODE)
    # The full list, in the importer's order, with its sheet and cell.
    assert [(i["code"], i["sheet"], i["cell"], i["message"]) for i in body["items"]] == [
        (a["code"], a["sheet"], a["cell"], a["message"]) for a in stored
    ]
    assert all(i["message"] for i in body["items"])


def test_confirmed_price_steps_are_listed_apart_and_not_counted(as_admin, version):
    body = as_admin.get(_url(version.id, limit=500)).json()
    steps = body["confirmed_price_steps"]
    assert (
        {(s["sheet"], s["cell"]) for s in steps}
        == set(CONFIRMED_PRICE_STEPS)
        == {
            ("HCM-AIR-CAD", "F39"),
            ("HN-AIR-CAD", "F38"),
            ("HN-AIR-CAD", "G38"),
        }
    )
    assert all("DEC-0222" in s["reference"] and s["price_vnd"] for s in steps)
    warned_cells = {(i["sheet"], i["cell"]) for i in body["items"]}
    assert not warned_cells & set(CONFIRMED_PRICE_STEPS)
    assert "price_falls_with_weight" not in body["counts_by_code"]


def test_pagination(as_admin, version):
    everything = as_admin.get(_url(version.id, limit=500)).json()["items"]
    first = as_admin.get(_url(version.id, limit=10, offset=0)).json()
    second = as_admin.get(_url(version.id, limit=10, offset=10)).json()
    last = as_admin.get(_url(version.id, limit=10, offset=30)).json()
    past = as_admin.get(_url(version.id, limit=10, offset=1000)).json()
    assert first["count"] == second["count"] == EXPECTED_COUNT
    assert (first["limit"], first["offset"]) == (10, 0)
    assert first["items"] == everything[:10]
    assert second["items"] == everything[10:20]
    assert last["items"] == everything[30:] and len(last["items"]) == EXPECTED_COUNT - 30
    assert past["items"] == [] and past["count"] == EXPECTED_COUNT
    # The default page is 50, enough for the whole fixture.
    assert as_admin.get(_url(version.id)).json()["items"] == everything
    assert as_admin.get(_url(version.id, limit=0)).status_code == 422
    assert as_admin.get(_url(version.id, limit=501)).status_code == 422
    assert as_admin.get(_url(version.id, offset=-1)).status_code == 422


def test_permission_is_tariff_read(api_for, client, version):
    assert client.get(_url(version.id)).status_code == 401
    assert api_for(Role.OPERATIONS).get(_url(version.id)).status_code == 200
    assert api_for(Role.MARKETING).get(_url(version.id)).status_code == 403
    assert api_for(Role.READ_ONLY_MANAGER).get(_url(version.id)).status_code == 403


def test_unknown_version_is_404(as_admin, version):
    assert as_admin.get(_url(version.id + 999)).status_code == 404


def test_a_version_without_a_report_has_no_warnings(as_admin, db, version):
    version.import_report_json = "{}"
    db.commit()
    body = as_admin.get(_url(version.id)).json()
    assert body["count"] == 0 and body["items"] == [] and body["confirmed_price_steps"] == []
