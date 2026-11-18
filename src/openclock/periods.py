"""Time-zone-aware reporting periods.

A week is ISO 8601: Monday 00:00 (inclusive) to the next Monday 00:00 (exclusive), in the
time zone the user chose. See docs/adr/0005-duplicates-and-time-zones.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class Period:
    """Half-open interval ``[start, end)`` expressed in the user's time zone."""

    start: datetime
    end: datetime
    timezone: str
    kind: str  # "week", "month" or "custom"

    def contains(self, moment: datetime) -> bool:
        # Compare in UTC: Python compares datetimes that share a tzinfo by wall-clock time,
        # which would be wrong across a DST change.
        utc = moment.astimezone(UTC)
        return self.start.astimezone(UTC) <= utc < self.end.astimezone(UTC)

    @property
    def duration(self) -> timedelta:
        return self.end.astimezone(UTC) - self.start.astimezone(UTC)

    @property
    def days(self) -> int:
        """Number of calendar days in the period."""
        return (self.last_day - self.first_day).days + 1

    @property
    def first_day(self) -> date:
        return self.start.date()

    @property
    def last_day(self) -> date:
        """Last calendar day included in the period (inclusive)."""
        return (self.end - timedelta(microseconds=1)).date()


def resolve_timezone(name: str) -> ZoneInfo:
    """Return the IANA zone for ``name`` or raise ``ValueError`` with a helpful message."""
    if not name or not isinstance(name, str):
        raise ValueError("A time zone is required, e.g. 'America/Sao_Paulo' or 'UTC'.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Unknown time zone {name!r}. Use an IANA name such as 'America/Sao_Paulo'."
        ) from exc


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz)


def today_in(tz_name: str) -> date:
    return datetime.now(UTC).astimezone(resolve_timezone(tz_name)).date()


def week_containing(day: date, tz_name: str) -> Period:
    """The ISO week (Monday to Sunday) that contains ``day``, in ``tz_name``."""
    tz = resolve_timezone(tz_name)
    monday = day - timedelta(days=day.weekday())
    return Period(
        start=_local_midnight(monday, tz),
        end=_local_midnight(monday + timedelta(days=7), tz),
        timezone=tz_name,
        kind="week",
    )


def date_range(first_day: date, last_day: date, tz_name: str) -> Period:
    """Calendar days ``first_day`` to ``last_day``, both inclusive, in ``tz_name``."""
    if last_day < first_day:
        raise ValueError("end_date must be on or after start_date")
    tz = resolve_timezone(tz_name)
    return Period(
        start=_local_midnight(first_day, tz),
        end=_local_midnight(last_day + timedelta(days=1), tz),
        timezone=tz_name,
        kind="custom",
    )


def month_containing(day: date, tz_name: str) -> Period:
    """The calendar month that contains ``day``, in ``tz_name``."""
    tz = resolve_timezone(tz_name)
    first = day.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return Period(
        start=_local_midnight(first, tz),
        end=_local_midnight(following, tz),
        timezone=tz_name,
        kind="month",
    )


def previous_equivalent(period: Period) -> Period:
    """The period of the same kind right before ``period``.

    - week   -> the previous ISO week
    - month  -> the previous calendar month (lengths may differ; see ``Period.days``)
    - custom -> the same number of days immediately before
    """
    if period.kind == "week":
        return week_containing(period.first_day - timedelta(days=7), period.timezone)
    if period.kind == "month":
        return month_containing(period.first_day - timedelta(days=1), period.timezone)
    last = period.first_day - timedelta(days=1)
    return date_range(last - timedelta(days=period.days - 1), last, period.timezone)
