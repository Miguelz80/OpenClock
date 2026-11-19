"""Totals per source, duplicate detection and combined totals.

All numbers that an assistant reports come from here, never from the model.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from openclock.models import Source, Sport, Workout
from openclock.periods import Period

#: Two workouts from different sources are possible duplicates when their time ranges overlap
#: for at least this fraction of the shorter workout.
DUPLICATE_MIN_OVERLAP = 0.5
#: When a duration is missing, workouts are compared by start time within this tolerance.
DUPLICATE_START_TOLERANCE = timedelta(minutes=5)


class DuplicatePolicy(StrEnum):
    """How to build a combined total when possible duplicates exist."""

    FLAG = "flag"  # withhold the combined total and list the duplicates
    COUNT_ALL = "count_all"  # add everything, duplicates included
    PREFER_GARMIN = "prefer_garmin"  # keep the Garmin record of each duplicate pair
    PREFER_APPLE_HEALTH = "prefer_apple_health"  # keep the Apple Health record of each pair


_PREFERRED_SOURCE = {
    DuplicatePolicy.PREFER_GARMIN: Source.GARMIN,
    DuplicatePolicy.PREFER_APPLE_HEALTH: Source.APPLE_HEALTH,
}


@dataclass(frozen=True, slots=True)
class Totals:
    """Sums over a group of workouts. A metric is summed only where it is available."""

    workout_count: int
    distance_m: float | None  # None when no workout in a non-empty group has a distance
    duration_s: float | None  # None when no workout in a non-empty group has a duration
    missing_distance: int
    missing_duration: int


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    first: Workout
    second: Workout
    overlap_ratio: float | None  # None when compared by start time only
    reason: str


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    period: Period
    sport: Sport | None
    workouts: list[Workout]
    by_source: dict[Source, Totals]
    possible_duplicates: list[DuplicateCandidate]
    duplicate_policy: DuplicatePolicy
    combined: Totals | None
    combined_withheld_reason: str | None = None
    excluded_from_combined: list[Workout] = field(default_factory=list)

    @property
    def sources_without_data(self) -> list[Source]:
        return [s for s, t in self.by_source.items() if t.workout_count == 0]


def filter_workouts(
    workouts: Iterable[Workout],
    period: Period,
    sport: Sport | None = None,
    source: Source | None = None,
) -> list[Workout]:
    """Workouts whose start falls inside ``period``, sorted by start time."""
    selected = [
        w
        for w in workouts
        if period.contains(w.start)
        and (sport is None or w.sport == sport)
        and (source is None or w.source == source)
    ]
    return sorted(selected, key=lambda w: (w.start, w.source, w.source_id))


def totals(workouts: Sequence[Workout]) -> Totals:
    distances = [w.distance_m for w in workouts if w.distance_m is not None]
    durations = [w.duration_s for w in workouts if w.duration_s is not None]
    empty = not workouts
    return Totals(
        workout_count=len(workouts),
        distance_m=sum(distances) if (distances or empty) else None,
        duration_s=sum(durations) if (durations or empty) else None,
        missing_distance=len(workouts) - len(distances),
        missing_duration=len(workouts) - len(durations),
    )


def _compare(a: Workout, b: Workout) -> DuplicateCandidate | None:
    if a.source == b.source or a.sport != b.sport:
        return None
    a_end, b_end = a.end, b.end
    if a_end is not None and b_end is not None and a.duration_s and b.duration_s:
        overlap = (min(a_end, b_end) - max(a.start, b.start)).total_seconds()
        ratio = max(0.0, overlap) / min(a.duration_s, b.duration_s)
        if ratio >= DUPLICATE_MIN_OVERLAP:
            return DuplicateCandidate(
                a, b, round(ratio, 3), f"time ranges overlap {ratio:.0%} of the shorter workout"
            )
        return None
    gap = abs(a.start - b.start)
    if gap <= DUPLICATE_START_TOLERANCE:
        minutes = gap.total_seconds() / 60
        return DuplicateCandidate(
            a, b, None, f"duration unavailable; starts {minutes:.1f} min apart"
        )
    return None


def find_possible_duplicates(workouts: Sequence[Workout]) -> list[DuplicateCandidate]:
    """Pairs of workouts from different sources that probably describe the same session."""
    ordered = sorted(workouts, key=lambda w: (w.start, w.source, w.source_id))
    found: list[DuplicateCandidate] = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            candidate = _compare(a, b)
            if candidate is not None:
                found.append(candidate)
    return found


def summarize(
    workouts: Iterable[Workout],
    period: Period,
    sport: Sport | None = Sport.RUNNING,
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.FLAG,
) -> PeriodSummary:
    """Totals per source for ``period``, with duplicates flagged before combining."""
    selected = filter_workouts(workouts, period, sport)
    by_source = {source: totals([w for w in selected if w.source == source]) for source in Source}
    duplicates = find_possible_duplicates(selected)

    combined: Totals | None
    withheld: str | None = None
    excluded: list[Workout] = []
    if not duplicates or duplicate_policy == DuplicatePolicy.COUNT_ALL:
        combined = totals(selected)
    elif duplicate_policy == DuplicatePolicy.FLAG:
        combined = None
        withheld = (
            f"{len(duplicates)} possible duplicate(s) across sources. Confirm with the user, "
            "then call again with duplicate_policy 'count_all', 'prefer_garmin' or "
            "'prefer_apple_health'."
        )
    else:
        preferred = _PREFERRED_SOURCE[duplicate_policy]
        drop: dict[tuple[Source, str], Workout] = {}
        for pair in duplicates:
            for member in (pair.first, pair.second):
                if member.source != preferred:
                    drop[member.key] = member
        excluded = sorted(drop.values(), key=lambda w: (w.start, w.source_id))
        combined = totals([w for w in selected if w.key not in drop])

    return PeriodSummary(
        period=period,
        sport=sport,
        workouts=selected,
        by_source=by_source,
        possible_duplicates=duplicates,
        duplicate_policy=duplicate_policy,
        combined=combined,
        combined_withheld_reason=withheld,
        excluded_from_combined=excluded,
    )
