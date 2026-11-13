"""Audit logging for material changes (CRM.md section 11)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time_utils import utcnow
from app.models import AuditEvent, ConsentEvent, User

# Keys whose values are never written to the audit log.
_REDACTED_KEYS = {
    "password",
    "password_hash",
    "new_password",
    "current_password",
    "api_key",
    "secret",
    "token",
    "session_token",
    "csrf_token",
    "authorization",
}

# Personal detail that does not need to be duplicated into the audit trail.
_PERSONAL_KEYS = {
    "email_entered",
    "email_normalized",
    "phone_entered",
    "phone_e164",
    "notes",
    "body",
}


def redact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if lowered in _REDACTED_KEYS:
            cleaned[key] = "[redacted]"
        elif lowered in _PERSONAL_KEYS:
            cleaned[key] = "[changed]" if value is not None else None
        elif isinstance(value, dict):
            cleaned[key] = redact(value)
        else:
            cleaned[key] = value
    return cleaned


def record_audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    summary: str,
    actor: User | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    actor_label: str | None = None,
) -> AuditEvent:
    """Append an audit entry. The caller owns the surrounding transaction.

    ``actor_label`` names an actor who is not a staff user: a customer acting through their
    own account, ``customer_account:CA-000001`` (UAT round 8). A staff ``actor`` always
    wins, and with neither the row says ``system``.
    """
    event = AuditEvent(
        occurred_at=utcnow(),
        actor_user_id=actor.id if actor else None,
        actor_label=actor.email if actor else (actor_label or "system"),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:400],
        detail_json=json.dumps(redact(detail), ensure_ascii=False) if detail else None,
        ip_address=ip_address,
    )
    db.add(event)
    return event


def list_audit_events(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    conditions = []
    if entity_type:
        conditions.append(AuditEvent.entity_type == entity_type)
    if entity_id:
        conditions.append(AuditEvent.entity_id == str(entity_id))
    if action:
        conditions.append(AuditEvent.action == action)

    total = db.scalar(select(func.count()).select_from(AuditEvent).where(*conditions)) or 0
    rows = db.scalars(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


# --- What the audit screen may show --------------------------------------------------

#: Detail keys that hold a list of *field names* -- what changed, never the values. The
#: writers use several spellings; each is listed rather than guessed at.
_FIELD_NAME_KEYS = (
    "changed_fields",
    "fields",
    "changed",
    "field_keys",
    "applied_field_keys",
    "differing_field_keys",
)

#: Detail keys that hold a machine reason *code*. A free-text ``reason`` is deliberately
#: absent: staff type it, so it can carry a name or an address.
_REASON_CODE_KEYS = ("reason_code", "override_reason_code")

#: A field name or reason code is a short snake_case token. Anything else is not a name,
#: so it is dropped rather than shown: the screen must never become a way to read a value.
_NAME_TOKEN = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


#: An evidence reference is a ticket, form or document reference: short, starting with a
#: letter or digit, and made of the characters such references use. Anything else -- an
#: address, a sentence -- is not shown (UAT round 5).
_EVIDENCE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-./#:]{0,79}$")


def _evidence_token(value: Any) -> str | None:
    if isinstance(value, str) and _EVIDENCE_TOKEN.match(value) and "@" not in value:
        return value
    return None


#: The longest old or new value the audit screen shows for one change.
_CHANGE_VALUE_MAX = 300


def _change_entries(value: Any) -> list[dict[str, str | None]]:
    """Old and new values from a ``changes`` list (UAT round 8).

    Written only by ``customer_service.update_customer`` for an approved Customer Account
    change request, and shown to roles holding ``audit:read``, who can read the same values
    on the customer record. Each entry must name its field with a field-name token and hold
    text or nothing on either side; anything else is dropped rather than shown.
    """
    if not isinstance(value, list):
        return []
    entries: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name, old, new = item.get("field"), item.get("old"), item.get("new")
        if not (isinstance(name, str) and _NAME_TOKEN.match(name)):
            continue
        if not all(side is None or isinstance(side, str) for side in (old, new)):
            continue
        entries.append(
            {
                "field": name,
                "old": old[:_CHANGE_VALUE_MAX] if old is not None else None,
                "new": new[:_CHANGE_VALUE_MAX] if new is not None else None,
            }
        )
    return entries


def _name_tokens(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, str) and _NAME_TOKEN.match(item)]


def audit_display_fields(detail_json: str | None) -> dict[str, Any]:
    """The reason code and changed field *names* an audit row carries, for display.

    Read from the stored detail, top level only. Values are never returned: a field list
    yields its names, a reason code must itself look like a code, and anything that does
    not fit those shapes is left out (UAT round 3: the audit screen showed only a
    one-line summary). ``admin_override`` is true when an Admin took a decision that is
    Operations' by default (UAT round 4, CA-APR-05). ``evidence_reference`` is the
    reference a suppression was recorded against, when it looks like one (UAT round 5).
    ``changes`` is the one exception to "names only": the old and new values an approved
    Customer Account change request applied (UAT round 8, ``_change_entries``).
    """
    empty: dict[str, Any] = {
        "reason_code": None,
        "changed_fields": [],
        "admin_override": False,
        "evidence_reference": None,
        "changes": [],
    }
    if not detail_json:
        return empty
    try:
        detail = json.loads(detail_json)
    except ValueError:
        return empty
    if not isinstance(detail, dict):
        return empty

    reason_code = None
    for key in _REASON_CODE_KEYS:
        value = detail.get(key)
        if isinstance(value, str) and _NAME_TOKEN.match(value):
            reason_code = value
            break

    names: list[str] = []
    for key in _FIELD_NAME_KEYS:
        for name in _name_tokens(detail.get(key)):
            if name not in names:
                names.append(name)
    # Only a literal ``true`` counts: the flag is written as a boolean by
    # ``customer_account_audit`` and anything else is not that writer's (CA-APR-05).
    admin_override = detail.get("admin_override") is True
    return {
        "reason_code": reason_code,
        "changed_fields": sorted(names),
        "admin_override": admin_override,
        "evidence_reference": _evidence_token(detail.get("evidence_reference")),
        "changes": _change_entries(detail.get("changes")),
    }


def suppression_evidence_fallback(db: Session, event: AuditEvent) -> str | None:
    """The evidence reference of a ``suppression.add`` row written before UAT round 5.

    Those rows carry ``consent_event_id`` and not the reference itself, so it is read from
    the consent event the row names, under the same shape check.
    """
    if event.action != "suppression.add" or not event.detail_json:
        return None
    try:
        detail = json.loads(event.detail_json)
    except ValueError:
        return None
    event_id = detail.get("consent_event_id") if isinstance(detail, dict) else None
    if not isinstance(event_id, int):
        return None

    consent = db.get(ConsentEvent, event_id)
    return _evidence_token(consent.evidence_reference) if consent is not None else None
