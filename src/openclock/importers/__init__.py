"""Importers turn one exported file into normalized ``Workout`` records.

Importers never compute totals and know nothing about MCP or channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openclock.models import Workout


class FileImportError(Exception):
    """The file could not be read as the expected format. Nothing from it is imported."""


@dataclass(slots=True)
class ImportResult:
    workouts: list[Workout] = field(default_factory=list)
    #: Non-fatal problems, e.g. a session without a start time that had to be skipped.
    warnings: list[str] = field(default_factory=list)
