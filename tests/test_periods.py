from datetime import UTC, date, datetime, timedelta

import pytest

from openclock.periods import date_range, resolve_timezone, week_containing


def test_week_runs_monday_to_monday_in_local_time():
    week = week_containing(date(2026, 11, 18), "America/Sao_Paulo")  # a Wednesday
    assert week.start.isoformat() == "2026-11-16T00:00:00-03:00"
    assert week.end.isoformat() == "2026-11-23T00:00:00-03:00"
    assert week.first_day == date(2026, 11, 16)
    assert week.last_day == date(2026, 11, 22)


@pytest.mark.parametrize("day", [date(2026, 11, 16), date(2026, 11, 22)])
def test_monday_and_sunday_belong_to_the_same_week(day):
    assert week_containing(day, "UTC").first_day == date(2026, 11, 16)


def test_sunday_night_in_sao_paulo_is_monday_in_utc():
    # 22:00 Sunday in São Paulo == 01:00 Monday UTC.
    sunday_night = datetime(2026, 11, 16, 1, 0, tzinfo=UTC)
    local_week = week_containing(date(2026, 11, 18), "America/Sao_Paulo")
    utc_week = week_containing(date(2026, 11, 18), "UTC")
    assert not local_week.contains(sunday_night)
    assert utc_week.contains(sunday_night)


def test_end_is_exclusive():
    week = week_containing(date(2026, 11, 18), "UTC")
    assert week.contains(week.start)
    assert not week.contains(week.end)
    assert week.contains(week.end - timedelta(microseconds=1))


def test_week_across_dst_change_has_local_boundaries():
    # Europe/Berlin leaves DST on 2026-10-25, so that week lasts 169 hours.
    week = week_containing(date(2026, 10, 21), "Europe/Berlin")
    assert week.duration == timedelta(hours=169)
    # 00:30 UTC on Monday 26 Oct is 01:30 local, i.e. already the next week.
    assert not week.contains(datetime(2026, 10, 26, 0, 30, tzinfo=UTC))
    assert week.start.isoformat() == "2026-10-19T00:00:00+02:00"
    assert week.end.isoformat() == "2026-10-26T00:00:00+01:00"


def test_date_range_is_inclusive_of_last_day():
    period = date_range(date(2026, 11, 1), date(2026, 11, 30), "America/Sao_Paulo")
    assert period.start.isoformat() == "2026-11-01T00:00:00-03:00"
    assert period.end.isoformat() == "2026-12-01T00:00:00-03:00"
    assert period.last_day == date(2026, 11, 30)


def test_date_range_rejects_reversed_dates():
    with pytest.raises(ValueError, match="on or after"):
        date_range(date(2026, 11, 2), date(2026, 11, 1), "UTC")


@pytest.mark.parametrize("name", ["", "Mars/Olympus", "not a zone"])
def test_unknown_time_zone(name):
    with pytest.raises(ValueError):
        resolve_timezone(name)
