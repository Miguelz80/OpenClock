"""Training goals set by the user, and progress towards them.

Goals are plain data: a metric, a target and a period (week or month). They come from a
``goals.toml`` file or are passed in by the assistant after the user states them. Progress is
computed here from the same totals as every other answer; suggestions are left to the
assistant, which must base them on these numbers. See docs/adr/0008-goals.md.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from openclock.metrics import DuplicatePolicy, Totals, summarize
from openclock.models import Source, Sport, Workout
from openclock.periods import Period, month_containing, previous_equivalent, week_containing


class GoalMetric(StrEnum):
    DISTANCE_KM = "distance_km"  # total distance in the period
    DURATION_MIN = "duration_min"  # total active time in the period
    WORKOUT_COUNT = "workout_count"  # number of workouts in the period
    AVG_PACE = "avg_pace"  # average pace at or below the target (seconds per km)
    LONGEST_KM = "longest_km"  # at least one workout this long in the period


#: Metrics that accumulate through the period, so "on track" can be judged mid-period.
CUMULATIVE = {GoalMetric.DISTANCE_KM, GoalMetric.DURATION_MIN, GoalMetric.WORKOUT_COUNT}


class GoalStatus(StrEnum):
    MET = "met"  # target reached (for a period in progress: reached already)
    ON_TRACK = "on_track"  # in progress; cumulative total at or above the pro-rata target
    BEHIND = "behind"  # in progress; cumulative total below the pro-rata target
    IN_PROGRESS = "in_progress"  # in progress; pace or longest workout not reached yet
    NOT_MET = "not_met"  # period ended without reaching the target
    NOT_STARTED = "not_started"  # the period starts after ``as_of``
    NO_DATA = "no_data"  # the period ends before the first imported workout
    UNAVAILABLE = "unavailable"  # the metric cannot be computed (missing data, duplicates)


PERIODS = ("week", "month")
_PACE = re.compile(r"^\s*(\d{1,2}):([0-5]\d)\s*(?:/\s*km)?\s*$")


@dataclass(frozen=True, slots=True)
class Goal:
    id: str
    metric: GoalMetric
    #: km, minutes, count, seconds per km (pace) or km (longest), depending on ``metric``.
    target: float
    per: str = "week"
    sport: Sport | None = Sport.RUNNING
    #: ``None`` means the combined total of all sources.
    source: Source | None = None
    description: str | None = None


def parse_pace(value: str | float | int) -> float:
    """``"5:30"`` or ``"5:30 /km"`` -> 330.0 seconds per km. Numbers are taken as seconds."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    match = _PACE.match(str(value))
    if not match:
        raise ValueError(f"Pace target must look like '5:30' (min:sec per km), got {value!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_goal(data: Mapping[str, Any], index: int = 0) -> Goal:
    """Validate one goal given as a mapping (from TOML, JSON or an MCP call)."""
    where = f"goal {data.get('id') or index + 1}"
    try:
        metric = GoalMetric(data["metric"])
    except KeyError as exc:
        raise ValueError(f"{where}: 'metric' is required") from exc
    except ValueError as exc:
        options = ", ".join(m.value for m in GoalMetric)
        raise ValueError(f"{where}: unknown metric {data['metric']!r}; use {options}") from exc
    if "target" not in data:
        raise ValueError(f"{where}: 'target' is required")
    raw_target = data["target"]
    if metric == GoalMetric.AVG_PACE:
        target = parse_pace(raw_target)
    else:
        try:
            target = float(raw_target)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{where}: target must be a number, got {raw_target!r}") from exc
    if not math.isfinite(target) or target <= 0:
        raise ValueError(f"{where}: target must be a positive number")
    per = data.get("per", "week")
    if per not in PERIODS:
        raise ValueError(f"{where}: 'per' must be 'week' or 'month', got {per!r}")
    sport_raw = data.get("sport", "running")
    try:
        sport = None if sport_raw in (None, "all") else Sport(sport_raw)
    except ValueError as exc:
        raise ValueError(f"{where}: unknown sport {sport_raw!r}") from exc
    source_raw = data.get("source", "combined")
    try:
        source = None if source_raw in (None, "combined") else Source(source_raw)
    except ValueError as exc:
        raise ValueError(f"{where}: source must be 'combined', 'garmin' or 'apple_health'") from exc
    goal_id = str(data.get("id") or f"{metric.value}-{per}")
    return Goal(goal_id, metric, target, per, sport, source, data.get("description"))


def parse_goals(items: Iterable[Mapping[str, Any]]) -> list[Goal]:
    goals = [parse_goal(item, i) for i, item in enumerate(items)]
    ids = [g.id for g in goals]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate goal id(s): {', '.join(duplicates)}")
    return goals


def load_goals_file(path: str | Path) -> list[Goal]:
    """Read ``[[goal]]`` tables from a TOML file."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path.name}: invalid TOML ({exc})") from exc
    return parse_goals(data.get("goal", []))


# --- progress --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeriodResult:
    period: Period
    actual: float | None
    status: GoalStatus


@dataclass(frozen=True, slots=True)
class GoalProgress:
    goal: Goal
    period: Period
    as_of: datetime
    actual: float | None
    status: GoalStatus
    elapsed_fraction: float
    workouts: list[Workout]
    #: Pro-rata target at ``as_of`` (cumulative metrics in a period in progress only).
    expected_by_now: float | None = None
    #: Still needed to reach the target (cumulative metrics only; 0 when met).
    remaining: float | None = None
    days_left: int | None = None
    reason: str | None = None
    history: list[PeriodResult] = field(default_factory=list)

    @property
    def recent_average(self) -> float | None:
        """Mean of past periods that have data and a value."""
        values = [h.actual for h in self.history if h.actual is not None]
        return sum(values) / len(values) if values else None

    @property
    def recent_met(self) -> tuple[int, int]:
        """(periods met, periods with data) among the past periods."""
        judged = [h for h in self.history if h.status in (GoalStatus.MET, GoalStatus.NOT_MET)]
        return sum(h.status == GoalStatus.MET for h in judged), len(judged)


def period_for(goal: Goal, day: Any, tz_name: str) -> Period:
    builder = week_containing if goal.per == "week" else month_containing
    return builder(day, tz_name)


def _value(goal: Goal, totals: Totals | None) -> float | None:
    if totals is None:
        return None
    match goal.metric:
        case GoalMetric.DISTANCE_KM:
            return None if totals.distance_m is None else totals.distance_m / 1000
        case GoalMetric.DURATION_MIN:
            return None if totals.duration_s is None else totals.duration_s / 60
        case GoalMetric.WORKOUT_COUNT:
            return float(totals.workout_count)
        case GoalMetric.AVG_PACE:
            return totals.pace_s_per_km
        case GoalMetric.LONGEST_KM:
            return None if totals.longest_distance_m is None else totals.longest_distance_m / 1000


def _reached(goal: Goal, actual: float) -> bool:
    if goal.metric == GoalMetric.AVG_PACE:
        return actual <= goal.target
    return actual >= goal.target


@dataclass(frozen=True, slots=True)
class _Measure:
    value: float | None
    reason: str | None
    workouts: list[Workout]
    withheld: bool = False  # combined total withheld because of possible duplicates


def _measure(
    goal: Goal, workouts: list[Workout], period: Period, policy: DuplicatePolicy
) -> _Measure:
    summary = summarize(workouts, period, sport=goal.sport, duplicate_policy=policy)
    totals = summary.combined if goal.source is None else summary.by_source[goal.source]
    if totals is None:
        return _Measure(None, summary.combined_withheld_reason, summary.workouts, withheld=True)
    selected = [w for w in summary.workouts if goal.source is None or w.source == goal.source]
    actual = _value(goal, totals)
    reason = None
    if actual is None:
        reason = {
            GoalMetric.AVG_PACE: "no workout in the period has both distance and duration",
            GoalMetric.LONGEST_KM: "no workout in the period has a distance",
        }.get(goal.metric, f"{goal.metric.value} is unavailable for these workouts")
    return _Measure(actual, reason, selected)


def _first_data(goal: Goal, workouts: list[Workout]) -> datetime | None:
    relevant = [w.start for w in workouts if goal.source is None or w.source == goal.source]
    return min(relevant, default=None)


def evaluate(
    goal: Goal,
    workouts: list[Workout],
    period: Period,
    as_of: datetime,
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.FLAG,
    history: int = 4,
) -> GoalProgress:
    """Progress of ``goal`` in ``period`` as of ``as_of``, plus the previous periods."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    # Progress "as of" a moment only counts what had happened by then.
    workouts = [w for w in workouts if w.start < as_of]
    first_data = _first_data(goal, workouts)
    past: list[PeriodResult] = []
    earlier = period
    for _ in range(history):
        earlier = previous_equivalent(earlier)
        if first_data is None or earlier.end <= first_data:
            past.append(PeriodResult(earlier, None, GoalStatus.NO_DATA))
            continue
        m = _measure(goal, workouts, earlier, duplicate_policy)
        if m.value is not None:
            status = GoalStatus.MET if _reached(goal, m.value) else GoalStatus.NOT_MET
        elif m.withheld or goal.metric in CUMULATIVE:
            status = GoalStatus.UNAVAILABLE
        else:  # no qualifying workout for a pace or longest-run goal
            status = GoalStatus.NOT_MET
        past.append(PeriodResult(earlier, m.value, status))

    total_s = period.duration.total_seconds()
    elapsed_s = (as_of - period.start).total_seconds()
    elapsed = min(1.0, max(0.0, elapsed_s / total_s))
    m = _measure(goal, workouts, period, duplicate_policy)
    actual, reason = m.value, m.reason
    days_left = max(0, math.ceil((period.end - as_of) / timedelta(days=1)))
    common = dict(
        goal=goal,
        period=period,
        as_of=as_of,
        elapsed_fraction=elapsed,
        workouts=m.workouts,
        history=past,
        days_left=days_left,
    )

    if elapsed_s <= 0:
        return GoalProgress(actual=None, status=GoalStatus.NOT_STARTED, **common)
    if first_data is None or period.end <= first_data:
        return GoalProgress(
            actual=None,
            status=GoalStatus.NO_DATA,
            reason="no imported workouts cover this period",
            **common,
        )
    finished = elapsed >= 1.0
    if actual is None:
        # A pace or longest-run goal with no qualifying workout is simply not reached yet.
        if goal.metric not in CUMULATIVE and not m.withheld:
            status = GoalStatus.NOT_MET if finished else GoalStatus.IN_PROGRESS
        else:
            status = GoalStatus.UNAVAILABLE
        return GoalProgress(actual=None, status=status, reason=reason, **common)

    reached = _reached(goal, actual)
    expected = remaining = None
    if goal.metric in CUMULATIVE:
        remaining = max(0.0, goal.target - actual)
        if not finished:
            expected = goal.target * elapsed
    if reached:
        status = GoalStatus.MET
    elif finished:
        status = GoalStatus.NOT_MET
    elif goal.metric in CUMULATIVE:
        status = GoalStatus.ON_TRACK if actual >= expected else GoalStatus.BEHIND
    else:
        status = GoalStatus.IN_PROGRESS
    return GoalProgress(
        actual=actual,
        status=status,
        expected_by_now=expected,
        remaining=remaining,
        **common,
    )
