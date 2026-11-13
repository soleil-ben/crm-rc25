"""Approved public wording for shipment timeline updates.

Staff should not have to compose a customer-facing sentence under time pressure, and a
customer reading the tracking page in Vietnamese should not be handed English. Both
problems have the same fix: the event stores a **template key** rather than a sentence,
and each surface renders that key in the language its reader chose.

What this module owns
---------------------
* The catalogue itself, loaded once from ``app/content/public_update_templates.json``.
* Which templates an event type may use — a customs sentence on a delivery event would be
  worse than no sentence.
* Whether an event type publishes by default (DEC-0083).
* Rendering a key into one language.

What it deliberately does not own
---------------------------------
Free text. A template never replaces the ability to write a specific sentence; it just
means nobody has to write the ordinary ones. An event carries a template key *or* free
text, never both — see ``event_service`` for why that exclusivity is enforced rather
than merged.

Unverified wording
------------------
The Vietnamese in the catalogue has **not** been reviewed by a native speaker. It is the
same caveat the staff Vietnamese catalogue carries, and it matters more here, because
these sentences go to customers rather than to colleagues who can shrug at an awkward
phrase. Review is an open owner decision (DEC-0084); until it closes, a staff member who
wants to be certain can read the preview the form shows in both languages before sending.

Immutability
------------
A key's wording never changes. The event stores the key, so editing wording in place
would silently rewrite what a customer was told last week. New wording is a new key; the old
key moves to the catalogue's ``retired`` list, where it still renders for the events that
carry it and is never offered again. ``check_catalogue`` is called
at import time so a malformed or self-contradictory catalogue fails at startup rather
than at the moment a staff member tries to publish.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.enums import ShipmentEventType

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "content" / "public_update_templates.json"

#: The languages the public tracking page offers. A template missing either is a defect,
#: not a fallback opportunity: half a translation is how a customer gets English on a
#: Vietnamese page, which is the exact problem this module exists to solve.
REQUIRED_LANGUAGES = ("en", "vi")

DEFAULT_LANGUAGE = "en"


class CatalogueError(RuntimeError):
    """The template catalogue is malformed. Raised at import time, never at request time."""


def _load() -> dict[str, Any]:
    try:
        raw = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - packaging failure
        raise CatalogueError(f"Template catalogue is missing at {CATALOGUE_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogueError(f"Template catalogue is not valid JSON: {exc}") from exc
    check_catalogue(raw)
    return raw


def check_catalogue(raw: dict[str, Any]) -> None:
    """Fail loudly on a catalogue that cannot be trusted.

    Every check here is something that would otherwise surface as a staff member clicking
    publish and getting a 500, or worse, a customer seeing an empty milestone.
    """
    templates = raw.get("templates")
    event_types = raw.get("event_types")
    if not isinstance(templates, dict) or not isinstance(event_types, dict):
        raise CatalogueError("Catalogue needs both 'templates' and 'event_types' objects.")

    for key, entry in templates.items():
        text = (entry or {}).get("text")
        if not isinstance(text, dict):
            raise CatalogueError(f"Template '{key}' has no 'text' object.")
        for language in REQUIRED_LANGUAGES:
            value = text.get(language)
            if not isinstance(value, str) or not value.strip():
                raise CatalogueError(f"Template '{key}' is missing {language} wording.")

    known_event_types = {member.value for member in ShipmentEventType}
    for event_type, entry in event_types.items():
        if event_type not in known_event_types:
            raise CatalogueError(
                f"Catalogue names event type '{event_type}', which is not a ShipmentEventType."
            )
        if not isinstance((entry or {}).get("default_public"), bool):
            raise CatalogueError(f"Event type '{event_type}' needs a boolean 'default_public'.")
        keys = entry.get("templates")
        if not isinstance(keys, list):
            raise CatalogueError(f"Event type '{event_type}' needs a 'templates' list.")
        for key in keys:
            if key not in templates:
                raise CatalogueError(
                    f"Event type '{event_type}' references unknown template '{key}'."
                )

    # A retired key is kept so the events that already carry it still render what the
    # customer was told; it is never offered again (RC-UAT-25 item 5, Ben 2026-10-25).
    retired = raw.get("retired", [])
    if not isinstance(retired, list):
        raise CatalogueError("'retired' must be a list of template keys.")
    offered = {k for entry in event_types.values() for k in entry["templates"]}
    for key in retired:
        if key not in templates:
            raise CatalogueError(f"Retired template '{key}' is not in the catalogue.")
        if key in offered:
            raise CatalogueError(f"Retired template '{key}' is still offered by an event type.")

    orphans = set(templates) - offered - set(retired)
    if orphans:
        raise CatalogueError(
            "These templates belong to no event type and could never be chosen: "
            + ", ".join(sorted(orphans))
        )


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Any]:
    return _load()


def template_keys() -> set[str]:
    return set(catalogue()["templates"])


def keys_for_event_type(event_type: str) -> list[str]:
    """Templates offered for this event type, in catalogue order. Order is the UI's order."""
    entry = catalogue()["event_types"].get(str(event_type))
    return list(entry["templates"]) if entry else []


def publishes_by_default(event_type: str) -> bool:
    """Whether the publish box starts ticked for this event type (DEC-0083).

    False for the states where a canned sentence could tell a customer something staff do
    not yet know to be true. An event type absent from the catalogue — ``booked``, which
    the system writes itself — does not publish.
    """
    entry = catalogue()["event_types"].get(str(event_type))
    return bool(entry["default_public"]) if entry else False


def is_valid_for(key: str, event_type: str) -> bool:
    return key in keys_for_event_type(event_type)


def render(key: str, language: str = DEFAULT_LANGUAGE) -> str | None:
    """The approved sentence for ``key`` in ``language``.

    Returns ``None`` for an unknown key rather than raising: a historical event whose
    template was removed from the catalogue must not take the tracking page down. Callers
    that need to reject an unknown key validate it explicitly instead.
    """
    entry = catalogue()["templates"].get(key)
    if entry is None:
        return None
    text = entry["text"]
    return text.get(language) or text.get(DEFAULT_LANGUAGE)


def describe_for_staff() -> list[dict[str, Any]]:
    """The catalogue in the shape the staff UI needs to build its picker."""
    data = catalogue()
    return [
        {
            "event_type": event_type,
            "default_public": entry["default_public"],
            "templates": [
                {"key": key, "text": data["templates"][key]["text"]} for key in entry["templates"]
            ],
        }
        for event_type, entry in data["event_types"].items()
    ]


# Fail at import, not at the first staff member who tries to publish an update.
catalogue()
