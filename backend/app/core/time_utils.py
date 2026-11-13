"""UTC-first time helpers.

All timestamps are stored in UTC (CRM.md section 3). Display conversion to the
configured office timezone happens in the presentation layer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def aware_utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Normalize any datetime to a naive UTC value suitable for storage."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def to_timezone(value: datetime | None, tz_name: str | None = None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(zone(tz_name))


def days_ago(days: int) -> datetime:
    return utcnow() - timedelta(days=days)


def days_between(earlier: datetime, later: datetime | None = None) -> int:
    later = later or utcnow()
    return (later - earlier).days


# --- Reporting period boundaries (Phase 5A, DEC-0076) ------------------------
#
# Every report period is a half-open interval [start, end) cut at local midnight in the
# organization's configured timezone and then converted to UTC for the query. A parcel
# handed over at 23:30 on 30 September in Mississauga is September business; cutting on
# UTC midnight would move it into October for four hours of every day.
#
# The offset is not a constant — America/Toronto observes daylight saving — so the
# boundary is resolved through ``zoneinfo`` for the specific date rather than by adding a
# fixed number of hours.


class TimezoneUnavailableError(RuntimeError):
    """The configured timezone cannot be resolved on this installation.

    Raised rather than quietly substituting UTC. A report headed "September, Toronto
    time" that was actually cut on UTC midnight is wrong in a way nobody can see, and
    four hours of every day would land in the wrong month. A loud failure is the lesser
    harm, and ``tzdata`` is a declared dependency precisely so this cannot happen in a
    correctly installed environment.
    """


def is_known_timezone(tz_name: str) -> bool:
    """Whether ``tz_name`` resolves on this installation, without raising."""
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def zone(tz_name: str | None = None) -> ZoneInfo:
    """Resolve a timezone name. Never silently substitutes UTC."""
    name = tz_name or settings.default_timezone
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimezoneUnavailableError(
            f"Timezone {name!r} could not be resolved. Install the 'tzdata' package or "
            f"correct the configured office timezone."
        ) from exc


def local_midnight_utc(day: date, tz_name: str | None = None) -> datetime:
    """Naive-UTC instant of local midnight at the *beginning* of ``day``."""
    local = datetime(day.year, day.month, day.day, tzinfo=zone(tz_name))
    return local.astimezone(UTC).replace(tzinfo=None)


def period_bounds(
    from_date: date, to_date: date, tz_name: str | None = None
) -> tuple[datetime, datetime]:
    """Half-open ``[start, end)`` in naive UTC for an inclusive local date range.

    ``to_date`` is inclusive to the caller and exclusive in the result: the end is local
    midnight at the beginning of the day *after* ``to_date``. Adjacent periods therefore
    tile without a gap and without double-counting a record on the boundary.
    """
    return (
        local_midnight_utc(from_date, tz_name),
        local_midnight_utc(to_date + timedelta(days=1), tz_name),
    )


def in_zone(value: datetime, tz_name: str | None = None) -> datetime:
    """Interpret a naive-UTC stored timestamp in the organization's timezone."""
    return value.replace(tzinfo=UTC).astimezone(zone(tz_name))
