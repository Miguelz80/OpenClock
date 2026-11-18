"""The normalized workout record shared by every importer and interface."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class Source(StrEnum):
    """Where a workout record came from. Sources are never merged or rewritten."""

    GARMIN = "garmin"
    APPLE_HEALTH = "apple_health"


class Sport(StrEnum):
    """Normalized activity type. Importers map platform-specific labels to these values."""

    RUNNING = "running"
    WALKING = "walking"
    CYCLING = "cycling"
    SWIMMING = "swimming"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Workout:
    """One workout, normalized.

    ``duration_s`` and ``distance_m`` are ``None`` when the source does not provide them.
    They are reported as *unavailable*, never as zero.
    """

    source: Source
    source_id: str
    sport: Sport
    start: datetime
    duration_s: float | None
    distance_m: float | None
    source_file: str
    raw_sport: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id must not be empty")
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        # Store every start time in UTC; conversion to the user's zone happens when grouping.
        object.__setattr__(self, "start", self.start.astimezone(UTC))
        for name in ("duration_s", "distance_m"):
            value = getattr(self, name)
            if value is None:
                continue
            value = float(value)
            if math.isnan(value) or math.isinf(value) or value < 0:
                raise ValueError(f"{name} must be a finite, non-negative number or None")
            object.__setattr__(self, name, value)

    @property
    def key(self) -> tuple[Source, str]:
        """Identity used to make re-imports idempotent."""
        return (self.source, self.source_id)

    @property
    def end(self) -> datetime | None:
        if self.duration_s is None:
            return None
        return self.start + timedelta(seconds=self.duration_s)
