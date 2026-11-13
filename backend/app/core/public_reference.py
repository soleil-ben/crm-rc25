"""Public tracking reference normalization and strict validation.

The public lookup accepts exactly two things: a parent Solaris Shipment ID
(``SX-CAV-7K9D2M4R8T6W``) or one of its package references
(``SX-CAV-7K9D2M4R8T6W-01``). Nothing else is a lookup key. There is no partial
search, no customer-name search, and no booking-reference search on the public
surface (CRM.md section 10).

Two jobs live here, and they are deliberately separate:

**Normalization** is forgiving, because a handheld scanner, a phone keyboard, and a
pasted email all mangle an identifier differently. It reuses
``shipment_service.normalize_reference`` so the public surface and the internal barcode
search agree on what a reference *is*, then strips the extra punctuation a copy-paste
tends to drag along.

**Validation** is strict, and runs after normalization. A value must match one of the
four route prefixes, twelve characters of the unambiguous alphabet, and — for a package —
a two-digit sequence in the range the package service can actually allocate. A value that
does not match is never sent to the database.

The caller must not treat a validation failure as a distinguishable outcome: an invalid
reference and a correctly formed but unknown one produce the same public response
(CRM.md section 10, "an invalid lookup should reveal no customer data").
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from app.core.enums import RouteGroup
from app.services.identifier_service import UNAMBIGUOUS_ALPHABET
from app.services.shipment_service import normalize_reference as _normalize_core

#: Longest string that could plausibly be an identifier. A public caller sending more
#: than this is not typing a reference.
#:
#: This bound is enforced **here**, in application code, and deliberately not as a
#: FastAPI ``Path(max_length=...)`` constraint. Phase 3 declared it on the route, where
#: it ran before the endpoint body and turned an oversized reference into a detailed 422
#: that named the constraint, echoed the value back, and never touched the rate limiter.
#: Exceeding the bound is not a distinguishable outcome: it is simply not a Solaris
#: reference, and produces the same generic 404 as any other malformed value (DEC-0059).
MAX_INPUT_LENGTH = 120

#: The 12-character suffix alphabet, shared with the generator so the two cannot drift.
_SUFFIX_CLASS = f"[{re.escape(UNAMBIGUOUS_ALPHABET)}]{{12}}"
_PREFIX_CLASS = "|".join(sorted(route.value for route in RouteGroup))

#: A parent Solaris Shipment ID, anchored at both ends. Full match only.
SHIPMENT_PATTERN = re.compile(rf"^SX-(?:{_PREFIX_CLASS})-{_SUFFIX_CLASS}$")

#: A package reference: the parent ID plus a stable two-digit sequence. ``-00`` is not
#: allocatable (sequences start at 1) and is rejected here rather than in the database.
PACKAGE_PATTERN = re.compile(rf"^SX-(?:{_PREFIX_CLASS})-{_SUFFIX_CLASS}-(?:0[1-9]|[1-9][0-9])$")

# Characters a paste or a scanner wedge tends to add around an identifier: surrounding
# quotes and brackets, a trailing sentence period, a stray comma or semicolon. Stripped
# from the ends only -- never from the middle, where they would change the identifier.
_EDGE_NOISE = "\"'`<>[](){}.,;:!?|\\/«»"

# Dash characters an email client, a word processor, or a phone keyboard substitutes for
# a plain hyphen. Converted to "-" rather than stripped, because the hyphen is a
# structural separator in a Solaris reference, not decoration.
_DASH_VARIANTS = (
    "‐",  # hyphen
    "‑",  # non-breaking hyphen
    "‒",  # figure dash
    "–",  # en dash
    "—",  # em dash
    "―",  # horizontal bar
    "−",  # minus sign
    "－",  # fullwidth hyphen-minus
    "_",  # a hyphen that survived a filename or a spreadsheet round trip
)


@dataclass(frozen=True)
class PublicReference:
    """A reference that passed strict validation."""

    value: str
    kind: str  # "shipment" or "package"

    @property
    def is_package(self) -> bool:
        return self.kind == "package"

    @property
    def parent_value(self) -> str:
        """The parent Solaris Shipment ID, whichever form was submitted."""
        return self.value[:-3] if self.is_package else self.value


def normalize_public_reference(raw: str | None) -> str:
    """Uppercase, strip scanner and paste noise, normalize dashes.

    Deliberately forgiving about *presentation* and unmoved on *content*: it will fix
    ``  sx-cav-7k9d2m4r8t6w-01.  `` but it will not repair a wrong character or guess a
    missing one.

    Dashes get one extra pass that the internal search does not need. Mail clients and
    word processors autocorrect a hyphen between capitals into an en dash, so a customer
    who received their ID in an email quite often pastes ``SX–CAV–...``. The internal
    normalizer *removes* those characters, which would turn the identifier into an
    unrecognizable run of letters; here they are converted to a hyphen first, so the
    separator survives. Nothing else about the value changes.
    """
    if not raw:
        return ""
    trimmed = raw.strip()[:MAX_INPUT_LENGTH]
    for dash in _DASH_VARIANTS:
        trimmed = trimmed.replace(dash, "-")
    cleaned = _normalize_core(trimmed)
    # Strip edge punctuation after core normalization, since the core pass removes the
    # whitespace that would otherwise hide a trailing full stop.
    return cleaned.strip(_EDGE_NOISE)


def is_within_input_bound(raw: str | None) -> bool:
    """Whether a submitted value is short enough to be an identifier at all.

    Checked before normalization so an oversized value is refused rather than silently
    truncated into something that might match. Truncation would be a quiet way for
    ``SX-CAV-7K9D2M4R8T6W`` plus 200 characters of noise to become a successful lookup
    if the noise ever landed past the cut; refusing outright cannot.
    """
    if raw is None:
        return True
    return len(raw.strip()) <= MAX_INPUT_LENGTH


def parse_public_reference(raw: str | None) -> PublicReference | None:
    """Normalize then strictly validate. ``None`` means "not a Solaris reference".

    The caller turns ``None`` and "valid but unknown" into the *same* public response,
    so this function's failure must never reach a customer as a distinct message. That
    includes an oversized value: too long is one more way of not being a reference, not a
    separate kind of answer.
    """
    if not is_within_input_bound(raw):
        return None
    reference = normalize_public_reference(raw)
    if not reference:
        return None
    if PACKAGE_PATTERN.match(reference):
        return PublicReference(value=reference, kind="package")
    if SHIPMENT_PATTERN.match(reference):
        return PublicReference(value=reference, kind="shipment")
    return None


def reference_digest(reference: str, *, secret: str) -> str:
    """A keyed, truncated digest of a reference, for operational logs only.

    The complete reference must never reach a log, an error report, analytics, or a page
    title (CRM.md section 10). When an operator genuinely needs to correlate repeated
    lookups -- an abuse investigation, say -- this gives a stable token that cannot be
    reversed into a tracking identifier without the application secret.
    """
    return hmac.new(secret.encode("utf-8"), reference.encode("utf-8"), hashlib.sha256).hexdigest()[
        :12
    ]
