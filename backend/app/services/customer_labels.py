"""Customer-facing text never names the vendor or its carriers (owner, Louis Tong, 2026-10-21).

Surcharge descriptions are copied from the vendor's rate sheet, and a vendor's own wording can
carry its name ("phụ thu Kango ..."); staff also type free text a customer reads (a tracking
update, a location, invoice notes, the bill-to). Three tools, each a test:

* :func:`customer_safe_label` -- a **label** (a surcharge or invoice line) that names a vendor
  is replaced as a whole by the neutral label ("Phụ phí" / "Surcharge").
* :func:`customer_safe_text` -- **free text** keeps its words; only the words that name a
  vendor are replaced by a neutral word in the output language ("đối tác vận chuyển" /
  "carrier"). Used on output (tracking, the Customer Account timeline, invoice documents
  and PDFs).
* :func:`refuse_vendor_name` -- a staff save of customer-facing free text (a draft invoice's
  lines, notes, bill-to and PO) that names a vendor is refused (422, the field named).

The names come from the ``vendors`` table (key and name) plus :data:`ALWAYS_HIDDEN`, so a vendor
added later is covered without a code change.

**Matching** (independent review M2): the text is folded (case, Vietnamese diacritics) and cut
into words of letters and digits; a name matches when its words appear as consecutive words of
the text -- so "ana" never hides "Canada" and "ups" never hides "groups". To catch obfuscation
("Kan-go", "K.ango") a name of at least :data:`_SQUASH_MIN_LENGTH` letters and digits also
matches when it appears in the text with everything but letters and digits removed. A name
shorter than :data:`_MIN_NAME_LENGTH` is ignored unless it is listed in :data:`ALWAYS_HIDDEN`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.errors import ValidationError

#: Names hidden even before any vendor row exists (the current air vendor). A name listed
#: here is matched whatever its length.
ALWAYS_HIDDEN: tuple[str, ...] = ("kango",)
#: The neutral label used when a vendor label names a vendor.
NEUTRAL_LABEL = {"vi": "Phụ phí", "en": "Surcharge"}
#: The neutral word that replaces a vendor's name inside free text.
NEUTRAL_WORD = {"vi": "đối tác vận chuyển", "en": "carrier"}
_MIN_NAME_LENGTH = 4
_SQUASH_MIN_LENGTH = 5
_WORD = re.compile(r"[^\W_]+")


def _fold(text: str) -> str:
    """Case-, diacritic- and spacing-insensitive form, for matching only."""
    decomposed = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join(stripped.split())


def _words(text: str) -> list[str]:
    return _WORD.findall(_fold(text))


def _usable(name: str) -> list[str] | None:
    """The folded words of a name, or None when it is too short to match safely."""
    words = _words(name or "")
    squashed = "".join(words)
    if not squashed:
        return None
    if len(squashed) < _MIN_NAME_LENGTH and squashed not in {
        "".join(_words(n)) for n in ALWAYS_HIDDEN
    }:
        return None
    return words


def vendor_names(db: Session | None) -> tuple[str, ...]:
    """Every name a customer must not read, folded for matching."""
    names = set(ALWAYS_HIDDEN)
    if db is not None:
        from app.models import Vendor  # noqa: PLC0415

        for key, name in db.execute(select(Vendor.key, Vendor.name)):
            for value in (key, name):
                if value and _usable(value):
                    names.add(_fold(value))
    return tuple(sorted({_fold(n) for n in names}))


def _spans(text: str, names: Iterable[str]) -> list[tuple[int, int]]:
    """The character spans of ``text`` that name a vendor, merged and in order."""
    tokens = [(m.start(), m.end(), "".join(_words(m.group()))) for m in _WORD.finditer(text)]
    tokens = [token for token in tokens if token[2]]
    folded = [token[2] for token in tokens]
    squashed = "".join(folded)
    # Where each token's letters start in the squashed text.
    starts, position = [], 0
    for word in folded:
        starts.append(position)
        position += len(word)
    hits: list[tuple[int, int]] = []  # token index ranges, inclusive
    for name in names:
        words = _usable(name)
        if not words:
            continue
        size = len(words)
        for index in range(len(folded) - size + 1):
            if folded[index : index + size] == words:
                hits.append((index, index + size - 1))
        joined = "".join(words)
        if len(joined) >= _SQUASH_MIN_LENGTH:
            found = squashed.find(joined)
            while found != -1:
                end = found + len(joined) - 1
                first = max(i for i, s in enumerate(starts) if s <= found)
                last = max(i for i, s in enumerate(starts) if s <= end)
                hits.append((first, last))
                found = squashed.find(joined, found + 1)
    merged: list[tuple[int, int]] = []
    for first, last in sorted(hits):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return [(tokens[first][0], tokens[last][1]) for first, last in merged]


def names_a_vendor(text: str | None, names: Iterable[str]) -> bool:
    if not text:
        return False
    return bool(_spans(text, tuple(names)))


def customer_safe_label(text: str | None, names: Iterable[str], *, language: str = "en") -> str:
    """``text`` unless it names a vendor, else the neutral surcharge label (whole label)."""
    names = tuple(names)
    if names_a_vendor(text, names):
        return NEUTRAL_LABEL.get(language, NEUTRAL_LABEL["en"])
    return text or ""


def customer_safe_text(
    text: str | None, names: Iterable[str], *, language: str = "en"
) -> str | None:
    """Free text with only the words that name a vendor replaced by a neutral word."""
    if not text:
        return text
    spans = _spans(text, tuple(names))
    if not spans:
        return text
    word = NEUTRAL_WORD.get(language, NEUTRAL_WORD["en"])
    out, cursor = [], 0
    for start, end in spans:
        out.append(text[cursor:start])
        out.append(word)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def refuse_vendor_name(text: str | None, names: Iterable[str], *, field: str) -> None:
    """Refuse (422, ``field`` named) customer-facing text that names a vendor."""
    if names_a_vendor(text, names):
        raise ValidationError(
            "Customers must not read a vendor's or carrier's name here: reword it.",
            field=field,
        )
