"""Phase 15: the approver badge -- drafts awaiting a decision and held-sender rate emails."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.enums import Role
from app.services import tariff_intake_service as svc
from tests.conftest import see_committed_changes
from tests.test_tariff_intake import WORKBOOK, build_eml, ingest
from tests.test_tariff_intake_review import manual_draft

URL = "/api/v1/tariffs/intake/pending-count"


@pytest.fixture(autouse=True)
def intake_folder(tmp_path, monkeypatch):
    folder = tmp_path / "intake"
    monkeypatch.setattr(settings, "tariff_intake_dir", str(folder))
    return folder


def test_counts_drafts_awaiting_review_and_held_senders(db, admin_is_tariff_approver, as_admin):
    empty = as_admin.get(URL)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {
        "viewer_is_approver": True,
        "drafts_awaiting": 0,
        "held_senders": 0,
        "total": 0,
    }

    draft = manual_draft(db, WORKBOOK.read_bytes())
    # No allowed domain: the email is held until an approver releases it.
    ingest(db, build_eml([("rates.xlsx", WORKBOOK.read_bytes())]))
    see_committed_changes(db)
    body = as_admin.get(URL).json()
    assert (body["drafts_awaiting"], body["held_senders"], body["total"]) == (1, 1, 2)

    # A rejected draft stays a draft but is decided: it no longer waits.
    rejected = as_admin.post(
        f"/api/v1/tariffs/versions/{draft.id}/reject", json={"reason": "Not ours"}
    )
    assert rejected.status_code == 200, rejected.text
    body = as_admin.get(URL).json()
    assert (body["drafts_awaiting"], body["held_senders"]) == (0, 1)


def test_a_non_approver_gets_no_counts(db, users, api_for):
    svc.update_settings(db, approver_emails=["owner@demo.example.com"], actor=None)
    db.commit()
    ingest(db, build_eml([("rates.xlsx", WORKBOOK.read_bytes())]))  # one held sender waits
    see_committed_changes(db)
    for role in (Role.OPERATIONS, Role.ADMIN):
        response = api_for(role).get(URL)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "viewer_is_approver": False,
            "drafts_awaiting": 0,
            "held_senders": 0,
            "total": 0,
        }


def test_roles_without_tariff_read_are_refused(api_for):
    for role in (Role.MARKETING, Role.READ_ONLY_MANAGER):
        assert api_for(role).get(URL).status_code == 403
