"""The explicit ``sqlite3`` date/datetime codecs store exactly what the defaults stored.

Python 3.12 deprecated the ``date``/``datetime`` adapters and converters that ``sqlite3``
registers on import. ``app.core.sqlite_codecs`` replaces them with un-deprecated copies,
and this file is the before/after proof that the replacement changed nothing but the
warning.

**Before** is a fresh interpreter with nothing of the application imported, so the
standard library's defaults are the codecs in force. **After** is this process, where
importing ``app.core.db`` registered ours. The same values go through both; the stored
text must be byte-identical; the deprecation must appear only before.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
import subprocess
import sys
import warnings
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core import sqlite_codecs
from app.core.db import build_engine

# Every shape the application can hand to the driver: naive with and without microseconds
# (the default adapter omits ``.ffffff`` when it is zero), aware in UTC and at an offset
# (it appends ``+HH:MM``), and a bare date.
SAMPLES: list[tuple[str, str, str]] = [
    ("naive_micro", "datetime", datetime(2026, 9, 21, 14, 15, 56, 123456).isoformat()),
    ("naive_whole", "datetime", datetime(2026, 9, 21, 14, 15, 56).isoformat()),
    ("aware_utc", "datetime", datetime(2026, 9, 21, 14, 15, 56, 7, tzinfo=UTC).isoformat()),
    (
        "aware_offset",
        "datetime",
        datetime(2026, 9, 21, 9, 15, 56, tzinfo=timezone(timedelta(hours=-5))).isoformat(),
    ),
    ("date", "date", date(2026, 9, 21).isoformat()),
]

# What a ``datetime`` always looked like on disk: date, a space, time -- never a ``T``.
EXPECTED_TEXT = {
    "naive_micro": "2026-09-21 14:15:56.123456",
    "naive_whole": "2026-09-21 14:15:56",
    "aware_utc": "2026-09-21 14:15:56.000007+00:00",
    "aware_offset": "2026-09-21 09:15:56-05:00",
    "date": "2026-09-21",
}

DEPRECATION_MARKER = "is deprecated as of Python 3.12"


def _revive(kind: str, iso: str) -> date | datetime:
    return date.fromisoformat(iso) if kind == "date" else datetime.fromisoformat(iso)


def _exercise(samples: list[tuple[str, str, str]]) -> dict:
    """Store every sample through a raw ``sqlite3`` connection and read two back.

    Returns the stored text and SQLite storage class per sample, the objects the
    ``date``/``timestamp`` converters produced for the naive samples, and every
    ``DeprecationWarning`` message that was raised on the way. Shared by the "before"
    subprocess and the "after" in-process run, so both measure the same thing.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        stored: dict[str, list[str]] = {}
        plain = sqlite3.connect(":memory:")
        for name, kind, iso in samples:
            value = _revive(kind, iso)
            row = plain.execute("SELECT ?, typeof(?)", (value, value)).fetchone()
            stored[name] = list(row)
        plain.close()

        typed = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES)
        typed.execute("CREATE TABLE t (d date, ts timestamp)")
        typed.execute(
            "INSERT INTO t VALUES (?, ?)",
            (date(2026, 9, 21), datetime(2026, 9, 21, 14, 15, 56, 123456)),
        )
        d, ts = typed.execute("SELECT d, ts FROM t").fetchone()
        typed.close()
    return {
        "stored": stored,
        "converted": [repr(d), repr(ts)],
        "deprecations": sorted(
            {str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)}
        ),
    }


def _run_before(samples: list[tuple[str, str, str]]) -> dict:
    """Run ``_exercise`` in an interpreter that has never imported the application.

    ``-I`` keeps the current directory and the user site off ``sys.path``, so ``app``
    cannot be found even by accident; the two functions are shipped as source.
    """
    source = "\n".join(
        [
            "import json, sqlite3, sys, warnings",
            "from datetime import UTC, date, datetime, timedelta, timezone",
            inspect.getsource(_revive),
            inspect.getsource(_exercise),
            "print(json.dumps(_exercise(json.loads(sys.argv[1]))))",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", source, json.dumps(samples)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def before() -> dict:
    return _run_before(SAMPLES)


@pytest.fixture(scope="module")
def after() -> dict:
    # ``app.core.db`` was imported at the top of this module, which registered the codecs.
    assert sqlite3.adapters[(datetime, sqlite3.PrepareProtocol)] is sqlite_codecs.adapt_datetime
    assert sqlite3.adapters[(date, sqlite3.PrepareProtocol)] is sqlite_codecs.adapt_date
    return _exercise(SAMPLES)


class TestBefore:
    """The baseline this module replaces, measured rather than assumed."""

    def test_the_defaults_stored_these_exact_bytes(self, before: dict) -> None:
        assert {name: row[0] for name, row in before["stored"].items()} == EXPECTED_TEXT
        assert {row[1] for row in before["stored"].values()} == {"text"}

    @pytest.mark.skipif(
        sys.version_info < (3, 12), reason="the defaults are deprecated from Python 3.12"
    )
    def test_the_defaults_are_deprecated(self, before: dict) -> None:
        messages = before["deprecations"]
        assert any("datetime adapter" in m and DEPRECATION_MARKER in m for m in messages)
        assert any("date adapter" in m and DEPRECATION_MARKER in m for m in messages)
        assert any("timestamp converter" in m and DEPRECATION_MARKER in m for m in messages)
        assert any("date converter" in m and DEPRECATION_MARKER in m for m in messages)


class TestAfter:
    """Same values, same bytes, no warning."""

    def test_stored_text_is_byte_identical_to_the_defaults(self, before: dict, after: dict) -> None:
        assert after["stored"] == before["stored"]
        assert {name: row[0] for name, row in after["stored"].items()} == EXPECTED_TEXT

    def test_converters_return_what_the_defaults_returned(self, before: dict, after: dict) -> None:
        assert after["converted"] == before["converted"]
        assert after["converted"] == [
            "datetime.date(2026, 9, 21)",
            "datetime.datetime(2026, 9, 21, 14, 15, 56, 123456)",
        ]

    def test_nothing_is_deprecated_any_more(self, after: dict) -> None:
        assert [m for m in after["deprecations"] if DEPRECATION_MARKER in m] == []

    def test_through_the_application_engine(self) -> None:
        """A ``datetime`` bound to a ``text()`` statement has no column type to be
        formatted by, so it reaches the driver as an object -- the path that used to
        trip the default adapter."""
        engine = build_engine("sqlite://")
        value = datetime(2026, 9, 21, 14, 15, 56, 123456)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with engine.connect() as connection:
                stored = connection.execute(text("SELECT :ts"), {"ts": value}).scalar_one()
        engine.dispose()
        assert stored == "2026-09-21 14:15:56.123456"
        assert [
            str(w.message)
            for w in caught
            if issubclass(w.category, DeprecationWarning) and DEPRECATION_MARKER in str(w.message)
        ] == []

    def test_registration_is_idempotent(self) -> None:
        sqlite_codecs.register()
        sqlite_codecs.register()
        assert sqlite3.adapters[(datetime, sqlite3.PrepareProtocol)] is sqlite_codecs.adapt_datetime
        assert sqlite3.adapters[(date, sqlite3.PrepareProtocol)] is sqlite_codecs.adapt_date
