"""The durable webhook inbox.

CRM.md section 9 asks for: *persist incoming events durably, enqueue processing, and
acknowledge promptly after durable acceptance.* This module is the durable acceptance.
Nothing here applies a business effect; it stores what arrived, decides whether it has
been seen before, records what can be said about its authenticity, and queues the work.

**Three axes, kept independent.** This is the part that is easy to get wrong by
collapsing them together:

* **Deduplication** asks *have we seen this event?* It runs on an unverified payload,
  because a forged replay of a genuine event must still be recognized as a replay.
* **Authenticity** asks *did the provider send this?* A failure here means the payload is
  stored and never applied -- not that it is discarded, because a forged delivery is
  exactly the thing an operator may later want to look at.
* **Processing** asks *what should happen now?* It runs later, in a worker, and only for
  an item whose authenticity permits it.

**What is never stored.** No authorization header, no API key, no cookie, no signature
value, no complete request header set. ``redaction.safe_headers`` keeps an allowlist of
four diagnostic headers and drops everything else rather than masking it, because a masked
entry still records that a particular header was present and that has no use worth the
risk.

**Bounded, and refused rather than truncated.** A body over
``INTEGRATION_WEBHOOK_MAX_BYTES`` is stored as a digest with no body at all. Truncating
would leave a payload that parses into something the provider did not send, which is worse
than having nothing: the digest still lets a redelivery be recognized.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import (
    InboxProcessingState,
    IntegrationJobType,
    WebhookVerificationState,
)
from app.core.time_utils import utcnow
from app.integrations.adapter import ProviderAdapter
from app.integrations.redaction import payload_digest, safe_summary
from app.models import IntegrationWebhookInboxItem
from app.models.integration import UNASSIGNED_CONNECTION
from app.services import integration_job_service

Clock = Callable[[], datetime]

DEDUPE_BASIS_EVENT_ID = "provider_event_id"
DEDUPE_BASIS_FINGERPRINT = "payload_fingerprint"


@dataclass(frozen=True)
class AcceptanceResult:
    """What happened to a delivery.

    ``is_duplicate`` is the interesting field. A duplicate is a **successful**
    acknowledgement: the provider is told the event was received, because it was, the
    first time. What it must not do is produce a second timeline entry, a second delivered
    count, a second shipment-state change, a second revenue figure, a second follow-up
    task, or an audit action implying a separate business event -- and it does not, because
    it creates no new job and no new normalized event.
    """

    item: IntegrationWebhookInboxItem
    is_duplicate: bool
    is_rejected: bool
    enqueued_job_id: int | None = None


class WebhookRejected(Exception):
    """A delivery refused on arrival. Carries a stable code, never the payload."""

    def __init__(self, code: str, summary: str) -> None:
        super().__init__(f"{code}: {summary}")
        self.code = code
        self.summary = summary


def _now(clock: Clock | None) -> datetime:
    return clock() if clock else utcnow()


def fallback_fingerprint(*parts: object) -> str:
    """A stable digest over the fields that identify an event when no id is supplied.

    The caller chooses the parts, because only an adapter knows which fields a given
    provider rewrites between deliveries. A fingerprint that included a delivery attempt
    counter, a retry number, or the delivery timestamp would change on every redelivery
    and defeat the entire mechanism -- so the adapter is asked for the *immutable* fields
    and this only hashes them.

    The separator matters: without it, ``("ab", "c")`` and ``("a", "bc")`` would hash
    alike, and two different events would silently become one.
    """
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _check_bounds(body: bytes, content_type: str | None) -> None:
    """Content-type and size limits, applied before anything is parsed."""
    allowed = settings.integration_webhook_content_type_list
    media_type = (content_type or "").split(";")[0].strip().lower()
    if allowed and media_type not in allowed:
        raise WebhookRejected(
            "content_type_not_allowed",
            f"declared content type {media_type or 'none'} is not accepted",
        )
    if len(body) > settings.integration_webhook_max_bytes:
        raise WebhookRejected(
            "payload_too_large",
            f"body of {len(body)} bytes exceeds the configured limit",
        )


def accept_delivery(
    db: Session,
    *,
    adapter: ProviderAdapter,
    body: bytes,
    headers: dict[str, str] | None = None,
    connection_key: str = UNASSIGNED_CONNECTION,
    connection_id: int | None = None,
    clock: Clock | None = None,
) -> AcceptanceResult:
    """Store one delivery durably, deduplicate it, judge it, and queue the work.

    The order is the design:

    1. **Bound it.** Size and content type, before the body is looked at.
    2. **Identify it**, from the unverified payload. Replay detection does not depend on
       authenticity, and must not: a forged replay is still a replay.
    3. **Store it**, with a database-enforced unique key. A concurrent duplicate loses at
       flush and becomes an idempotent acknowledgement of the winner.
    4. **Judge authenticity**, and record the verdict as its own field.
    5. **Queue** -- processing when the payload is verified, an authenticated read when it
       is merely an unsigned notification, and nothing at all when it is forged.

    Note what step 5 does *not* do for an unsigned notification: it does not create a
    normalized event, and it does not touch a shipment. It enqueues a question to the
    provider (CRM.md section 9).
    """
    now = _now(clock)
    capabilities = adapter.capabilities()
    supplied_headers = headers or {}

    try:
        _check_bounds(body, supplied_headers.get("content-type"))
    except WebhookRejected as rejection:
        item = _store_rejected(
            db,
            capabilities=capabilities,
            body=body,
            content_type=supplied_headers.get("content-type"),
            connection_key=connection_key,
            connection_id=connection_id,
            rejection=rejection,
            now=now,
        )
        return AcceptanceResult(item=item, is_duplicate=False, is_rejected=True)

    # Identity is extracted from an unverified payload deliberately. A malformed body is
    # a rejection, not an exception that loses the delivery.
    try:
        identity = adapter.extract_identity(body=body, headers=supplied_headers)
    except Exception as error:  # noqa: BLE001 - any parse failure is one outcome
        rejection = WebhookRejected("unparseable_payload", type(error).__name__)
        item = _store_rejected(
            db,
            capabilities=capabilities,
            body=body,
            content_type=supplied_headers.get("content-type"),
            connection_key=connection_key,
            connection_id=connection_id,
            rejection=rejection,
            now=now,
        )
        return AcceptanceResult(item=item, is_duplicate=False, is_rejected=True)

    dedupe_key = identity.event_id or identity.fingerprint
    dedupe_basis = DEDUPE_BASIS_EVENT_ID if identity.event_id else DEDUPE_BASIS_FINGERPRINT

    existing = db.scalar(
        select(IntegrationWebhookInboxItem).where(
            IntegrationWebhookInboxItem.provider_key == capabilities.provider_key,
            IntegrationWebhookInboxItem.connection_key == connection_key,
            IntegrationWebhookInboxItem.dedupe_key == dedupe_key,
        )
    )
    if existing is not None:
        return AcceptanceResult(item=existing, is_duplicate=True, is_rejected=False)

    item = IntegrationWebhookInboxItem(
        provider_key=capabilities.provider_key,
        provider_api_version=capabilities.provider_api_version,
        connection_key=connection_key,
        connection_id=connection_id,
        received_at=now,
        content_type=supplied_headers.get("content-type"),
        payload_bytes=len(body),
        payload_text=body.decode("utf-8", errors="replace"),
        payload_omitted=False,
        payload_sha256=payload_digest(body),
        provider_event_id=identity.event_id,
        payload_fingerprint=identity.fingerprint,
        dedupe_key=dedupe_key,
        dedupe_basis=dedupe_basis,
        verification_state=WebhookVerificationState.PENDING,
        processing_state=InboxProcessingState.PENDING,
        attempt_count=0,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent session inserted the same event first. The unique constraint is
        # what makes "one inbox record and one downstream effect" true under concurrency,
        # rather than the check above, which only makes the common case cheap.
        db.rollback()
        winner = db.scalar(
            select(IntegrationWebhookInboxItem).where(
                IntegrationWebhookInboxItem.provider_key == capabilities.provider_key,
                IntegrationWebhookInboxItem.connection_key == connection_key,
                IntegrationWebhookInboxItem.dedupe_key == dedupe_key,
            )
        )
        return AcceptanceResult(item=winner, is_duplicate=True, is_rejected=False)

    verified_state, detail = _judge_authenticity(
        adapter, capabilities=capabilities, body=body, headers=supplied_headers
    )
    item.verification_state = verified_state
    item.verification_detail = safe_summary(detail)
    if verified_state in {
        WebhookVerificationState.SIGNATURE_VALID,
        WebhookVerificationState.VERIFIED_BY_READ,
    }:
        item.verified_at = now

    job_id: int | None = None

    if verified_state in {
        WebhookVerificationState.SIGNATURE_MISSING,
        WebhookVerificationState.SIGNATURE_INVALID,
    }:
        # Forged, or claiming an authenticity it cannot demonstrate. Stored for review,
        # never applied, and never retried: no number of attempts turns an invalid
        # signature into a valid one, and a forged event that could be retried would be a
        # way of keeping the queue busy.
        item.processing_state = InboxProcessingState.REJECTED
        item.rejected_at = now
        item.error_code = "authentication"
        item.error_summary = safe_summary(detail)
    elif verified_state is WebhookVerificationState.UNSIGNED_UNTRUSTED:
        # The provider offers no signature this adapter can check. The notification is a
        # hint that something changed, nothing more. The only thing it may cause is an
        # authenticated question to the provider (CRM.md section 9).
        job = integration_job_service.enqueue(
            db,
            job_type=IntegrationJobType.VERIFY_NOTIFICATION,
            provider_key=capabilities.provider_key,
            connection_key=connection_key,
            connection_id=connection_id,
            inbox_item_id=item.id,
            dedupe_key=integration_job_service.verification_dedupe_key(item.id),
            priority=50,
            clock=clock,
        )
        job_id = job.id if job else None
    else:
        job = integration_job_service.enqueue(
            db,
            job_type=IntegrationJobType.PROCESS_WEBHOOK_INBOX_ITEM,
            provider_key=capabilities.provider_key,
            connection_key=connection_key,
            connection_id=connection_id,
            inbox_item_id=item.id,
            dedupe_key=integration_job_service.inbox_dedupe_key(item.id),
            priority=10,
            clock=clock,
        )
        job_id = job.id if job else None

    db.flush()
    return AcceptanceResult(
        item=item, is_duplicate=False, is_rejected=False, enqueued_job_id=job_id
    )


def _judge_authenticity(
    adapter: ProviderAdapter,
    *,
    capabilities,
    body: bytes,
    headers: dict[str, str],
) -> tuple[str, str]:
    """Decide what can honestly be said about where this payload came from.

    An adapter that does **not** declare ``verifies_signatures`` is never asked to verify.
    That is not a shortcut: asking a signature-less adapter to verify would produce an
    answer of some kind, and any answer would be a claim the provider does not support.
    Recording ``unsigned_untrusted`` instead states the actual situation, and the
    consequence -- no direct mutation, verification read only -- follows from it.
    """
    if not capabilities.verifies_signatures:
        return (
            WebhookVerificationState.UNSIGNED_UNTRUSTED,
            "provider supplies no verifiable signature",
        )

    try:
        verified, reason = adapter.verify_webhook(body=body, headers=headers)
    except Exception as error:  # noqa: BLE001 - a verifier that throws has not verified
        return WebhookVerificationState.SIGNATURE_INVALID, type(error).__name__

    if verified:
        return WebhookVerificationState.SIGNATURE_VALID, reason or "signature verified"
    if reason == "signature_missing":
        return WebhookVerificationState.SIGNATURE_MISSING, "no signature was supplied"
    return WebhookVerificationState.SIGNATURE_INVALID, reason or "signature did not verify"


def _store_rejected(
    db: Session,
    *,
    capabilities,
    body: bytes,
    content_type: str | None,
    connection_key: str,
    connection_id: int | None,
    rejection: WebhookRejected,
    now: datetime,
) -> IntegrationWebhookInboxItem:
    """Store a refused delivery as a digest, without its body.

    Deliberately not silent. Refusing a delivery and forgetting it means an operator
    investigating "the provider says it sent us this" has nothing to look at, and a
    provider retrying an oversized payload forever leaves no evidence of why.

    The digest is over the exact bytes received, so a redelivery of the same oversized
    payload is recognized rather than stored again. The body itself is not kept: the
    reason it was refused is that it is too big to keep.
    """
    digest = payload_digest(body)
    dedupe_key = f"rejected:{digest}"

    existing = db.scalar(
        select(IntegrationWebhookInboxItem).where(
            IntegrationWebhookInboxItem.provider_key == capabilities.provider_key,
            IntegrationWebhookInboxItem.connection_key == connection_key,
            IntegrationWebhookInboxItem.dedupe_key == dedupe_key,
        )
    )
    if existing is not None:
        return existing

    item = IntegrationWebhookInboxItem(
        provider_key=capabilities.provider_key,
        provider_api_version=capabilities.provider_api_version,
        connection_key=connection_key,
        connection_id=connection_id,
        received_at=now,
        content_type=content_type,
        payload_bytes=len(body),
        payload_text=None,
        payload_omitted=True,
        payload_sha256=digest,
        provider_event_id=None,
        payload_fingerprint=digest,
        dedupe_key=dedupe_key,
        dedupe_basis=DEDUPE_BASIS_FINGERPRINT,
        verification_state=WebhookVerificationState.PENDING,
        processing_state=InboxProcessingState.REJECTED,
        rejected_at=now,
        error_code=rejection.code,
        error_summary=safe_summary(rejection.summary),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalar(
            select(IntegrationWebhookInboxItem).where(
                IntegrationWebhookInboxItem.provider_key == capabilities.provider_key,
                IntegrationWebhookInboxItem.connection_key == connection_key,
                IntegrationWebhookInboxItem.dedupe_key == dedupe_key,
            )
        )
    return item


# --- Worker-facing transitions ---------------------------------------------


def mark_processed(
    db: Session, item: IntegrationWebhookInboxItem, *, clock: Clock | None = None
) -> None:
    item.processing_state = InboxProcessingState.PROCESSED
    item.processed_at = _now(clock)
    item.error_code = None
    item.error_summary = None
    db.flush()


def mark_duplicate(
    db: Session, item: IntegrationWebhookInboxItem, *, clock: Clock | None = None
) -> None:
    """A delivery that turned out to describe an event already applied.

    Kept as a durable record with no business effect. Distinct from ``PROCESSED`` so an
    operator can tell "we acted on this" from "we recognized it and deliberately did
    nothing", which is the difference between a working integration and a stuck one.
    """
    item.processing_state = InboxProcessingState.DUPLICATE
    item.processed_at = _now(clock)
    db.flush()


def mark_failed(
    db: Session,
    item: IntegrationWebhookInboxItem,
    *,
    code: str,
    summary: str | None,
    terminal: bool,
    next_attempt_at: datetime | None = None,
    clock: Clock | None = None,
) -> None:
    now = _now(clock)
    item.attempt_count += 1
    item.error_code = code
    item.error_summary = safe_summary(summary)
    if terminal:
        item.processing_state = InboxProcessingState.FAILED_TERMINAL
        item.failed_at = now
        item.next_attempt_at = None
    else:
        item.processing_state = InboxProcessingState.FAILED
        item.next_attempt_at = next_attempt_at
    db.flush()


def mark_verified_by_read(
    db: Session, item: IntegrationWebhookInboxItem, *, clock: Clock | None = None
) -> None:
    """Promote an untrusted notification after an authenticated read confirmed it.

    The only route from ``unsigned_untrusted`` to something that may move a parcel, and
    it requires the provider to have answered an authenticated question -- not the
    notification to have been persuasive.
    """
    item.verification_state = WebhookVerificationState.VERIFIED_BY_READ
    item.verified_at = _now(clock)
    db.flush()


def awaiting_verification_count(db: Session) -> int:
    """Inbox items that cannot be applied until the provider is asked directly."""
    from sqlalchemy import func

    return (
        db.scalar(
            select(func.count())
            .select_from(IntegrationWebhookInboxItem)
            .where(
                IntegrationWebhookInboxItem.verification_state
                == WebhookVerificationState.UNSIGNED_UNTRUSTED,
                IntegrationWebhookInboxItem.processing_state.in_(
                    (InboxProcessingState.PENDING, InboxProcessingState.FAILED)
                ),
            )
        )
        or 0
    )


def counts_by_state(db: Session) -> dict[str, int]:
    from sqlalchemy import func

    rows = db.execute(
        select(IntegrationWebhookInboxItem.processing_state, func.count()).group_by(
            IntegrationWebhookInboxItem.processing_state
        )
    ).all()
    return dict(rows)
