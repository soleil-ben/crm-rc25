"""The Phase 17 UAT air dataset (`scripts/uat_seed_phase13.py`, run by `uat_env.py`).

Built for real -- migrations, the base seed, its augmentation and the air dataset -- into a
temporary UAT directory, never `data/uat/`. Checked: every coverage category is present; the
data a case names is there in the state the case expects; a second run adds nothing; only
reserved addresses appear; and the seed refuses a database, a mail folder or an intake folder
it was not built for.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
UAT_ENV_PATH = REPO_ROOT / "scripts" / "uat_env.py"
SEED_PATH = REPO_ROOT / "scripts" / "uat_seed_phase13.py"


def load_uat_env():
    spec = importlib.util.spec_from_file_location("uat_env_phase13_under_test", UAT_ENV_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def point_at(module, uat_dir: Path, monkeypatch) -> Path:
    monkeypatch.setattr(module, "UAT_DIR", uat_dir)
    monkeypatch.setattr(module, "UAT_DB", uat_dir / "solaris_uat.uat.db")
    monkeypatch.setattr(module, "UAT_MAIL_DIR", uat_dir / "account_mail")
    monkeypatch.setattr(module, "UAT_INTAKE_DIR", uat_dir / "tariff_intake")
    return uat_dir / "solaris_uat.uat.db"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One full build, shared by the read-only checks below."""
    module = load_uat_env()
    monkeypatch = pytest.MonkeyPatch()
    uat_dir = tmp_path_factory.mktemp("uat")
    path = point_at(module, uat_dir, monkeypatch)
    target = module.validated_target(path)
    module.create(target, reset=True)
    yield module, target
    monkeypatch.undo()


def rows(path: Path, query: str) -> list[tuple]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def test_every_required_category_is_present(built, capsys):
    module, path = built
    assert module.report(path) == 0
    assert "Every required category is present." in capsys.readouterr().out


def test_the_five_masters_are_at_the_stages_the_cases_name(built):
    _, path = built
    assert dict(
        rows(
            path,
            "select vendor_reference, state from consolidations "
            "where vendor_reference like 'UAT-AWB-%'",
        )
    ) == {
        "UAT-AWB-OPEN": "open",
        "UAT-AWB-BOOKED": "booked",
        "UAT-AWB-TRANSIT": "booked",
        "UAT-AWB-DELIVERED": "completed",
        "UAT-AWB-CLOSED": "completed",
    }


def test_quotes_invoices_and_money_are_in_the_expected_state(built):
    _, path = built
    offers = dict(
        rows(
            path,
            "select s.booking_reference, o.status from quote_offers o "
            "join shipments s on s.id = o.shipment_id",
        )
    )
    assert offers == {
        "UAT-AIR-A1-2": "sent",
        "UAT-AIR-A1-1": "accepted",
        "UAT-AIR-A2-1": "accepted",
        # RC-UAT-20 (DEC-0227): the domestic Canada -> Canada shipments, accepted by A2.
        "UAT-AIR-DOM-NS": "accepted",
        "UAT-AIR-DOM-NB": "accepted",
        "UAT-AIR-DOM-UNK": "accepted",
    }
    invoices = dict(
        rows(
            path,
            "select s.booking_reference, i.tax_status || ' ' || i.status "
            "from customer_invoices i join shipments s on s.id = i.shipment_id",
        )
    )
    assert invoices == {
        "UAT-AIR-A3-3": "gst_hst_0 paid",
        # RC-UAT-20 (DEC-0227): VN-CA is zero-rated by route (13 % under RC-UAT-19).
        "UAT-AIR-A1-1": "gst_hst_0 issued",
        "UAT-AIR-A3-2": "gst_hst_0 partially_paid",
        "UAT-AIR-A4-3": "gst_hst_5 partially_paid",
    }
    assert rows(path, "select count(*) from customer_payments where currency = 'VND'") == [(1,)]
    assert rows(path, "select count(*) from customer_payments where kind = 'refund'") == [(1,)]
    bills = rows(
        path,
        "select vendor_bill_number, status, variance_cad != 0, variance_reason is not null "
        "from vendor_invoices order by vendor_bill_number",
    )
    assert bills == [
        ("UAT-BILL-CLOSED", "paid", 0, 0),
        ("UAT-BILL-DELIVERED", "paid", 1, 1),
    ]
    assert rows(path, "select count(*) from period_closes where reopened_at is null") == [(1,)]


def test_domestic_drafts_take_the_destination_province_rate(built):
    """DEC-0227: a Canada -> Canada draft auto-fills the destination province's rate,
    included; with no recognisable province no rate is suggested and staff must choose."""
    _, path = built
    shipments = rows(
        path,
        "select booking_reference, route_group, origin_country_code, "
        "destination_country_code, recipient_province_state, recipient_postal_code "
        "from shipments where booking_reference like 'UAT-AIR-DOM-%' order by booking_reference",
    )
    assert shipments == [
        ("UAT-AIR-DOM-NB", "CAD", "CA", "CA", "NB", "E1C 4M3"),
        ("UAT-AIR-DOM-NS", "CAD", "CA", "CA", "NS", "B3H 1A1"),
        ("UAT-AIR-DOM-UNK", "CAD", "CA", "CA", None, None),
    ]
    drafts = rows(
        path,
        "select s.booking_reference, d.status, r.route_band, r.destination_province, "
        "r.suggested_rate_percent, r.suggested_mode, r.rate_required, r.rate_chosen_at "
        "from invoice_drafts d join shipments s on s.id = d.shipment_id "
        "join invoice_draft_tax_route r on r.draft_id = d.id "
        "where s.booking_reference like 'UAT-AIR-DOM-%' order by s.booking_reference",
    )
    assert drafts == [
        ("UAT-AIR-DOM-NB", "draft", "domestic", "NB", 15, "included", 0, None),
        ("UAT-AIR-DOM-NS", "draft", "domestic", "NS", 14, "included", 0, None),
        ("UAT-AIR-DOM-UNK", "draft", "domestic", None, None, "included", 1, None),
    ]
    rates = dict(
        rows(
            path,
            "select s.booking_reference, d.tax_rate_percent from invoice_drafts d "
            "join shipments s on s.id = d.shipment_id "
            "where s.booking_reference in ('UAT-AIR-DOM-NS', 'UAT-AIR-DOM-NB')",
        )
    )
    assert rates == {"UAT-AIR-DOM-NS": 14, "UAT-AIR-DOM-NB": 15}
    # The stand-in master is not one of the five UAT-AWB-* masters the cases name.
    assert rows(
        path, "select state from consolidations where vendor_reference = 'UAT-DOM-AWB'"
    ) == [("booked",)]


def test_accounts_milestone_emails_and_the_opt_out(built):
    module, path = built
    accounts = dict(
        rows(
            path,
            "select i.email_normalized, i.preferred_language from customer_identities i "
            "join customer_identity_links l on l.identity_id = i.id where l.status = 'active'",
        )
    )
    assert accounts == {"trang.air@example.com": "vi", "emily.air@example.com": "en"}
    outcomes = dict(
        rows(
            path,
            "select o.template_key, o.status from notification_outbox o "
            "join shipments s on s.id = o.shipment_id "
            "where s.booking_reference = 'UAT-AIR-A2-1'",
        )
    )
    assert outcomes == {"notify.received.en": "sent", "notify.in_transit.en": "skipped"}
    departure = rows(
        path,
        "select e.public_update_text from shipment_events e join shipments s "
        "on s.id = e.shipment_id where s.booking_reference = 'UAT-AIR-A1-1' "
        "and e.event_type = 'departed_origin' and e.is_public_update = 1",
    )
    assert departure and departure[0][0]  # staff wording, shown under the standard sentence
    captured = list(module.UAT_MAIL_DIR.glob("*.json"))
    assert any("notify" in p.name or "quote" in p.name for p in captured)


def test_the_two_rate_emails_became_a_draft_and_a_held_intake(built):
    module, path = built
    assert sorted(rows(path, "select status, sender from tariff_email_intakes")) == [
        ("held_sender", "rates@unknown-forwarder.example.com"),
        ("imported", "rates@vendor-rates.example.com"),
    ]
    assert sorted(p.name for p in (module.UAT_INTAKE_DIR / "samples").glob("*.eml")) == [
        "uat-rates-allowed.eml",
        "uat-rates-unknown-sender.eml",
    ]
    assert len(list((module.UAT_INTAKE_DIR / "processed").glob("*.eml"))) == 2
    assert not list(module.UAT_INTAKE_DIR.glob("*.eml"))  # the worker moved both


def test_only_reserved_addresses_and_the_demo_admin_as_approver(built):
    _, path = built
    settings = rows(path, "select approver_emails from tariff_intake_settings")
    assert settings == [('["admin@demo.example.com"]',)]
    for (address,) in rows(
        path,
        "select email_normalized from customers where email_normalized is not null "
        "union select email_normalized from customer_identities "
        "union select email from users",
    ):
        assert address.endswith("example.com"), address


def test_no_text_column_holds_a_real_company_address(built):
    """The UAT database never stores the real mailbox or approver (S1): every text column
    of every table is scanned, not only the ones expected to hold an address."""
    _, path = built
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            name
            for (name,) in connection.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        ]
        hits = []
        for table in tables:
            columns = [
                row[1]
                for row in connection.execute(f'pragma table_info("{table}")')
                if not row[2] or any(k in row[2].upper() for k in ("CHAR", "TEXT", "CLOB", "JSON"))
            ]
            for column in columns:
                found = connection.execute(
                    f'select count(*) from "{table}" where lower(cast("{column}" as text)) '  # noqa: S608
                    "like '%soleiltransportation.com%'"
                ).fetchone()[0]
                if found:
                    hits.append(f"{table}.{column}")
    finally:
        connection.close()
    assert hits == []
    assert rows(path, "select mailbox_address from tariff_intake_settings") == [
        ("tariffs@demo.example.com",)
    ]


def test_a_target_in_a_sub_directory_is_refused(tmp_path, monkeypatch):
    module = load_uat_env()
    point_at(module, tmp_path / "uat", monkeypatch)
    with pytest.raises(module.SafetyError, match="sub-directory"):
        module.validated_target(tmp_path / "uat" / "nested" / "x.uat.db")


def test_a_second_run_adds_nothing(built):
    module, path = built
    tables = ("consolidations", "quote_offers", "customer_invoices", "tariff_email_intakes")
    before = {t: rows(path, f"select count(*) from {t}") for t in tables}  # noqa: S608
    assert module.seed_air(path) == ["already present (UAT-AWB-OPEN); nothing added"]
    assert {t: rows(path, f"select count(*) from {t}") for t in tables} == before  # noqa: S608


def test_refresh_fx_adds_one_demo_reading_and_nothing_else(built):
    module, path = built
    before = rows(path, "select count(*) from fx_rate_snapshots")[0][0]
    offers = rows(path, "select count(*) from quote_offers")
    assert module.seed_air(path, "--refresh-fx") == [
        "added a fresh demo exchange-rate reading (source demo://fixture)"
    ]
    assert rows(path, "select count(*) from fx_rate_snapshots")[0][0] == before + 1
    assert rows(path, "select count(*) from quote_offers") == offers


# --- Refusals ------------------------------------------------------------------------------------


def run_seed(**env) -> subprocess.CompletedProcess:
    full = {
        **os.environ,
        "ENVIRONMENT": "development",
        "ALLOW_DEMO_SEED": "true",
        "PYTHONIOENCODING": "utf-8",
        **env,
    }
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SEED_PATH)],
        cwd=BACKEND_ROOT,
        env=full,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_the_seed_refuses_a_database_that_is_not_a_uat_one(tmp_path):
    result = run_seed(
        DATABASE_URL=f"sqlite:///{(tmp_path / 'other.db').as_posix()}",
        ACCOUNT_EMAIL_CAPTURE_DIR=str(tmp_path / "mail"),
        TARIFF_INTAKE_DIR=str(tmp_path / "intake"),
    )
    assert result.returncode == 2 and "Refused" in result.stderr
    assert not (tmp_path / "other.db").exists()


def test_the_seed_refuses_folders_outside_the_uat_database_directory(tmp_path):
    home = tmp_path / "uat"
    home.mkdir()
    url = f"sqlite:///{(home / 'x.uat.db').as_posix()}"
    for mail, intake in (
        (tmp_path / "mail", home / "intake"),
        (home / "mail", tmp_path / "intake"),
    ):
        result = run_seed(
            DATABASE_URL=url, ACCOUNT_EMAIL_CAPTURE_DIR=str(mail), TARIFF_INTAKE_DIR=str(intake)
        )
        assert result.returncode == 2 and "outside" in result.stderr
    assert not (home / "x.uat.db").exists()


def test_the_seed_refuses_production(tmp_path):
    home = tmp_path / "uat"
    result = run_seed(
        ENVIRONMENT="production",
        DATABASE_URL=f"sqlite:///{(home / 'x.uat.db').as_posix()}",
        ACCOUNT_EMAIL_CAPTURE_DIR=str(home / "mail"),
        TARIFF_INTAKE_DIR=str(home / "intake"),
    )
    assert result.returncode != 0
    assert not (home / "x.uat.db").exists()


def test_the_intake_folder_is_only_ever_cleared_inside_the_uat_directory(tmp_path, monkeypatch):
    module = load_uat_env()
    point_at(module, tmp_path / "uat", monkeypatch)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "keep.eml").write_text("x", encoding="utf-8")
    monkeypatch.setattr(module, "UAT_INTAKE_DIR", outside)
    with pytest.raises(module.SafetyError):
        module.clear_intake_folder()
    assert (outside / "keep.eml").exists()
