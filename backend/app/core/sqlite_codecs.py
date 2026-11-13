"""Explicit ``sqlite3`` adapters and converters for ``date`` and ``datetime``.

Python 3.12 deprecated the four codecs that the ``sqlite3`` module registers on import --
the adapters that turn a ``date`` or ``datetime`` into text on the way in, and the
``date`` and ``timestamp`` converters that turn text back on the way out -- and every use
of them now raises ``DeprecationWarning`` (CPython gh-90016). They are scheduled for
removal, at which point a ``datetime`` handed to the driver would fail with
``InterfaceError: Error binding parameter`` instead of being stored.

The application's own columns never reached them: SQLAlchemy's SQLite dialect formats
``DateTime`` columns itself. What does reach them is any value handed to the driver with
no column type to go by -- a ``datetime`` bound to a ``text()`` statement, which is how
the one warning in the 2,625-test suite arose (``test_account_shipment_authorization``
plants a row with raw SQL and a ``utcnow()`` parameter) -- and anything a script does on
a raw ``sqlite3`` connection. Nothing under ``app/`` does either today; this is here so
that nothing which starts to is silently formatted by a codec that is about to be
removed.

These four functions are the stdlib defaults, transcribed. Registering them replaces the
deprecated entries with un-deprecated ones that produce **the same bytes**:
``YYYY-MM-DD`` for a date and ``YYYY-MM-DD HH:MM:SS[.ffffff][+HH:MM]`` for a datetime --
a space between the date and the time, not a ``T``, exactly as before. A database written
before this module existed and one written after are indistinguishable.
``tests/test_sqlite_datetime_codecs.py`` is the before/after proof.

``app.core.db`` registers them on import, so every engine the application builds, and
every script that imports the application, is covered. Registration is process-wide
and idempotent.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime


def adapt_date(value: date) -> str:
    """``YYYY-MM-DD`` -- what the default adapter stored."""
    return value.isoformat()


def adapt_datetime(value: datetime) -> str:
    """``YYYY-MM-DD HH:MM:SS[.ffffff][+HH:MM]`` -- what the default adapter stored.

    The separator is a space, as it was in every version of Python's default adapter, so
    nothing written by this application changes shape. Microseconds appear only when
    non-zero and a UTC offset only when the value is aware, both as before.
    """
    return value.isoformat(" ")


def convert_date(value: bytes) -> date:
    """The default ``date`` converter: ``YYYY-MM-DD`` back to a ``date``."""
    return date(*map(int, value.split(b"-")))


def convert_timestamp(value: bytes) -> datetime:
    """The default ``timestamp`` converter: ``YYYY-MM-DD HH:MM:SS[.ffffff]`` to a datetime.

    Naive, like the default. The stored text never carried an offset through this
    converter and still does not.
    """
    datepart, timepart = value.split(b" ")
    year, month, day = map(int, datepart.split(b"-"))
    timepart_full = timepart.split(b".")
    hours, minutes, seconds = map(int, timepart_full[0].split(b":"))
    microseconds = int(f"{timepart_full[1].decode():0<6.6}") if len(timepart_full) == 2 else 0
    return datetime(year, month, day, hours, minutes, seconds, microseconds)


def register() -> None:
    """Replace the deprecated default codecs with these. Safe to call more than once."""
    sqlite3.register_adapter(date, adapt_date)
    sqlite3.register_adapter(datetime, adapt_datetime)
    sqlite3.register_converter("date", convert_date)
    sqlite3.register_converter("timestamp", convert_timestamp)
