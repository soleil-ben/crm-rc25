"""`scripts/expire_account_link.py`: an expired link for CA-REG-07, and nowhere it must not go.

Two halves, both asserted rather than left to the reader:

* **It refuses.** Outside ``development`` and ``uat``; against a path that is neither the
  UAT database nor the development one; against the development database under UAT; against
  an end-to-end scratch database or a backup; against a file that does not exist; and for
  an address that is not on a reserved test domain. Every refusal changes nothing.
* **What it does is real.** The link is refused by the server *as expired* -- the audit
  log says ``expired``, not ``unknown`` -- and the rest of CA-REG-07 then holds: a new
  link works and the aged one still does not.

No test here touches the real ``data/uat/`` or the development database. The script's
directory constants are moved into a temporary directory first.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.account_enums import IdentityStatus, TokenPurpose
from app.core.db import build_engine
from app.core.time_utils import utcnow
from app.models import AuditEvent, Base, CustomerAuthToken, CustomerIdentity
from app.services import customer_auth_service, customer_identity_service
from tests.account_fixtures import register, verification_token, verify

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "expire_account_link.py"
ADDRESS = "hanh@demo.example.com"
RESEND = "/api/v1/account/verification/resend"


def load_script():
    """Import the script by path. It is a script, not an installed module."""
    spec = importlib.util.spec_from_file_location("expire_account_link_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(tmp_path, monkeypatch):
    """The script, with every location it recognises moved under ``tmp_path``."""
    module = load_script()
    monkeypatch.setattr(module, "UAT_DIR", tmp_path / "data" / "uat")
    monkeypatch.setattr(module, "UAT_DB", tmp_path / "data" / "uat" / "solaris_uat.uat.db")
    monkeypatch.setattr(module, "DEV_DB", tmp_path / "data" / "solaris_crm.db")
    monkeypatch.setattr(module, "E2E_DIR", tmp_path / "data" / "e2e")
    monkeypatch.setattr(module, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setenv("ENVIRONMENT", "uat")
    return module


def _empty_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _database_with_a_link(path: Path, email: str = ADDRESS) -> str:
    """A schema'd database holding one identity with one outstanding verification link."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = build_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as db:
        identity = CustomerIdentity(
            public_id="CA-000001",
            email_entered=email,
            email_normalized=email,
            password_hash="",
            status=IdentityStatus.PENDING_VERIFICATION,
            failed_sign_in_count=0,
        )
        customer_auth_service.set_password(db, identity, password="SolarisCustomer!2026")
        db.add(identity)
        db.flush()
        issued = customer_identity_service.issue_token(
            db, identity, purpose=TokenPurpose.EMAIL_VERIFICATION, request_ip=None
        )
        db.commit()
        plaintext = issued.plaintext
    engine.dispose()
    return plaintext


def _redeem(path: Path, token: str, purpose=TokenPurpose.EMAIL_VERIFICATION):
    engine = build_engine(f"sqlite:///{path.as_posix()}")
    try:
        with sessionmaker(bind=engine, future=True)() as db:
            return customer_identity_service.redeem_token(db, token=token, purpose=purpose)
    finally:
        engine.dispose()


def _token_rows(path: Path) -> list[tuple]:
    engine = build_engine(f"sqlite:///{path.as_posix()}")
    try:
        with sessionmaker(bind=engine, future=True)() as db:
            return [
                (row.issued_at, row.expires_at)
                for row in db.scalars(select(CustomerAuthToken)).all()
            ]
    finally:
        engine.dispose()


# --- Refusals ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "environment", ["production", "prod", "e2e", "test", "staging", "PRODUCTION", ""]
)
def test_it_refuses_outside_development_and_uat_and_changes_nothing(
    script, tmp_path, monkeypatch, capsys, environment
):
    target = tmp_path / "data" / "uat" / "solaris_uat.uat.db"
    _database_with_a_link(target)
    before = _token_rows(target)
    monkeypatch.setenv("ENVIRONMENT", environment)

    assert script.main([ADDRESS, "--path", str(target)]) == 2
    assert "Refused" in capsys.readouterr().err
    assert _token_rows(target) == before


@pytest.mark.parametrize("environment", ["development", "uat", "UAT", " development "])
def test_development_and_uat_are_accepted(script, tmp_path, environment):
    target = _empty_file(tmp_path / "data" / "uat" / "solaris_uat.uat.db")
    resolved = script.validated_database(target, environment.strip().lower())
    assert resolved.name == "solaris_uat.uat.db"


def test_an_unset_environment_counts_as_development(script, monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert script.current_environment() == "development"


@pytest.mark.parametrize(
    "relative",
    [
        "elsewhere/solaris_uat.uat.db",  # the suffix, outside the UAT directory
        "data/uat/solaris_uat.db",  # the UAT directory, without the suffix
        "data/uat-old/solaris_uat.uat.db",  # a sibling that only starts with the name
        "data/e2e/run.e2e.db",
        "data/uat/scratch.e2e.db",
        "backups/solaris_uat.uat.db",
        "data/production.db",
    ],
)
def test_it_refuses_any_database_it_does_not_recognise(script, tmp_path, relative):
    target = _empty_file(tmp_path / relative)
    with pytest.raises(script.SafetyError):
        script.validated_database(target, "uat")


def test_it_refuses_a_database_that_does_not_exist(script, tmp_path):
    with pytest.raises(script.SafetyError, match="never creates"):
        script.validated_database(tmp_path / "data" / "uat" / "missing.uat.db", "uat")
    assert not (tmp_path / "data" / "uat" / "missing.uat.db").exists()


def test_the_development_database_is_allowed_only_under_development(script, tmp_path):
    dev = _empty_file(tmp_path / "data" / "solaris_crm.db")
    assert script.validated_database(dev, "development") == script._canonical(dev)
    with pytest.raises(script.SafetyError, match="development database"):
        script.validated_database(dev, "uat")


def test_it_refuses_an_address_that_is_not_on_a_reserved_domain(script, tmp_path, capsys):
    target = tmp_path / "data" / "uat" / "solaris_uat.uat.db"
    _database_with_a_link(target)
    before = _token_rows(target)

    assert script.main(["someone@solarisexpress.ca", "--path", str(target)]) == 2
    assert "reserved test domain" in capsys.readouterr().err
    assert _token_rows(target) == before


def test_an_address_with_no_account_changes_nothing(script, tmp_path, capsys):
    target = tmp_path / "data" / "uat" / "solaris_uat.uat.db"
    _database_with_a_link(target)
    before = _token_rows(target)

    assert script.main(["nobody@example.com", "--path", str(target)]) == 1
    assert "No Customer Account" in capsys.readouterr().out
    assert _token_rows(target) == before


# --- What it does --------------------------------------------------------------------


def test_the_link_is_expired_in_the_database_and_refused_as_expired(script, tmp_path, capsys):
    target = tmp_path / "data" / "uat" / "solaris_uat.uat.db"
    token = _database_with_a_link(target)
    [(issued_before, expires_before)] = _token_rows(target)
    lifetime = expires_before - issued_before

    assert script.main([ADDRESS, "--path", str(target)]) == 0
    output = capsys.readouterr().out
    assert "CA-000001" in output
    # The token is a credential: it is never printed. Neither is the address.
    assert token not in output
    assert ADDRESS not in output

    [(issued_after, expires_after)] = _token_rows(target)
    assert expires_after < utcnow()
    assert issued_after < expires_after
    assert expires_after - issued_after == lifetime

    refused = _redeem(target, token)
    assert refused.ok is False
    assert refused.reason_code == "expired"

    # A second run finds nothing outstanding and says so rather than pretending.
    assert script.main([ADDRESS, "--path", str(target)]) == 1


def test_ageing_is_audited_without_the_token_or_the_address(script, tmp_path):
    target = tmp_path / "data" / "uat" / "solaris_uat.uat.db"
    token = _database_with_a_link(target)
    script.main([ADDRESS, "--path", str(target)])

    engine = build_engine(f"sqlite:///{target.as_posix()}")
    try:
        with sessionmaker(bind=engine, future=True)() as db:
            event = db.scalar(select(AuditEvent).where(AuditEvent.action == script.AUDIT_ACTION))
    finally:
        engine.dispose()
    assert event is not None
    detail = json.loads(event.detail_json)
    assert detail == {
        "identity_public_id": "CA-000001",
        "purposes": ["email_verification"],
        "count": 1,
    }
    blob = f"{event.summary} {event.detail_json}"
    assert token not in blob
    assert ADDRESS not in blob


def test_a_password_reset_link_is_aged_only_when_asked(script, tmp_path):
    target = tmp_path / "data" / "uat" / "solaris_uat.uat.db"
    verification = _database_with_a_link(target)
    engine = build_engine(f"sqlite:///{target.as_posix()}")
    with sessionmaker(bind=engine, future=True)() as db:
        identity = db.scalar(select(CustomerIdentity))
        reset = customer_identity_service.issue_token(
            db, identity, purpose=TokenPurpose.PASSWORD_RESET, request_ip=None
        ).plaintext
        db.commit()
    engine.dispose()

    assert script.main([ADDRESS, "--path", str(target), "--purpose", "password_reset"]) == 0
    assert _redeem(target, reset, TokenPurpose.PASSWORD_RESET).reason_code == "expired"
    # The verification link was not asked about and still works.
    assert _redeem(target, verification).ok is True


def test_ca_reg_07_end_to_end_the_aged_link_stays_refused_after_a_new_one(
    script, account_client, account_db, captured_mail
):
    """The case as a tester runs it: aged link refused, new link works, old one still not."""
    register(account_client, email=ADDRESS)
    old = verification_token(captured_mail, ADDRESS)

    result = script.expire_links(account_db, ADDRESS, script.PURPOSES["verification"])
    account_db.commit()
    assert result.total == 1

    refused = verify(account_client, old)
    assert refused.status_code == 422
    assert refused.json()["message"] == customer_identity_service.GENERIC_TOKEN_FAILURE
    account_db.expire_all()
    reasons = [
        json.loads(event.detail_json).get("reason_code")
        for event in account_db.scalars(
            select(AuditEvent).where(AuditEvent.action == "customer_account.verification_refused")
        )
    ]
    assert "expired" in reasons

    account_client.post(RESEND, json={"email": ADDRESS})
    new = verification_token(captured_mail, ADDRESS)
    assert new != old
    assert verify(account_client, new).status_code == 200
    assert verify(account_client, old).status_code == 422
