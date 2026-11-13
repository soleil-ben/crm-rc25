"""Integration health: permissions, honest state, and the actions that exist.

Two things are being checked, and the second matters more than the first.

**Permissions**, because the health surface is staff-only and the actions that change the
integration are narrower still (CRM.md section 11).

**Honesty**, because a health panel exists to be believed. With no provider configured the
only truthful connection state is ``not_configured``, and the values this cannot support
have to be *absent* rather than reassuring -- in particular ``stale_assignment_count`` is
``None`` and not ``0``, because no freshness rule exists and "0 stale" is a claim that
everything is fresh.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.enums import (
    IntegrationConnectionState,
    IntegrationJobStatus,
    ProviderErrorKind,
    Role,
)
from app.integrations.registry import AdapterRegistry
from app.models import IntegrationConnection
from app.services import integration_health_service as health
from app.services import integration_job_service as jobs
from tests.fakes.fake_provider_adapter import FakeProviderAdapter

BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)
HEALTH = "/api/v1/integrations/health"
JOBS = "/api/v1/integrations/jobs"


def clock_at(moment: datetime = BASE_TIME):
    return lambda: moment


def enqueue(db, **kwargs):
    defaults = {
        "job_type": "refresh_tracking_assignment",
        "provider_key": "fake",
        "clock": clock_at(),
    }
    defaults.update(kwargs)
    job = jobs.enqueue(db, **defaults)
    db.commit()
    return job


# --- Honest state -----------------------------------------------------------


def test_with_no_provider_the_only_state_is_not_configured(db):
    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert result.any_provider_configured is False
    assert len(result.connections) == 1
    connection = result.connections[0]
    assert connection.state == IntegrationConnectionState.NOT_CONFIGURED
    assert connection.provider_key is None
    assert connection.provider_api_version is None
    assert connection.last_success_at is None
    assert connection.last_error_at is None


def test_the_summary_says_what_a_staff_member_needs_to_know(db):
    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert "No provider account is connected" in result.summary
    assert "Automatic tracking is unavailable" in result.summary
    assert "Manual milestones" in result.summary


def test_the_stale_count_is_none_rather_than_zero(db):
    """The distinction this whole file turns on.

    ``0 stale`` asserts that everything is fresh. ``None`` says the system cannot tell,
    which is the truth: a freshness threshold needs a provider's documented update cadence
    and there is no provider.
    """
    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert result.stale_assignment_count is None
    assert result.stale_assignment_count != 0
    assert "No freshness rule exists" in result.stale_rule_description


def test_there_is_no_worker_heartbeat_until_a_worker_runs(db):
    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert result.worker is None


def test_a_heartbeat_appears_only_after_a_worker_actually_ran(db):
    from app.workers import integration_worker

    integration_worker.run_once(
        db, worker_name="w1", registry=AdapterRegistry({}), clock=clock_at(), jitter=lambda: 0.0
    )
    db.commit()

    result = health.build_health(
        db, registry=AdapterRegistry({}), clock=clock_at(BASE_TIME + timedelta(minutes=5))
    )

    assert result.worker is not None
    assert result.worker.worker_name == "w1"
    assert result.worker.seconds_since_last_seen == 300


def test_a_connection_row_without_an_adapter_still_reports_not_configured(db):
    """A row exists but nothing can serve it, so no capability may be claimed."""
    db.add(
        IntegrationConnection(
            provider_key="some-provider",
            connection_key="acct-1",
            state=IntegrationConnectionState.CONNECTED,
            is_enabled=True,
        )
    )
    db.commit()

    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert result.connections[0].state == IntegrationConnectionState.NOT_CONFIGURED


def test_a_disabled_connection_reports_disabled(db):
    adapter = FakeProviderAdapter()
    db.add(
        IntegrationConnection(
            provider_key="fake",
            connection_key="acct-1",
            state=IntegrationConnectionState.CONNECTED,
            is_enabled=False,
        )
    )
    db.commit()

    result = health.build_health(db, registry=AdapterRegistry({"fake": adapter}), clock=clock_at())

    assert result.connections[0].state == IntegrationConnectionState.DISABLED


# --- Counts -----------------------------------------------------------------


def test_job_counts_reflect_the_queue(db):
    enqueue(db, dedupe_key="a")
    failed = enqueue(db, dedupe_key="b")
    failed.attempt_count = 99
    jobs.mark_failed(
        db,
        failed,
        kind=ProviderErrorKind.PERMANENT,
        summary="settled",
        clock=clock_at(),
        jitter=lambda: 0.0,
    )
    db.commit()

    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert result.jobs_pending == 1
    assert result.jobs_failed_terminal == 1
    assert result.jobs_requiring_review == 1


def test_the_oldest_pending_age_is_reported(db):
    enqueue(db, dedupe_key="a")

    result = health.build_health(
        db, registry=AdapterRegistry({}), clock=clock_at(BASE_TIME + timedelta(hours=2))
    )

    assert result.oldest_pending_job_age_seconds == 7200


def test_the_oldest_pending_age_is_none_when_the_queue_is_empty(db):
    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert result.oldest_pending_job_age_seconds is None


def test_inbox_awaiting_verification_is_reported(db):
    from app.services import integration_inbox_service as inbox
    from tests.fakes.fake_provider_adapter import make_payload, unsigned_headers

    adapter = FakeProviderAdapter(verifies_signatures=False)
    inbox.accept_delivery(
        db,
        adapter=adapter,
        body=make_payload(),
        headers=unsigned_headers(),
        clock=clock_at(),
    )
    db.commit()

    result = health.build_health(db, registry=AdapterRegistry({}), clock=clock_at())

    assert result.inbox_awaiting_verification == 1


# --- Permissions ------------------------------------------------------------


def test_health_requires_a_session(client):
    assert client.get(HEALTH).status_code == 401


@pytest.mark.parametrize("role", [Role.ADMIN, Role.READ_ONLY_MANAGER])
def test_roles_with_integration_read_can_see_health(api_for, role):
    assert api_for(role).get(HEALTH).status_code == 200


@pytest.mark.parametrize("role", [Role.OPERATIONS, Role.MARKETING])
def test_roles_without_integration_read_are_refused(api_for, role):
    """Marketing in particular must never approach provider configuration
    (CRM.md section 11)."""
    response = api_for(role).get(HEALTH)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_only_an_admin_can_retry_a_failed_job(db, api_for):
    job = enqueue(db, dedupe_key="a")
    job.attempt_count = 99
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.RETRYABLE,
        summary="timeout",
        clock=clock_at(),
        jitter=lambda: 0.0,
    )
    db.commit()

    assert api_for(Role.READ_ONLY_MANAGER).post(f"{JOBS}/{job.id}/retry").status_code == 403
    assert api_for(Role.OPERATIONS).post(f"{JOBS}/{job.id}/retry").status_code == 403
    assert api_for(Role.ADMIN).post(f"{JOBS}/{job.id}/retry").status_code == 200


def test_a_read_only_manager_cannot_disable_a_connection(db, api_for):
    response = api_for(Role.READ_ONLY_MANAGER).post(
        "/api/v1/integrations/connections/1/disable", json={"reason": "testing"}
    )

    assert response.status_code == 403


# --- The endpoint -----------------------------------------------------------


def test_the_health_endpoint_reports_the_honest_picture(db, as_admin):
    response = as_admin.get(HEALTH)

    assert response.status_code == 200
    body = response.json()
    assert body["any_provider_configured"] is False
    assert body["connections"][0]["state"] == "not_configured"
    assert body["connections"][0]["provider_key"] is None
    assert body["stale_assignment_count"] is None
    assert body["worker"] is None
    assert "No provider account is connected" in body["summary"]


def test_the_health_endpoint_never_claims_a_connection(db, as_admin):
    """No value in the payload may read as "connected" while nothing is."""
    text = as_admin.get(HEALTH).text.lower()

    assert "connected_api" not in text
    assert '"state": "connected"' not in text
    assert "synchronized" not in text
    assert "last_successful_sync" not in text


def test_the_review_queue_can_be_listed(db, as_admin):
    healthy = enqueue(db, dedupe_key="a")
    broken = enqueue(db, dedupe_key="b")
    broken.attempt_count = 99
    jobs.mark_failed(
        db,
        broken,
        kind=ProviderErrorKind.MAPPING,
        summary="nothing maps",
        clock=clock_at(),
        jitter=lambda: 0.0,
    )
    db.commit()

    response = as_admin.get(JOBS, params={"review_only": True})

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [broken.id]
    assert healthy.id not in ids


def test_retrying_a_job_through_the_api_is_audited(db, as_admin, users):
    from app.models import AuditEvent

    job = enqueue(db, dedupe_key="a")
    job.attempt_count = 99
    jobs.mark_failed(
        db,
        job,
        kind=ProviderErrorKind.RETRYABLE,
        summary="timeout",
        clock=clock_at(),
        jitter=lambda: 0.0,
    )
    db.commit()

    response = as_admin.post(f"{JOBS}/{job.id}/retry")

    assert response.status_code == 200
    assert response.json()["status"] == IntegrationJobStatus.PENDING
    assert response.json()["manual_retry_count"] == 1
    # The history survives the retry.
    assert response.json()["attempt_count"] == 99

    entry = db.query(AuditEvent).filter(AuditEvent.action == "integration.job_retry").one_or_none()
    assert entry is not None


def test_retrying_a_healthy_job_is_refused(db, as_admin):
    job = enqueue(db, dedupe_key="a")

    response = as_admin.post(f"{JOBS}/{job.id}/retry")

    assert response.status_code == 409


def test_disabling_a_connection_that_does_not_exist_is_a_404(db, as_admin):
    """The truthful answer with nothing configured.

    The Settings panel renders no Disable button in this state rather than offering one
    that cannot do anything.
    """
    response = as_admin.post(
        "/api/v1/integrations/connections/1/disable", json={"reason": "testing"}
    )

    assert response.status_code == 404


def test_disabling_a_connection_touches_no_shipment_data(db, as_admin):
    """Safe by construction: it stops the integration and rewrites no history."""
    from tests.integration_fixtures import tracked_shipment

    tracked = tracked_shipment(db)
    before_state = tracked.shipment.operational_state
    connection = IntegrationConnection(
        provider_key="fake",
        connection_key="acct-1",
        state=IntegrationConnectionState.CONNECTED,
        is_enabled=True,
    )
    db.add(connection)
    db.commit()

    response = as_admin.post(
        f"/api/v1/integrations/connections/{connection.id}/disable",
        json={"reason": "pausing while we investigate"},
    )

    assert response.status_code == 200
    db.refresh(connection)
    assert connection.is_enabled is False
    assert connection.state == IntegrationConnectionState.DISABLED

    db.refresh(tracked.shipment)
    db.refresh(tracked.assignment)
    assert tracked.shipment.operational_state == before_state
    assert tracked.assignment.is_active is True


def test_there_is_no_connect_or_verify_endpoint():
    """A button that cannot perform a real operation is worse than no button.

    Matched on the trailing path *segment* rather than as a substring: the disable action
    lives under ``/integrations/connections/{id}/`` and would trip a loose ``"connect" in
    path`` check while being exactly the sort of endpoint that should exist.
    """
    from tests.test_public_boundary import walk_api_routes

    actions = {path.rsplit("/", 1)[-1] for path, _route in walk_api_routes()}

    assert "connect" not in actions
    assert "verify" not in actions
    assert "authorize" not in actions
    assert "test-connection" not in actions
    # And the actions that do exist are the two that can genuinely do something.
    assert "retry" in actions
    assert "disable" in actions
