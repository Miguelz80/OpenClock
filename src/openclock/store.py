"""In-memory workout store that makes re-imports idempotent."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from openclock.models import Source, Workout


@dataclass(frozen=True, slots=True)
class AddResult:
    added: int
    replaced: int


class WorkoutStore:
    """Workouts keyed by ``(source, source_id)``.

    Adding a workout whose key already exists replaces it, so importing the same file twice
    (or two copies of it) leaves the totals unchanged.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[Source, str], Workout] = {}

    def add(self, workout: Workout) -> bool:
        """Insert or replace ``workout``. Returns ``True`` if it was new."""
        is_new = workout.key not in self._by_key
        self._by_key[workout.key] = workout
        return is_new

    def add_all(self, workouts: Iterable[Workout]) -> AddResult:
        added = replaced = 0
        for workout in workouts:
            if self.add(workout):
                added += 1
            else:
                replaced += 1
        return AddResult(added=added, replaced=replaced)

    def all(self) -> list[Workout]:
        return sorted(self._by_key.values(), key=lambda w: (w.start, w.source, w.source_id))

    def __len__(self) -> int:
        return len(self._by_key)
