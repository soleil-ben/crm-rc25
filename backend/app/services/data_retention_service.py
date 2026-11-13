"""Retention-deletion machinery, disabled by default (RC-UAT-21 Phase D, DEC-0233).

The owner has not decided any retention period (OD-01 is open; OD-36 says do not implement
canonical deletion schedules until OD-01 is answered). This module is therefore **machinery
that does nothing** until the owner decides:

* a global switch (``data_retention_settings.enabled``), off; only an Admin turns it on, with
  the typed confirmation ``CONFIRMATION_PHRASE`` (audited ``data_retention.enable``);
* one policy per record class (``data_retention_policies``), each disabled with no period;
  a class can be enabled only while the global switch is on and a period is set;
* the worker ``python -m app.workers.retention_worker --once [--dry-run]``, never scheduled.
  A real run touches a class only when the switch is on **and** the class is enabled **and**
  it has a period; it works in bounded batches (one transaction each) and records a run row
  and an audit event (``data_retention.run``). A dry run changes nothing and reports the
  counts per class (``data_retention.dry_run``).

**Never reachable** (stand-in D-6): customer invoices and their lines, payments, payment
conversions, vendor bills, cost allocations, period closes, invoice drafts, audit events,
consent events and suppressions, customers, shipments and their history. They are simply not
record classes, so no policy row can name them; ``FORBIDDEN_TABLES`` is asserted by the tests.
Nothing is under legal hold yet; a hold would remove a record from every class (D-7).

Record classes (each a closed, non-financial set of rows):

* ``soft_deleted_quotes`` -- quote versions an Admin soft-deleted longer ago than the period,
  never referenced by any invoice draft or customer invoice (any status), never with an
  accepted offer (the customer's acceptance record) or an offer an invoice draft names:
  **delete** removes the version, its lines, its expiry row and its (declined, withdrawn or
  expired) offer; the soft-delete row stays (``purged_at``).
* ``closed_quote_offers`` -- declined, withdrawn or expired offers: **anonymise** clears the
  decline and withdrawal reasons and who answered; the offer and its frozen content stay.
* ``notification_outbox_processed`` -- milestone notifications sent, recorded or skipped:
  **delete** (no address or body is stored on them anyway).
* ``customer_auth_tokens_spent`` -- Customer Account verification and reset tokens consumed or
  expired before the period: **delete**. (Tokens already stop working when they expire,
  OD-36; this only removes the dead rows.)
* ``customer_sessions_ended`` / ``staff_sessions_ended`` -- sessions expired or revoked before
  the period: **delete**.
* ``customer_registration_attempts`` -- registration attempt records (rate limiting and
  idempotency): **delete**.
* ``tariff_intake_emails`` -- vendor rate emails taken in: **anonymise** clears the sender
  address and the subject; the stored ``.eml`` file on disk is not touched (D-8).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, union, update
from sqlalchemy.orm import Session

from app.core.time_utils import utcnow
from app.models import (
    CustomerAuthToken,
    CustomerInvoice,
    CustomerRegistrationAttempt,
    CustomerSession,
    DataRetentionPolicy,
    DataRetentionRun,
    DataRetentionSettings,
    InvoiceDraft,
    NotificationOutbox,
    QuoteExpiry,
    QuoteLine,
    QuoteOffer,
    QuoteVersion,
    QuoteVersionDeletion,
    TariffEmailIntake,
    User,
    UserSession,
)
from app.models.rc21_retention import RETENTION_ACTIONS
from app.services import audit_service
from app.services.errors import NotFoundError, ValidationError

#: What an Admin types to turn the global switch on.
CONFIRMATION_PHRASE = "ENABLE RETENTION"
#: Upper bounds on what an Admin may set.
PERIOD_MAX_DAYS = 36500
BATCH_MIN, BATCH_MAX = 1, 5000
MIN_AGE_MAX_DAYS = 3650
#: A run never takes more than this many batches per class; the rest waits for the next run.
MAX_BATCHES_PER_CLASS = 1000

#: Tables the retention machinery must never touch (asserted by the tests).
FORBIDDEN_TABLES = frozenset(
    {
        "customer_invoices",
        "customer_invoice_lines",
        "customer_payments",
        "payment_conversions",
        "vendor_invoices",
        "vendor_invoice_lines",
        "cost_allocations",
        "period_closes",
        "invoice_drafts",
        "invoice_draft_tax",
        "invoice_draft_tax_route",
        "audit_events",
        "consent_events",
        "contact_suppressions",
        "customers",
        "shipments",
        "shipment_events",
        "data_retention_runs",
    }
)


@dataclass(frozen=True)
class RecordClass:
    key: str
    label: str
    description: str
    #: The tables a run of this class changes.
    tables: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    #: ``eligible(cutoff)`` -> a ``select`` of the primary keys past the period.
    eligible: Callable[[datetime], Any]
    #: ``apply(db, ids, action, now)`` -> rows changed.
    apply: Callable[[Session, list[Any], str, datetime], int]


# --- Record classes ------------------------------------------------------------------------------


def _protected_versions():
    """Versions the purge never removes: any invoice draft or customer invoice (any status)
    names them, or their offer was accepted (the customer's acceptance record), or their
    offer is named by an invoice draft."""
    return union(
        select(InvoiceDraft.quote_version_id),
        select(CustomerInvoice.quote_version_id),
        select(QuoteOffer.quote_version_id).where(QuoteOffer.status == "accepted"),
        select(QuoteOffer.quote_version_id).where(
            QuoteOffer.id.in_(
                select(InvoiceDraft.offer_id).where(InvoiceDraft.offer_id.is_not(None))
            )
        ),
    )


def _soft_deleted_quotes(cutoff: datetime):
    return (
        select(QuoteVersionDeletion.id)
        .where(
            QuoteVersionDeletion.restored_at.is_(None),
            QuoteVersionDeletion.purged_at.is_(None),
            QuoteVersionDeletion.quote_version_id.is_not(None),
            QuoteVersionDeletion.deleted_at < cutoff,
            QuoteVersionDeletion.quote_version_id.not_in(_protected_versions()),
        )
        .order_by(QuoteVersionDeletion.id)
    )


def _purge_quotes(db: Session, ids: list[int], _action: str, now: datetime) -> int:
    count = 0
    protected = set(db.scalars(_protected_versions()))
    for row in db.scalars(select(QuoteVersionDeletion).where(QuoteVersionDeletion.id.in_(ids))):
        version_id = row.quote_version_id
        # Belt and braces: re-check inside the batch that nothing protects it.
        if version_id in protected:
            continue
        row.quote_version_id = None
        row.purged_at = now
        db.flush()
        db.execute(delete(QuoteExpiry).where(QuoteExpiry.quote_version_id == version_id))
        db.execute(delete(QuoteOffer).where(QuoteOffer.quote_version_id == version_id))
        db.execute(delete(QuoteLine).where(QuoteLine.version_id == version_id))
        db.execute(delete(QuoteVersion).where(QuoteVersion.id == version_id))
        count += 1
    return count


def _closed_offers(cutoff: datetime):
    return (
        select(QuoteOffer.id)
        .where(
            QuoteOffer.status.in_(("declined", "withdrawn", "expired")),
            QuoteOffer.updated_at < cutoff,
            or_(
                QuoteOffer.decline_reason.is_not(None),
                QuoteOffer.withdrawn_reason.is_not(None),
                QuoteOffer.responded_identity_id.is_not(None),
            ),
        )
        .order_by(QuoteOffer.id)
    )


def _anonymise_offers(db: Session, ids: list[int], _action: str, _now: datetime) -> int:
    result = db.execute(
        update(QuoteOffer)
        .where(QuoteOffer.id.in_(ids))
        .values(decline_reason=None, withdrawn_reason=None, responded_identity_id=None)
    )
    return result.rowcount or 0


def _outbox(cutoff: datetime):
    return (
        select(NotificationOutbox.id)
        .where(
            NotificationOutbox.status.in_(("sent", "recorded", "skipped")),
            func.coalesce(NotificationOutbox.processed_at, NotificationOutbox.created_at) < cutoff,
        )
        .order_by(NotificationOutbox.id)
    )


def _tokens(cutoff: datetime):
    return (
        select(CustomerAuthToken.id)
        .where(or_(CustomerAuthToken.consumed_at < cutoff, CustomerAuthToken.expires_at < cutoff))
        .order_by(CustomerAuthToken.id)
    )


def _customer_sessions(cutoff: datetime):
    return (
        select(CustomerSession.id)
        .where(or_(CustomerSession.revoked_at < cutoff, CustomerSession.expires_at < cutoff))
        .order_by(CustomerSession.id)
    )


def _staff_sessions(cutoff: datetime):
    return (
        select(UserSession.id)
        .where(or_(UserSession.revoked_at < cutoff, UserSession.expires_at < cutoff))
        .order_by(UserSession.id)
    )


def _registration_attempts(cutoff: datetime):
    return (
        select(CustomerRegistrationAttempt.id)
        .where(CustomerRegistrationAttempt.created_at < cutoff)
        .order_by(CustomerRegistrationAttempt.id)
    )


def _intakes(cutoff: datetime):
    return (
        select(TariffEmailIntake.id)
        .where(
            TariffEmailIntake.created_at < cutoff,
            or_(TariffEmailIntake.sender.is_not(None), TariffEmailIntake.subject.is_not(None)),
        )
        .order_by(TariffEmailIntake.id)
    )


def _anonymise_intakes(db: Session, ids: list[int], _action: str, _now: datetime) -> int:
    result = db.execute(
        update(TariffEmailIntake)
        .where(TariffEmailIntake.id.in_(ids))
        .values(sender=None, subject=None)
    )
    return result.rowcount or 0


def _deleter(model) -> Callable[[Session, list[Any], str, datetime], int]:
    def _apply(db: Session, ids: list[Any], _action: str, _now: datetime) -> int:
        result = db.execute(delete(model).where(model.id.in_(ids)))
        return result.rowcount or 0

    return _apply


RECORD_CLASSES: dict[str, RecordClass] = {
    c.key: c
    for c in (
        RecordClass(
            "soft_deleted_quotes",
            "Soft-deleted quotes",
            "Quote versions an Admin deleted; never one an invoice, a draft invoice or an "
            "accepted offer refers to.",
            ("quote_versions", "quote_lines", "quote_offers", "quote_expiries"),
            ("delete",),
            _soft_deleted_quotes,
            _purge_quotes,
        ),
        RecordClass(
            "closed_quote_offers",
            "Declined, withdrawn or expired quote offers",
            "Clears the decline and withdrawal reasons and who answered; the offer stays.",
            ("quote_offers",),
            ("anonymise",),
            _closed_offers,
            _anonymise_offers,
        ),
        RecordClass(
            "notification_outbox_processed",
            "Processed milestone notifications",
            "Outbox rows sent, recorded or skipped (no address or body is stored).",
            ("notification_outbox",),
            ("delete",),
            _outbox,
            _deleter(NotificationOutbox),
        ),
        RecordClass(
            "customer_auth_tokens_spent",
            "Used or expired account tokens",
            "Customer Account verification and reset tokens already used or expired.",
            ("customer_auth_tokens",),
            ("delete",),
            _tokens,
            _deleter(CustomerAuthToken),
        ),
        RecordClass(
            "customer_sessions_ended",
            "Ended Customer Account sessions",
            "Customer Account sign-in sessions expired or signed out.",
            ("customer_sessions",),
            ("delete",),
            _customer_sessions,
            _deleter(CustomerSession),
        ),
        RecordClass(
            "staff_sessions_ended",
            "Ended staff sessions",
            "Staff sign-in sessions expired or signed out.",
            ("user_sessions",),
            ("delete",),
            _staff_sessions,
            _deleter(UserSession),
        ),
        RecordClass(
            "customer_registration_attempts",
            "Account registration attempts",
            "Records of registration attempts kept for rate limiting and repeat detection.",
            ("customer_registration_attempts",),
            ("delete",),
            _registration_attempts,
            _deleter(CustomerRegistrationAttempt),
        ),
        RecordClass(
            "tariff_intake_emails",
            "Vendor rate emails taken in",
            "Clears the sender address and subject; the tariff and the stored file stay.",
            ("tariff_email_intakes",),
            ("anonymise",),
            _intakes,
            _anonymise_intakes,
        ),
    )
}


# --- Settings and policies -----------------------------------------------------------------------


def read_settings(db: Session) -> DataRetentionSettings:
    """The settings row; a transient all-off default when there is none (reading never
    writes: a database built with ``create_all`` has no seeded row)."""
    row = db.get(DataRetentionSettings, 1)
    if row is not None:
        return row
    return DataRetentionSettings(
        id=1, enabled=False, quote_delete_min_age_days=0, batch_size=200, updated_at=utcnow()
    )


def _settings_for_write(db: Session) -> DataRetentionSettings:
    row = db.get(DataRetentionSettings, 1)
    if row is None:
        row = DataRetentionSettings(
            id=1, enabled=False, quote_delete_min_age_days=0, batch_size=200, updated_at=utcnow()
        )
        db.add(row)
        db.flush()
    return row


def _default_policy(key: str) -> DataRetentionPolicy:
    return DataRetentionPolicy(
        record_class=key,
        enabled=False,
        period_days=None,
        action=RECORD_CLASSES[key].allowed_actions[0],
        updated_at=utcnow(),
    )


def read_policies(db: Session) -> list[DataRetentionPolicy]:
    """One policy per known record class, in the catalogue order. A missing row reads as the
    default (disabled, undecided). A row naming an unknown class is ignored."""
    rows = {p.record_class: p for p in db.scalars(select(DataRetentionPolicy))}
    return [rows.get(key) or _default_policy(key) for key in RECORD_CLASSES]


def _policy_for_write(db: Session, key: str) -> DataRetentionPolicy:
    if key not in RECORD_CLASSES:
        raise NotFoundError("That record class does not exist.")
    row = db.get(DataRetentionPolicy, key)
    if row is None:
        row = _default_policy(key)
        db.add(row)
        db.flush()
    return row


def _user_email(db: Session, user_id: int | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.email if user else None


def settings_view(db: Session) -> dict[str, Any]:
    row = read_settings(db)
    return {
        "enabled": row.enabled,
        "enabled_at": row.enabled_at,
        "enabled_by": _user_email(db, row.enabled_by_user_id),
        "quote_delete_min_age_days": row.quote_delete_min_age_days,
        "batch_size": row.batch_size,
        "confirmation_phrase": CONFIRMATION_PHRASE,
        "updated_at": row.updated_at,
        "updated_by": _user_email(db, row.updated_by_user_id),
    }


def policy_view(db: Session, row: DataRetentionPolicy) -> dict[str, Any]:
    spec = RECORD_CLASSES[row.record_class]
    return {
        "record_class": row.record_class,
        "label": spec.label,
        "description": spec.description,
        "enabled": row.enabled,
        "period_days": row.period_days,
        "action": row.action,
        "allowed_actions": list(spec.allowed_actions),
        "last_run_at": row.last_run_at,
        "last_run_affected": row.last_run_affected,
        "updated_at": row.updated_at,
        "updated_by": _user_email(db, row.updated_by_user_id),
    }


def run_view(row: DataRetentionRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "dry_run": row.dry_run,
        "trigger": row.trigger,
        "status": row.status,
        "counts": json.loads(row.counts_json or "{}"),
        "error": row.error,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def recent_runs(db: Session, limit: int = 10) -> list[DataRetentionRun]:
    return list(
        db.scalars(
            select(DataRetentionRun)
            .order_by(DataRetentionRun.started_at.desc(), DataRetentionRun.id.desc())
            .limit(limit)
        )
    )


def update_settings(
    db: Session, changes: dict[str, Any], *, actor: User | None, now: datetime | None = None
) -> DataRetentionSettings:
    """Admin changes the global switch, the soft-delete minimum age or the batch size. Turning
    the switch on needs ``confirmation == CONFIRMATION_PHRASE``. Turning it off disables every
    class too (nothing runs until each is enabled again). The caller commits."""
    now = now or utcnow()
    row = _settings_for_write(db)
    before = {
        "enabled": row.enabled,
        "quote_delete_min_age_days": row.quote_delete_min_age_days,
        "batch_size": row.batch_size,
    }
    if "quote_delete_min_age_days" in changes:
        value = changes["quote_delete_min_age_days"]
        if not isinstance(value, int) or not 0 <= value <= MIN_AGE_MAX_DAYS:
            raise ValidationError(
                f"The minimum age is a whole number of days from 0 to {MIN_AGE_MAX_DAYS}.",
                field="quote_delete_min_age_days",
            )
        row.quote_delete_min_age_days = value
    if "batch_size" in changes:
        value = changes["batch_size"]
        if not isinstance(value, int) or not BATCH_MIN <= value <= BATCH_MAX:
            raise ValidationError(
                f"The batch size is a whole number from {BATCH_MIN} to {BATCH_MAX}.",
                field="batch_size",
            )
        row.batch_size = value
    action = "data_retention.settings_update"
    if "enabled" in changes and changes["enabled"] is not None:
        wanted = bool(changes["enabled"])
        if wanted and not row.enabled:
            if (changes.get("confirmation") or "").strip() != CONFIRMATION_PHRASE:
                raise ValidationError(
                    f'Type "{CONFIRMATION_PHRASE}" to turn retention deletion on.',
                    field="confirmation",
                )
            row.enabled = True
            row.enabled_at = now
            row.enabled_by_user_id = actor.id if actor else None
            action = "data_retention.enable"
        elif not wanted and row.enabled:
            row.enabled = False
            row.enabled_at = None
            row.enabled_by_user_id = None
            for policy in db.scalars(
                select(DataRetentionPolicy).where(DataRetentionPolicy.enabled.is_(True))
            ):
                policy.enabled = False
                policy.updated_at = now
                policy.updated_by_user_id = actor.id if actor else None
            action = "data_retention.disable"
    row.updated_at = now
    row.updated_by_user_id = actor.id if actor else None
    after = {
        "enabled": row.enabled,
        "quote_delete_min_age_days": row.quote_delete_min_age_days,
        "batch_size": row.batch_size,
    }
    audit_service.record_audit(
        db,
        action=action,
        entity_type="data_retention_settings",
        entity_id=1,
        summary={
            "data_retention.enable": "Retention deletion turned on",
            "data_retention.disable": "Retention deletion turned off (every class disabled)",
        }.get(action, "Retention settings changed"),
        actor=actor,
        detail={"before": before, "after": after, "reason": changes.get("reason")},
    )
    return row


def update_policy(
    db: Session,
    key: str,
    changes: dict[str, Any],
    *,
    actor: User | None,
    now: datetime | None = None,
) -> DataRetentionPolicy:
    """Admin edits one class: period (days, or None for undecided), action, enabled. Enabling
    needs the global switch on and a period. The caller commits."""
    now = now or utcnow()
    row = _policy_for_write(db, key)
    spec = RECORD_CLASSES[key]
    before = {"enabled": row.enabled, "period_days": row.period_days, "action": row.action}
    if "period_days" in changes:
        value = changes["period_days"]
        if value is not None and (not isinstance(value, int) or not 1 <= value <= PERIOD_MAX_DAYS):
            raise ValidationError(
                f"The period is a whole number of days from 1 to {PERIOD_MAX_DAYS}, or empty "
                "(undecided).",
                field="period_days",
            )
        row.period_days = value
    if "action" in changes and changes["action"] is not None:
        value = changes["action"]
        if value not in RETENTION_ACTIONS or value not in spec.allowed_actions:
            raise ValidationError(
                f"This record class allows: {', '.join(spec.allowed_actions)}.", field="action"
            )
        row.action = value
    if "enabled" in changes and changes["enabled"] is not None:
        row.enabled = bool(changes["enabled"])
    if row.enabled:
        if not read_settings(db).enabled:
            raise ValidationError(
                "Turn retention deletion on (with the owner's approval) before enabling a "
                "record class.",
                field="enabled",
            )
        if row.period_days is None:
            raise ValidationError(
                "Set a retention period before enabling this record class.", field="period_days"
            )
    row.updated_at = now
    row.updated_by_user_id = actor.id if actor else None
    after = {"enabled": row.enabled, "period_days": row.period_days, "action": row.action}
    audit_service.record_audit(
        db,
        action="data_retention.policy_update",
        entity_type="data_retention_policy",
        entity_id=key,
        summary=f"Retention policy for {spec.label} changed",
        actor=actor,
        detail={"before": before, "after": after, "reason": changes.get("reason")},
    )
    return row


# --- Running -------------------------------------------------------------------------------------


def _count(db: Session, query) -> int:
    return db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0


def dry_run(
    db: Session, *, trigger: str, actor: User | None = None, now: datetime | None = None
) -> DataRetentionRun:
    """Count what a real run would change, per class; change nothing. Records a run row and
    ``data_retention.dry_run``. A class with no period reports ``eligible: None``. The caller
    commits."""
    now = now or utcnow()
    settings = read_settings(db)
    counts: dict[str, Any] = {}
    for policy in read_policies(db):
        spec = RECORD_CLASSES[policy.record_class]
        eligible = (
            _count(db, spec.eligible(now - timedelta(days=policy.period_days)))
            if policy.period_days is not None
            else None
        )
        counts[spec.key] = {
            "action": policy.action,
            "period_days": policy.period_days,
            "enabled": policy.enabled,
            "would_run": bool(settings.enabled and policy.enabled and policy.period_days),
            "eligible": eligible,
            "affected": 0,
        }
    run = DataRetentionRun(
        dry_run=True,
        trigger=trigger,
        actor_user_id=actor.id if actor else None,
        status="completed",
        counts_json=json.dumps(counts),
        started_at=now,
        finished_at=utcnow(),
    )
    db.add(run)
    db.flush()
    audit_service.record_audit(
        db,
        action="data_retention.dry_run",
        entity_type="data_retention_run",
        entity_id=run.id,
        summary="Retention dry run (nothing changed)",
        actor=actor,
        actor_label=None if actor else f"worker:{trigger}",
        detail={"counts": {k: v["eligible"] for k, v in counts.items()}},
    )
    return run


def run(
    db: Session,
    *,
    trigger: str = "worker",
    batch_size: int | None = None,
    now: datetime | None = None,
) -> DataRetentionRun | None:
    """A real run. Returns None, having done nothing at all, while the global switch is off.

    Otherwise each enabled class with a period is worked in batches of ``batch_size`` rows,
    one committed transaction per batch, at most ``MAX_BATCHES_PER_CLASS`` batches. The run
    row and ``data_retention.run`` are committed at the end; a failure rolls back the open
    batch only and is recorded (``status = failed``) with a bounded message.
    """
    now = now or utcnow()
    settings = read_settings(db)
    if not settings.enabled:
        db.rollback()
        return None
    size = batch_size or settings.batch_size
    started = now
    counts: dict[str, Any] = {}
    error: str | None = None
    for policy in read_policies(db):
        spec = RECORD_CLASSES[policy.record_class]
        if not (policy.enabled and policy.period_days):
            counts[spec.key] = {"ran": False, "affected": 0, "action": policy.action}
            continue
        cutoff = now - timedelta(days=policy.period_days)
        affected = 0
        try:
            for _ in range(MAX_BATCHES_PER_CLASS):
                ids = list(db.scalars(spec.eligible(cutoff).limit(size)))
                if not ids:
                    break
                changed = spec.apply(db, ids, policy.action, now)
                affected += changed
                db.commit()
                if len(ids) < size or changed == 0:
                    break
        except Exception as exc:  # noqa: BLE001 - recorded, bounded, then the run stops
            db.rollback()
            error = f"{spec.key}: {type(exc).__name__}"[:300]
            counts[spec.key] = {"ran": True, "affected": affected, "action": policy.action}
            break
        stored = db.get(DataRetentionPolicy, spec.key)
        if stored is not None:
            stored.last_run_at = now
            stored.last_run_affected = affected
        counts[spec.key] = {"ran": True, "affected": affected, "action": policy.action}
        db.commit()
    run_row = DataRetentionRun(
        dry_run=False,
        trigger=trigger,
        status="failed" if error else "completed",
        counts_json=json.dumps(counts),
        error=error,
        started_at=started,
        finished_at=utcnow(),
    )
    db.add(run_row)
    db.flush()
    audit_service.record_audit(
        db,
        action="data_retention.run",
        entity_type="data_retention_run",
        entity_id=run_row.id,
        summary=(
            "Retention run: "
            + ", ".join(f"{k} {v['affected']}" for k, v in counts.items() if v["ran"])
            if any(v["ran"] for v in counts.values())
            else "Retention run: no record class enabled"
        ),
        actor_label=f"worker:{trigger}",
        detail={"counts": {k: v["affected"] for k, v in counts.items()}, "error": error},
    )
    db.commit()
    return run_row
