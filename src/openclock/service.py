"""Read-only queries shared by every interface (MCP server, CLI and future chat channels).

Each function returns a JSON-friendly dict that always states the period, the time zone, the
sources involved and anything missing or possibly outdated.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from openclock.library import Library
from openclock.metrics import DuplicatePolicy, PeriodSummary, compare, filter_workouts, summarize
from openclock.models import Source, Sport
from openclock.periods import (
    Period,
    date_range,
    month_containing,
    previous_equivalent,
    resolve_timezone,
    today_in,
    week_containing,
)
from openclock.report import comparison_to_dict, period_to_dict, summary_to_dict, workout_to_dict

PERIOD_KINDS = ("week", "month")

TIMEZONE_ENV = "OPENCLOCK_TIMEZONE"


def _parse_date(value: str | None, name: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date like 2026-11-18, got {value!r}") from exc


def choose_timezone(timezone: str | None) -> tuple[str, list[str]]:
    """The requested zone, else ``$OPENCLOCK_TIMEZONE``, else UTC with a note."""
    notes: list[str] = []
    name = timezone or os.environ.get(TIMEZONE_ENV)
    if not name:
        name = "UTC"
        notes.append(
            "No time zone given and OPENCLOCK_TIMEZONE is not set; using UTC. Ask the user "
            "for their time zone, because week boundaries depend on it."
        )
    resolve_timezone(name)
    return name, notes


def resolve_period(
    tz_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    reference_date: str | None = None,
    period: str = "week",
) -> Period:
    """A custom range when ``start_date``/``end_date`` are given, else the ISO week (or the
    calendar month, with ``period="month"``) containing ``reference_date`` (default: today in
    ``tz_name``)."""
    start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    if start or end:
        if not (start and end):
            raise ValueError("Give both start_date and end_date, or neither for a week or month.")
        return date_range(start, end, tz_name)
    if period not in PERIOD_KINDS:
        raise ValueError(f"Unknown period {period!r}. Use 'week' or 'month'.")
    reference = _parse_date(reference_date, "reference_date") or today_in(tz_name)
    builder = week_containing if period == "week" else month_containing
    return builder(reference, tz_name)


def _parse_sport(sport: str | None) -> Sport | None:
    if sport in (None, "", "all"):
        return None
    try:
        return Sport(sport)
    except ValueError as exc:
        options = ", ".join([s.value for s in Sport] + ["all"])
        raise ValueError(f"Unknown sport {sport!r}. Use one of: {options}.") from exc


def data_status(library: Library, period: Period) -> tuple[dict[str, Any], list[str]]:
    """Files per source, import problems and possibly outdated data."""
    notes: list[str] = []
    status: dict[str, Any] = {}
    workouts = library.workouts()
    for source in Source:
        files = [f for f in library.files if f.source == source]
        mine = [w for w in workouts if w.source == source]
        latest = max((w.start for w in mine), default=None)
        status[source.value] = {
            "files": [
                {
                    "file": f.path.name,
                    "workouts": len(f.workouts),
                    "modified_utc": f.modified.isoformat(timespec="seconds"),
                    "error": f.error,
                    "warnings": f.warnings,
                }
                for f in files
            ],
            "latest_workout_start": (
                latest.astimezone(resolve_timezone(period.timezone)).isoformat() if latest else None
            ),
        }
        if not files:
            notes.append(f"No {source.value} files in the data directory.")
        elif latest is not None and latest < period.start:
            notes.append(
                f"The latest {source.value} workout is from {latest.date().isoformat()}, before "
                "this period; the export may be outdated."
            )
        for f in files:
            if f.error:
                notes.append(f"Could not import {f.path.name}: {f.error}")
            notes.extend(f.warnings)
    return status, notes


def list_workouts(
    library: Library,
    timezone: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    reference_date: str | None = None,
    source: str | None = None,
    sport: str | None = "all",
    period_kind: str = "week",
) -> dict[str, Any]:
    tz_name, notes = choose_timezone(timezone)
    period = resolve_period(tz_name, start_date, end_date, reference_date, period_kind)
    library.refresh()
    selected = filter_workouts(
        library.workouts(),
        period,
        sport=_parse_sport(sport),
        source=Source(source) if source else None,
    )
    status, data_notes = data_status(library, period)
    return {
        "period": period_to_dict(period),
        "filters": {"source": source or "all", "sport": sport or "all"},
        "workout_count": len(selected),
        "workouts": [workout_to_dict(w, tz_name) for w in selected],
        "data_status": status,
        "notes": notes + data_notes,
    }


def _policy(duplicate_policy: str) -> DuplicatePolicy:
    try:
        return DuplicatePolicy(duplicate_policy)
    except ValueError as exc:
        options = ", ".join(p.value for p in DuplicatePolicy)
        raise ValueError(f"Unknown duplicate_policy {duplicate_policy!r}: {options}.") from exc


def _summary_notes(summary: PeriodSummary, label: str = "") -> list[str]:
    prefix = f"{label}: " if label else ""
    notes = []
    for source, totals in summary.by_source.items():
        if totals.missing_distance:
            notes.append(
                f"{prefix}{totals.missing_distance} {source.value} workout(s) have no distance."
            )
        if totals.missing_duration:
            notes.append(
                f"{prefix}{totals.missing_duration} {source.value} workout(s) have no duration."
            )
    if summary.combined_withheld_reason:
        notes.append(prefix + summary.combined_withheld_reason)
    return notes


def summarize_period(
    library: Library,
    timezone: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    reference_date: str | None = None,
    sport: str | None = "running",
    duplicate_policy: str = "flag",
    period_kind: str = "week",
) -> dict[str, Any]:
    tz_name, notes = choose_timezone(timezone)
    period = resolve_period(tz_name, start_date, end_date, reference_date, period_kind)
    policy = _policy(duplicate_policy)
    library.refresh()
    summary = summarize(
        library.workouts(), period, sport=_parse_sport(sport), duplicate_policy=policy
    )
    result = summary_to_dict(summary)
    status, data_notes = data_status(library, period)
    result["data_status"] = status
    result["notes"] = notes + _summary_notes(summary) + data_notes
    return result


def compare_periods(
    library: Library,
    timezone: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    reference_date: str | None = None,
    sport: str | None = "running",
    duplicate_policy: str = "flag",
    period_kind: str = "week",
) -> dict[str, Any]:
    """Compare a period with the equivalent period right before it."""
    tz_name, notes = choose_timezone(timezone)
    current_period = resolve_period(tz_name, start_date, end_date, reference_date, period_kind)
    previous_period = previous_equivalent(current_period)
    policy, sport_filter = _policy(duplicate_policy), _parse_sport(sport)
    library.refresh()
    workouts = library.workouts()
    current = summarize(workouts, current_period, sport=sport_filter, duplicate_policy=policy)
    previous = summarize(workouts, previous_period, sport=sport_filter, duplicate_policy=policy)
    result = comparison_to_dict(compare(current, previous))
    if current_period.days != previous_period.days:
        notes.append(
            f"The periods have different lengths ({current_period.days} vs "
            f"{previous_period.days} days); totals are not normalized per day."
        )
    if previous.combined is not None and previous.combined.workout_count == 0:
        notes.append("No workouts in the previous period, so percentage changes are undefined.")
    status, data_notes = data_status(library, current_period)
    result["data_status"] = status
    result["notes"] = (
        notes
        + _summary_notes(current, "current")
        + _summary_notes(previous, "previous")
        + data_notes
    )
    return result
