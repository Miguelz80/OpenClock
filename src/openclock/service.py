"""Read-only queries shared by every interface (MCP server, CLI and future chat channels).

Each function returns a JSON-friendly dict that always states the period, the time zone, the
sources involved and anything missing or possibly outdated.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from openclock.goals import Goal, GoalStatus, evaluate, load_goals_file, parse_goals, period_for
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
from openclock.report import (
    comparison_to_dict,
    goal_progress_to_dict,
    period_to_dict,
    summary_to_dict,
    workout_to_dict,
)

PERIOD_KINDS = ("week", "month")

TIMEZONE_ENV = "OPENCLOCK_TIMEZONE"
GOALS_ENV = "OPENCLOCK_GOALS_FILE"
GOALS_FILE = "goals.toml"


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


# --- goals -----------------------------------------------------------------------------------


def parse_as_of(value: str | None, tz_name: str) -> datetime:
    """``None`` -> now; ``"2026-11-19"`` -> the END of that day (all of it counts);
    ``"2026-11-19T18:00"`` -> that moment in ``tz_name`` unless an offset is given."""
    tz = resolve_timezone(tz_name)
    if not value:
        return datetime.now(UTC).astimezone(tz)
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            return datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(days=1)
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"as_of must be a date (2026-11-19) or date-time (2026-11-19T18:00), got {value!r}"
        ) from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=tz)


def goals_path(library: Library, goals_file: str | Path | None = None) -> Path:
    if goals_file:
        return Path(goals_file)
    if os.environ.get(GOALS_ENV):
        return Path(os.environ[GOALS_ENV])
    return library.data_dir / GOALS_FILE


def resolve_goals(
    library: Library,
    goals: Sequence[Mapping[str, Any]] | None = None,
    goals_file: str | Path | None = None,
) -> tuple[list[Goal], str]:
    """Goals passed in the call win; otherwise read the goals file if it exists."""
    if goals:
        return parse_goals(goals), "request"
    path = goals_path(library, goals_file)
    if path.is_file():
        return load_goals_file(path), path.name
    return [], "none"


def goal_progress(
    library: Library,
    timezone: str | None = None,
    reference_date: str | None = None,
    as_of: str | None = None,
    goals: Sequence[Mapping[str, Any]] | None = None,
    duplicate_policy: str = "flag",
    history: int = 4,
    goals_file: str | Path | None = None,
) -> dict[str, Any]:
    """Progress towards each goal in the week/month containing ``reference_date``.

    ``reference_date`` defaults to the day of ``as_of``, and ``as_of`` defaults to now.
    """
    tz_name, notes = choose_timezone(timezone)
    moment = parse_as_of(as_of, tz_name)
    if not 0 <= history <= 12:
        raise ValueError("history must be between 0 and 12 periods")
    reference = (
        _parse_date(reference_date, "reference_date")
        or (moment - timedelta(microseconds=1)).astimezone(resolve_timezone(tz_name)).date()
    )
    policy = _policy(duplicate_policy)
    goal_list, origin = resolve_goals(library, goals, goals_file)
    library.refresh()
    workouts = library.workouts()
    results = []
    for goal in goal_list:
        period = period_for(goal, reference, tz_name)
        progress = evaluate(goal, workouts, period, moment, policy, history)
        results.append(goal_progress_to_dict(progress))
        if progress.status == GoalStatus.UNAVAILABLE and progress.reason:
            notes.append(f"Goal {goal.id}: {progress.reason}")
    if not goal_list:
        notes.append(
            "No goals defined. Ask the user for a goal (for example 20 km of running per "
            f"week) and pass it in `goals`, or add it to {GOALS_FILE} in the data folder."
        )
    if any(r["period"]["kind"] == "week" for r in results) or not results:
        status, data_notes = data_status(library, week_containing(reference, tz_name))
    else:
        status, data_notes = data_status(library, month_containing(reference, tz_name))
    return {
        "as_of": moment.isoformat(timespec="minutes"),
        "timezone": tz_name,
        "goals_from": origin,
        "goals": results,
        "data_status": status,
        "notes": notes + data_notes,
    }


# --- data folder check -----------------------------------------------------------------------


def check_data(library: Library, timezone: str | None = None) -> dict[str, Any]:
    """An overview of a data folder: what was imported per source, the covered dates, files
    that failed, possible duplicates across devices and whether the goals file is valid."""
    from openclock.metrics import find_possible_duplicates

    tz_name, notes = choose_timezone(timezone)
    tz = resolve_timezone(tz_name)
    library.refresh()
    workouts = library.workouts()
    sources: dict[str, Any] = {}
    for source in Source:
        mine = [w for w in workouts if w.source == source]
        sports: dict[str, int] = {}
        for w in mine:
            sports[w.sport.value] = sports.get(w.sport.value, 0) + 1
        sources[source.value] = {
            "files": sum(1 for f in library.files if f.source == source),
            "workouts": len(mine),
            "by_sport": dict(sorted(sports.items())),
            "first_day": min(w.start for w in mine).astimezone(tz).date().isoformat()
            if mine
            else None,
            "last_day": max(w.start for w in mine).astimezone(tz).date().isoformat()
            if mine
            else None,
            "missing_distance": sum(1 for w in mine if w.distance_m is None),
            "missing_duration": sum(1 for w in mine if w.duration_s is None),
        }
    duplicates = find_possible_duplicates(workouts)
    problems = [
        {"file": f.path.name, "error": f.error, "warnings": f.warnings}
        for f in library.files
        if f.error or f.warnings
    ]
    try:
        goals, origin = resolve_goals(library)
        goals_status = {"file": origin, "goals": [g.id for g in goals], "error": None}
    except ValueError as exc:
        goals_status = {"file": GOALS_FILE, "goals": [], "error": str(exc)}
    if not workouts:
        notes.append("No workouts found. Put .fit, Garmin .zip or Apple Health export files here.")
    if duplicates:
        notes.append(
            f"{len(duplicates)} possible duplicate(s) across devices. Combined totals will be "
            "withheld until a duplicate policy is chosen."
        )
    return {
        "data_dir": str(library.data_dir),
        "timezone": tz_name,
        "files": len(library.files),
        "sources": sources,
        "possible_duplicates": [
            {
                "start_local": p.first.start.astimezone(tz).isoformat(timespec="minutes"),
                "files": [p.first.source_file, p.second.source_file],
                "reason": p.reason,
            }
            for p in duplicates
        ],
        "problems": problems,
        "goals": goals_status,
        "notes": notes,
    }
