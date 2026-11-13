"""Unsafe production configuration is refused, and health says almost nothing.

Two halves.

**Startup.** `CRM.md` section 3 requires that a missing provider key never stops the CRM
from starting. It does not require that a *dangerous* setting be tolerated, and the
distinction is the point: an absent integration credential is incomplete, while a
development secret key in production is unsafe. The first is a warning, the second is a
refusal, and every refusal is listed at once so the operator fixes the configuration in
one pass rather than discovering the next problem on the next restart.

**Health.** Three unauthenticated endpoints, and none of them may tell a stranger
anything about the installation. No path, no version, no revision, no hostname, no
environment name, no configuration value, no stack trace, no row count, no customer
value, and no tracking reference. Readiness names the failing *check*, because an
operator needs to know which runbook to open, and a check name is not an internal.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import (
    CONFIGURATION_WARNING_CODES,
    DEV_SECRET_KEY,
    Settings,
    configuration_warnings,
    database_path_problems,
    production_configuration_problems,
)

GOOD_SECRET = "b7f3c1a95e2d48f6a0c3e7b1d9f2a4c68e0b3d5f7a9c1e3b5d7f9a1c3e5b7d9f"


def production(**overrides) -> Settings:
    """A production settings object that is safe unless a test makes it otherwise."""
    base = {
        "environment": "production",
        "secret_key": GOOD_SECRET,
        "cookie_secure": True,
        "allow_demo_seed": False,
        "debug": False,
        "log_level": "INFO",
        "cors_origins": "https://crm.example.com",
        "tracking_base_url": "https://track.example.com/track",
        "database_url": "sqlite:////srv/solaris/data/solaris_crm.db",
    }
    base.update(overrides)
    return Settings(**base)


# --- The baseline is actually safe ------------------------------------------------------


def test_a_correct_production_configuration_raises_nothing(monkeypatch, tmp_path):
    database = tmp_path / "solaris_crm.db"
    settings = production(database_url=f"sqlite:///{database.as_posix()}")

    assert production_configuration_problems(settings) == []


# --- Refusals ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"secret_key": DEV_SECRET_KEY}, "SECRET_KEY"),
        ({"secret_key": "changeme"}, "SECRET_KEY"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"allow_demo_seed": True}, "ALLOW_DEMO_SEED"),
        ({"debug": True}, "DEBUG"),
        ({"log_level": "DEBUG"}, "LOG_LEVEL"),
        ({"cors_origins": ""}, "CORS_ORIGINS"),
        ({"cors_origins": "http://localhost:5173"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://ok.example.com,http://127.0.0.1:5173"}, "CORS_ORIGINS"),
        ({"cors_origins": "http://crm.example.com"}, "CORS_ORIGINS"),
        ({"tracking_base_url": ""}, "TRACKING_BASE_URL"),
        ({"tracking_base_url": "http://localhost:5173/track"}, "TRACKING_BASE_URL"),
        ({"tracking_base_url": "http://track.example.com"}, "TRACKING_BASE_URL"),
        ({"trust_proxy_headers": True}, "TRUSTED_PROXY_HOSTS"),
        ({"trusted_proxy_hosts": "10.0.0.1"}, "TRUST_PROXY_HEADERS"),
    ],
)
def test_an_unsafe_production_setting_is_refused(overrides, expected, tmp_path):
    database = tmp_path / "solaris_crm.db"
    settings = production(database_url=f"sqlite:///{database.as_posix()}", **overrides)

    problems = production_configuration_problems(settings)

    assert problems, f"{overrides} was accepted"
    assert any(expected in problem for problem in problems), problems


def test_every_problem_is_reported_at_once_not_one_per_restart(tmp_path):
    """Four things wrong should be four lines, not four restarts."""
    settings = production(
        secret_key=DEV_SECRET_KEY,
        cookie_secure=False,
        allow_demo_seed=True,
        debug=True,
        database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}",
    )

    problems = production_configuration_problems(settings)

    assert len(problems) >= 4


def test_the_refusal_names_the_variable_and_the_reason(tmp_path):
    settings = production(
        cookie_secure=False, database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}"
    )

    (problem,) = production_configuration_problems(settings)

    assert "COOKIE_SECURE" in problem
    assert "production" in problem


# --- DEC-0048: both halves, or neither --------------------------------------------------


def test_proxy_trust_without_a_named_proxy_is_refused(tmp_path):
    """Half a proxy configuration is worse than none: it looks configured."""
    settings = production(
        trust_proxy_headers=True,
        trusted_proxy_hosts="",
        database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}",
    )

    (problem,) = production_configuration_problems(settings)

    assert "DEC-0048" in problem
    assert "rate-limit bucket" in problem


def test_both_halves_together_are_accepted(tmp_path):
    settings = production(
        trust_proxy_headers=True,
        trusted_proxy_hosts="10.0.0.1",
        database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}",
    )

    assert production_configuration_problems(settings) == []


def test_proxy_trust_is_off_by_default_and_phase_5b_did_not_change_that():
    """The phase brief forbids enabling it. This is the standing proof."""
    from app.core.config import settings as live

    assert live.trust_proxy_headers is False
    assert live.trusted_proxy_host_list == []


# --- Database path ----------------------------------------------------------------------


def test_a_relative_database_path_is_refused():
    settings = production(database_url="sqlite:///data/solaris_crm.db")

    problems = database_path_problems(settings)

    assert any("absolute" in problem for problem in problems)


def test_a_database_inside_the_source_tree_is_refused():
    from app.core.config import BACKEND_ROOT

    inside = (BACKEND_ROOT / "app" / "solaris_crm.db").as_posix()
    settings = production(database_url=f"sqlite:///{inside}")

    problems = database_path_problems(settings)

    assert any("source tree" in problem for problem in problems)


def test_a_missing_database_directory_is_refused(tmp_path):
    settings = production(database_url=f"sqlite:///{(tmp_path / 'nope' / 'x.db').as_posix()}")

    problems = database_path_problems(settings)

    assert any("does not exist" in problem for problem in problems)


def test_an_in_memory_database_has_no_path_to_complain_about():
    settings = production(database_url="sqlite:///:memory:")

    assert database_path_problems(settings) == []


# --- Warnings are not refusals ----------------------------------------------------------


def test_an_empty_help_url_warns_rather_than_refusing(tmp_path):
    """Incomplete, not unsafe. Refusing would block on an undecided business value."""
    settings = production(
        public_help_url="", database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}"
    )

    assert production_configuration_problems(settings) == []
    assert "public_help_url_empty" in configuration_warnings(settings)


def test_every_warning_code_is_documented():
    """A code with no explanation is a log line nobody can act on."""
    settings = Settings(public_help_url="", public_carrier_link_hosts="")

    for code in configuration_warnings(settings):
        assert code in CONFIGURATION_WARNING_CODES, code


def test_a_warning_code_is_a_vocabulary_token():
    """It travels in a structured `reason_code` field, which refuses free text."""
    from app.core.logging import _SAFE_CONSTANT

    for code in CONFIGURATION_WARNING_CODES:
        assert _SAFE_CONSTANT.match(code), code


# --- Health endpoints -------------------------------------------------------------------

#: Anything that would tell a stranger about the installation.
FORBIDDEN_IN_HEALTH = (
    "production",
    "development",
    "staging",
    "sqlite",
    "/srv",
    "C:\\",
    "Traceback",
    "secret",
    "password",
    "token",
    "e5623fcf8018",
    "alembic",
    "America/Toronto",
    ".py",
    "solaris_crm.db",
)


@pytest.mark.parametrize("path", ["/health", "/health/live", "/health/ready"])
def test_a_health_response_reveals_nothing_about_the_installation(client, path):
    response = client.get(path)
    body = response.text

    assert response.status_code in (200, 503)
    for term in FORBIDDEN_IN_HEALTH:
        assert term.lower() not in body.lower(), f"{path} mentions {term}"


def test_liveness_says_only_that_it_is_alive(client):
    assert client.get("/health/live").json() == {"status": "ok"}


def test_the_original_health_path_still_answers(client):
    """Phase 1 published `/health`; a monitor pointed at it must not break."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_no_longer_leaks_the_environment_name(client):
    """It told an anonymous caller whether they had found production. Removed in 5B."""
    assert "environment" not in client.get("/health").json()


def test_readiness_reports_each_check_by_name(client):
    body = client.get("/health/ready").json()

    assert body["status"] == "ready"
    assert set(body["checks"]) == {"database", "migrations", "timezone"}
    assert set(body["checks"].values()) == {"ok"}


def test_readiness_answers_503_when_a_check_fails(client, monkeypatch):
    """A process that cannot serve must not be sent traffic, and must not be restarted."""
    import app.main as main

    monkeypatch.setattr(main, "_check_database_reachable", lambda: False)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"] == "failed"


def test_a_failed_readiness_check_still_says_nothing_private(client, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "_check_database_reachable", lambda: False)

    body = client.get("/health/ready").text

    for term in FORBIDDEN_IN_HEALTH:
        assert term.lower() not in body.lower()


def test_health_is_not_behind_authentication(client):
    """A readiness probe has no session, and blocking it would fail every deployment."""
    for path in ("/health", "/health/live", "/health/ready"):
        assert client.get(path).status_code in (200, 503)


# --- Correlation on the wire ------------------------------------------------------------


def test_a_staff_response_carries_a_correlation_id(client):
    response = client.get("/health")

    assert response.headers["X-Correlation-ID"]


def test_a_public_response_carries_no_correlation_id(client):
    """DEC-0085. Every public failure must be byte-identical to every other."""
    response = client.get("/api/v1/public/track/SX-CAV-ABCDEFGHJKLM")

    assert "X-Correlation-ID" not in response.headers


def test_two_public_failures_remain_indistinguishable(client):
    first = client.get("/api/v1/public/track/SX-CAV-ABCDEFGHJKLM")
    second = client.get("/api/v1/public/track/SX-CAD-MLKJHGFEDCBA")

    assert first.status_code == second.status_code
    assert first.text == second.text
    assert dict(first.headers) == dict(second.headers)


def test_a_supplied_correlation_id_is_echoed_when_it_is_safe(client):
    response = client.get("/health", headers={"X-Correlation-ID": "trace-0123456789ab"})

    assert response.headers["X-Correlation-ID"] == "trace-0123456789ab"


def test_a_forged_correlation_id_is_replaced(client):
    response = client.get("/health", headers={"X-Correlation-ID": 'x"\n{"forged":true}'})

    assert response.headers["X-Correlation-ID"] != 'x"\n{"forged":true}'


# --- Bounded request bodies -------------------------------------------------------------


def test_an_oversized_request_body_is_refused_before_it_is_read(client):
    from app.core.config import settings

    oversized = b"x" * (settings.max_request_bytes + 1)
    response = client.post(
        "/api/v1/auth/login",
        content=oversized,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"


def test_an_ordinary_request_body_is_unaffected(client):
    response = client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "y"})

    assert response.status_code != 413


def test_the_import_limit_is_far_smaller_than_the_global_one():
    """The global bound is a backstop; the CSV limit is the one operators meet."""
    from app.core.config import settings
    from app.services.csv_safety import MAX_FILE_BYTES

    assert settings.max_request_bytes > MAX_FILE_BYTES


# --- The request log ---------------------------------------------------------------------


def test_a_public_request_logs_the_route_template_not_the_reference(client, caplog):
    import logging

    with caplog.at_level(logging.INFO):
        client.get("/api/v1/public/track/SX-CAV-ABCDEFGHJKLM")

    http = [r for r in caplog.records if r.getMessage() == "http_request"]
    assert http, "the request was not logged"
    for record in http:
        assert "ABCDEFGHJKLM" not in json.dumps(record.__dict__, default=str)
        assert "{reference" in record.route
