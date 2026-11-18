"""Read-only queries shared by every interface (MCP server, CLI and future chat channels).

Each function returns a JSON-friendly dict that always states the period, the time zone, the
sources involved and anything missing or possibly outdated.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from openclock.library import Library
from openclock.metrics import DuplicatePolicy, filter_workouts, summarize
from openclock.models import Source, Sport
from openclock.periods import Period, date_range, resolve_timezone, today_in, week_containing
from openclock.report import period_to_dict, summary_to_dict, workout_to_dict

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
) -> Period:
    """A custom range when ``start_date``/``end_date`` are given, else the ISO week containing
    ``reference_date`` (default: today in ``tz_name``)."""
    start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    if start or end:
        if not (start and end):
            raise ValueError("Give both start_date and end_date, or neither for a week.")
        return date_range(start, end, tz_name)
    reference = _parse_date(reference_date, "reference_date") or today_in(tz_name)
    return week_containing(reference, tz_name)


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
) -> dict[str, Any]:
    tz_name, notes = choose_timezone(timezone)
    period = resolve_period(tz_name, start_date, end_date, reference_date)
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


def summarize_period(
    library: Library,
    timezone: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    reference_date: str | None = None,
    sport: str | None = "running",
    duplicate_policy: str = "flag",
) -> dict[str, Any]:
    tz_name, notes = choose_timezone(timezone)
    period = resolve_period(tz_name, start_date, end_date, reference_date)
    try:
        policy = DuplicatePolicy(duplicate_policy)
    except ValueError as exc:
        options = ", ".join(p.value for p in DuplicatePolicy)
        raise ValueError(f"Unknown duplicate_policy {duplicate_policy!r}: {options}.") from exc
    library.refresh()
    summary = summarize(
        library.workouts(), period, sport=_parse_sport(sport), duplicate_policy=policy
    )
    result = summary_to_dict(summary)
    status, data_notes = data_status(library, period)
    for source, totals in summary.by_source.items():
        if totals.missing_distance:
            notes.append(f"{totals.missing_distance} {source.value} workout(s) have no distance.")
        if totals.missing_duration:
            notes.append(f"{totals.missing_duration} {source.value} workout(s) have no duration.")
    if summary.combined_withheld_reason:
        notes.append(summary.combined_withheld_reason)
    result["data_status"] = status
    result["notes"] = notes + data_notes
    return result
