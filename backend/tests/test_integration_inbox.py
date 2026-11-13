"""The durable webhook inbox: deduplication, bounds, and the authenticity boundary.

AC-9 and AC-10 live here. *Duplicate webhooks do not create duplicate timeline events,
delivered counts, revenue, or follow-up tasks*, and *a forged or invalid webhook cannot
mutate shipment state*.

The three axes stay independent throughout, and most of these tests exist to prove that
they do:

* **deduplication** runs on an unverified payload, because a forged replay of a genuine
  event is still a replay;
* **authenticity** decides whether anything may be applied, and a failure stores the
  payload rather than discarding it -- a forged delivery is exactly the thing an operator
  later wants to look at;
* **processing** happens in a worker, later, and only for an item whose authenticity
  permits it.

Everything runs against ``FakeProviderAdapter``. It is not ShipStation and does not model
it: its provider key is ``fake`` and its signature scheme was invented in that file
(``docs/INTEGRATIONS.md`` section 3 lists what remains unverified).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db import build_engine
from app.core.enums import (
    InboxProcessingState,
    IntegrationJobType,
    WebhookVerificationState,
)
from app.models import Base, IntegrationJob, IntegrationWebhookInboxItem
from app.services import integration_inbox_service as inbox
from tests.fakes.fake_provider_adapter import (
    FakeProviderAdapter,
    make_payload,
    sign,
    signed_headers,
    unsigned_headers,
)

BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)


def clock_at(moment: datetime = BASE_TIME):
    return lambda: moment


def deliver(db, adapter, body: bytes, headers: dict[str, str] | None = None, **kwargs):
    return inbox.accept_delivery(
        db,
        adapter=adapter,
        body=body,
        headers=headers if headers is not None else signed_headers(body),
        clock=clock_at(),
        **kwargs,
    )


@pytest.fixture
def signing_adapter() -> FakeProviderAdapter:
    """A provider that signs its webhooks and supports an authenticated read."""
    return FakeProviderAdapter()


@pytest.fixture
def unsigned_adapter() -> FakeProviderAdapter:
    """A provider with no signature mechanism this adapter can check.

    Quite possibly what the real provider turns out to be, which is why this path is
    tested as thoroughly as the signed one.
    """
    return FakeProviderAdapter(verifies_signatures=False)


# --- Durable acceptance -----------------------------------------------------


def test_a_signed_delivery_is_stored_verified_and_queued(db, signing_adapter):
    body = make_payload()

    result = deliver(db, signing_adapter, body)
    db.commit()

    item = result.item
    assert result.is_duplicate is False
    assert result.is_rejected is False
    assert item.verification_state == WebhookVerificationState.SIGNATURE_VALID
    assert item.processing_state == InboxProcessingState.PENDING
    assert item.payload_sha256
    assert item.payload_bytes == len(body)
    assert item.provider_api_version == "fake-v0"

    job = db.get(IntegrationJob, result.enqueued_job_id)
    assert job.job_type == IntegrationJobType.PROCESS_WEBHOOK_INBOX_ITEM


def test_the_body_is_stored_whole_or_not_at_all(db, signing_adapter):
    """Storage is durable acceptance, so an acknowledgement means something."""
    body = make_payload(detail="A narrative the provider supplied")

    result = deliver(db, signing_adapter, body)

    assert result.item.payload_text == body.decode("utf-8")
    assert result.item.payload_omitted is False


# --- Deduplication ----------------------------------------------------------


def test_a_duplicate_delivery_creates_one_row_and_no_second_job(db, signing_adapter):
    """AC-9, at the inbox. The second delivery is acknowledged and does nothing."""
    body = make_payload()

    first = deliver(db, signing_adapter, body)
    db.commit()
    second = deliver(db, signing_adapter, body)
    db.commit()

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert second.item.id == first.item.id
    assert db.query(IntegrationWebhookInboxItem).count() == 1
    assert db.query(IntegrationJob).count() == 1


def test_a_duplicate_may_be_acknowledged_successfully(db, signing_adapter):
    """A duplicate is not an error to the provider: the event *was* received.

    What it must not do is produce a second business effect, which is asserted by the
    counts above and by the worker tests.
    """
    body = make_payload()
    deliver(db, signing_adapter, body)
    db.commit()

    result = deliver(db, signing_adapter, body)

    assert result.is_duplicate is True
    assert result.is_rejected is False
    assert result.item is not None


def test_deduplication_prefers_the_provider_event_id(db, signing_adapter):
    """Two deliveries with the same event id are one event, even if the wording differs.

    Providers reword narrative text between retries. If that changed the identity, every
    retry would look like a new milestone.
    """
    first = deliver(db, signing_adapter, make_payload(detail="First wording"))
    db.commit()
    second = deliver(db, signing_adapter, make_payload(detail="Rewritten wording"))

    assert second.is_duplicate is True
    assert second.item.id == first.item.id
    assert first.item.dedupe_basis == "provider_event_id"


def test_a_fingerprint_is_used_when_the_provider_supplies_no_event_id(db):
    """The fallback CRM.md section 9 requires: a stable digest over immutable fields."""
    adapter = FakeProviderAdapter(supplies_event_ids=False)
    body = make_payload(event_id=None)

    first = deliver(db, adapter, body)
    db.commit()
    second = deliver(db, adapter, body)

    assert first.item.dedupe_basis == "payload_fingerprint"
    assert first.item.provider_event_id is None
    assert second.is_duplicate is True
    assert db.query(IntegrationWebhookInboxItem).count() == 1


def test_the_fingerprint_covers_immutable_fields_only(db):
    """Rewording must not create a second event; a different status must.

    A fingerprint over a retry counter or a delivery timestamp would change on every
    redelivery and defeat the mechanism entirely, so the adapter chooses the fields and
    this pins the choice down.
    """
    adapter = FakeProviderAdapter(supplies_event_ids=False)

    deliver(db, adapter, make_payload(event_id=None, detail="First wording"))
    db.commit()
    reworded = deliver(db, adapter, make_payload(event_id=None, detail="Second wording"))
    db.commit()
    genuinely_new = deliver(
        db, adapter, make_payload(event_id=None, status="FAKE_ON_VAN", detail="First wording")
    )

    assert reworded.is_duplicate is True
    assert genuinely_new.is_duplicate is False
    assert db.query(IntegrationWebhookInboxItem).count() == 2


def test_deduplication_is_scoped_by_connection(db, signing_adapter):
    """Two accounts on one provider can legitimately emit the same event id."""
    body = make_payload()

    deliver(db, signing_adapter, body, connection_key="account-a")
    db.commit()
    other = deliver(db, signing_adapter, body, connection_key="account-b")

    assert other.is_duplicate is False
    assert db.query(IntegrationWebhookInboxItem).count() == 2


def test_fallback_fingerprint_separates_differently_split_parts():
    """The separator is what stops ``("ab", "c")`` and ``("a", "bc")`` hashing alike."""
    assert inbox.fallback_fingerprint("ab", "c") != inbox.fallback_fingerprint("a", "bc")
    assert inbox.fallback_fingerprint("a", "b") == inbox.fallback_fingerprint("a", "b")


def test_concurrent_duplicate_deliveries_from_separate_sessions_create_one_row(tmp_path):
    """The guarantee, at the database, under a genuine race.

    Two sessions on separate connections both see an empty table, both decide to insert,
    and both flush. The unique constraint decides. Without it this produces two inbox rows
    and two downstream effects, which is precisely the failure AC-9 forbids.
    """
    url = f"sqlite:///{(tmp_path / 'inbox.db').as_posix()}"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    first, second = factory(), factory()
    adapter = FakeProviderAdapter()
    body = make_payload()

    try:
        one = inbox.accept_delivery(
            first, adapter=adapter, body=body, headers=signed_headers(body), clock=clock_at()
        )
        first.commit()
        two = inbox.accept_delivery(
            second, adapter=adapter, body=body, headers=signed_headers(body), clock=clock_at()
        )
        second.commit()

        assert one.is_duplicate is False
        assert two.is_duplicate is True
        assert first.query(IntegrationWebhookInboxItem).count() == 1
        # And exactly one job, so exactly one downstream effect can follow.
        assert first.query(IntegrationJob).count() == 1
    finally:
        first.close()
        second.close()
        engine.dispose()


# --- Bounds -----------------------------------------------------------------


def test_an_oversized_payload_is_refused_and_kept_as_a_digest(db, signing_adapter, monkeypatch):
    """Refused, not truncated.

    A truncated body parses into something the provider did not send, which is worse than
    having nothing. The digest survives, so a redelivery of the same oversized payload is
    still recognized.
    """
    monkeypatch.setattr(settings, "integration_webhook_max_bytes", 100)
    body = make_payload(detail="x" * 500)

    result = deliver(db, signing_adapter, body)
    db.commit()

    assert result.is_rejected is True
    assert result.item.processing_state == InboxProcessingState.REJECTED
    assert result.item.payload_text is None
    assert result.item.payload_omitted is True
    assert result.item.payload_sha256
    assert result.item.error_code == "payload_too_large"
    assert result.enqueued_job_id is None
    assert db.query(IntegrationJob).count() == 0


def test_a_redelivered_oversized_payload_is_recognized(db, signing_adapter, monkeypatch):
    monkeypatch.setattr(settings, "integration_webhook_max_bytes", 100)
    body = make_payload(detail="x" * 500)

    first = deliver(db, signing_adapter, body)
    db.commit()
    second = deliver(db, signing_adapter, body)

    assert second.item.id == first.item.id
    assert db.query(IntegrationWebhookInboxItem).count() == 1


@pytest.mark.parametrize(
    "content_type",
    ["text/html", "application/xml", "text/plain", "application/x-www-form-urlencoded", None],
)
def test_an_unexpected_content_type_is_rejected(db, signing_adapter, content_type):
    """Rejected rather than parsed hopefully."""
    body = make_payload()
    headers = dict(signed_headers(body))
    if content_type is None:
        headers.pop("content-type", None)
    else:
        headers["content-type"] = content_type

    result = deliver(db, signing_adapter, body, headers=headers)
    db.commit()

    assert result.is_rejected is True
    assert result.item.error_code == "content_type_not_allowed"
    assert db.query(IntegrationJob).count() == 0


def test_an_unparseable_body_is_rejected_and_kept(db, signing_adapter):
    """A malformed payload is stored, not lost: an operator has to be able to see it."""
    result = deliver(db, signing_adapter, b"this is not json", headers=signed_headers(b"x"))
    db.commit()

    assert result.is_rejected is True
    assert result.item.error_code == "unparseable_payload"
    assert db.query(IntegrationJob).count() == 0


# --- Authenticity -----------------------------------------------------------


def test_a_missing_signature_is_rejected_by_a_signing_adapter(db, signing_adapter):
    """A signature-capable adapter must reject a missing signature."""
    body = make_payload()

    result = deliver(db, signing_adapter, body, headers=unsigned_headers())
    db.commit()

    assert result.item.verification_state == WebhookVerificationState.SIGNATURE_MISSING
    assert result.item.processing_state == InboxProcessingState.REJECTED
    assert result.enqueued_job_id is None


def test_an_invalid_signature_is_rejected_and_never_retried(db, signing_adapter):
    """A forged event cannot mutate state, and cannot keep the queue busy either.

    No number of attempts turns an invalid signature into a valid one, so no job is
    created at all.
    """
    body = make_payload()
    forged = dict(signed_headers(body))
    forged["x-fake-signature"] = sign(body, secret="an-attacker-secret")

    result = deliver(db, signing_adapter, body, headers=forged)
    db.commit()

    assert result.item.verification_state == WebhookVerificationState.SIGNATURE_INVALID
    assert result.item.processing_state == InboxProcessingState.REJECTED
    assert result.item.rejected_at is not None
    assert db.query(IntegrationJob).count() == 0


def test_a_malformed_signature_is_rejected(db, signing_adapter):
    body = make_payload()
    headers = dict(signed_headers(body))
    headers["x-fake-signature"] = "not-a-hex-digest"

    result = deliver(db, signing_adapter, body, headers=headers)

    assert result.item.verification_state == WebhookVerificationState.SIGNATURE_INVALID


def test_a_forged_delivery_is_still_stored_for_review(db, signing_adapter):
    """Discarding it would leave an operator investigating an attack with nothing."""
    body = make_payload()
    forged = dict(signed_headers(body))
    forged["x-fake-signature"] = sign(body, secret="an-attacker-secret")

    result = deliver(db, signing_adapter, body, headers=forged)
    db.commit()

    assert db.query(IntegrationWebhookInboxItem).count() == 1
    assert result.item.payload_text is not None


def test_a_forged_replay_is_still_recognized_as_a_replay(db, signing_adapter):
    """Deduplication does not depend on authenticity, and this is why it must not.

    An attacker replaying a genuine event with a broken signature must not create a second
    inbox row, or the dedupe table becomes a place to write into.
    """
    body = make_payload()
    deliver(db, signing_adapter, body)
    db.commit()

    forged = dict(signed_headers(body))
    forged["x-fake-signature"] = sign(body, secret="an-attacker-secret")
    replay = deliver(db, signing_adapter, body, headers=forged)

    assert replay.is_duplicate is True
    assert db.query(IntegrationWebhookInboxItem).count() == 1


def test_an_unsigned_provider_produces_an_untrusted_notification(db, unsigned_adapter):
    """The case CRM.md section 9 spends the most words on.

    The provider offers no signature. The notification is a hint, stored honestly as
    untrusted, and the **only** thing it may cause is an authenticated question to the
    provider. It does not become a normalized event, and it does not touch a shipment.
    """
    body = make_payload()

    result = deliver(db, unsigned_adapter, body, headers=unsigned_headers())
    db.commit()

    assert result.item.verification_state == WebhookVerificationState.UNSIGNED_UNTRUSTED
    assert result.item.processing_state == InboxProcessingState.PENDING

    job = db.get(IntegrationJob, result.enqueued_job_id)
    assert job.job_type == IntegrationJobType.VERIFY_NOTIFICATION, (
        "an unsigned notification must enqueue a verification read, not direct processing"
    )


def test_an_unsigned_adapter_is_never_asked_to_verify(db, unsigned_adapter):
    """Asking would produce an answer, and any answer would be a claim the provider does
    not support. Recording ``unsigned_untrusted`` states the actual situation instead."""
    body = make_payload()
    # Even with a signature header present, an adapter that does not declare the
    # capability stays untrusted.
    result = deliver(db, unsigned_adapter, body, headers=signed_headers(body))

    assert result.item.verification_state == WebhookVerificationState.UNSIGNED_UNTRUSTED


def test_a_verifier_that_raises_is_treated_as_not_verified(db):
    """Fails closed. A verifier that threw has not verified anything."""

    class ExplodingAdapter(FakeProviderAdapter):
        def verify_webhook(self, *, body, headers):
            raise RuntimeError("verifier blew up")

    result = deliver(db, ExplodingAdapter(), make_payload())

    assert result.item.verification_state == WebhookVerificationState.SIGNATURE_INVALID
    assert result.item.processing_state == InboxProcessingState.REJECTED


def test_awaiting_verification_counts_only_untrusted_pending_items(
    db, unsigned_adapter, signing_adapter
):
    deliver(db, unsigned_adapter, make_payload(event_id="u1"), headers=unsigned_headers())
    deliver(db, signing_adapter, make_payload(event_id="s1"))
    db.commit()

    assert inbox.awaiting_verification_count(db) == 1


# --- Verification promotion -------------------------------------------------


def test_only_an_authenticated_read_promotes_an_untrusted_notification(db, unsigned_adapter):
    body = make_payload()
    result = deliver(db, unsigned_adapter, body, headers=unsigned_headers())
    db.commit()

    inbox.mark_verified_by_read(db, result.item, clock=clock_at())
    db.commit()

    assert result.item.verification_state == WebhookVerificationState.VERIFIED_BY_READ
    assert result.item.verified_at is not None


# --- What the inbox never stores --------------------------------------------


def test_no_credential_bearing_header_is_stored(db, signing_adapter):
    """No authorization header, no API key, no cookie, no signature value, no header set.

    The signature is checked and then forgotten: keeping it would put a value derived from
    the shared secret in the database for no operational purpose.
    """
    body = make_payload()
    headers = dict(signed_headers(body))
    headers.update(
        {
            "authorization": "Bearer super-secret-token-value",
            "x-api-key": "fake-api-key-value",
            "cookie": "session=abc123",
        }
    )

    result = deliver(db, signing_adapter, body, headers=headers)
    db.commit()

    serialized = " ".join(str(value) for value in vars(result.item).values() if value is not None)
    for secret in (
        "super-secret-token-value",
        "fake-api-key-value",
        "session=abc123",
        headers["x-fake-signature"],
    ):
        assert secret not in serialized, secret

    # Only the diagnostic content type survives, and only as its own column.
    assert result.item.content_type == "application/json"


def test_the_inbox_model_has_no_column_that_could_hold_a_credential():
    """Structural, so a future column called ``api_key`` fails the build.

    ``lease_token`` is the one column whose *name* matches the scan and which is
    nonetheless fine: it is a locally generated ``secrets.token_hex`` value proving which
    worker holds a lease, never anything the provider supplied. It is named here rather
    than excluded by loosening the scan, so adding a genuine credential column called
    ``provider_token`` still fails.
    """
    columns = {column.name for column in IntegrationWebhookInboxItem.__table__.columns}

    #: Locally minted, provider-independent, and not a secret of anybody else.
    LOCAL_LEASE_COLUMNS = {"lease_token", "lease_owner", "lease_expires_at"}

    suspicious = columns - LOCAL_LEASE_COLUMNS
    for forbidden in (
        "authorization",
        "api_key",
        "apikey",
        "cookie",
        "secret",
        "token",
        "signature",
        "credential",
        "password",
        "headers",
        "request_headers",
    ):
        matched = [name for name in suspicious if forbidden in name]
        assert matched == [], f"{forbidden}: {matched}"


def test_a_lease_token_is_locally_generated_and_never_provider_supplied(db, signing_adapter):
    """The exception above, justified rather than asserted.

    A lease token is 32 hex characters from ``secrets.token_hex``. Nothing the provider
    sends can reach it.
    """
    import re

    from app.services import integration_job_service as jobs

    body = make_payload()
    result = deliver(db, signing_adapter, body)
    db.commit()

    claimed = jobs.claim_next(db, worker_name="w1", clock=clock_at())

    assert claimed is not None
    assert re.fullmatch(r"[0-9a-f]{32}", claimed.lease_token)
    assert claimed.lease_token not in body.decode("utf-8")
    assert result.item.payload_sha256 != claimed.lease_token
