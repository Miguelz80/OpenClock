"""Loads every supported file in a data directory into a ``WorkoutStore``.

Files are re-read only when their size or modification time changes, so the MCP server can
call ``refresh()`` before every request and still pick up new exports dropped into the folder.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from openclock.importers import FileImportError, ImportResult
from openclock.importers.apple_health import import_apple_health
from openclock.importers.fit import import_fit
from openclock.models import Source, Workout
from openclock.store import WorkoutStore

Importer = Callable[[Path], ImportResult]

IMPORTERS: dict[str, tuple[Source, Importer]] = {
    ".fit": (Source.GARMIN, import_fit),
    ".xml": (Source.APPLE_HEALTH, import_apple_health),
    ".zip": (Source.APPLE_HEALTH, import_apple_health),
}


@dataclass(slots=True)
class FileStatus:
    path: Path
    source: Source
    modified: datetime
    workouts: list[Workout] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


class Library:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.store = WorkoutStore()
        self.files: list[FileStatus] = []
        self._cache: dict[Path, tuple[tuple[int, int], FileStatus]] = {}

    def _candidates(self) -> list[Path]:
        if not self.data_dir.is_dir():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")
        return sorted(
            p
            for p in self.data_dir.rglob("*")
            if p.is_file()
            and p.suffix.lower() in IMPORTERS
            and not any(part.startswith(".") for part in p.relative_to(self.data_dir).parts)
        )

    def _load(self, path: Path) -> FileStatus:
        source, importer = IMPORTERS[path.suffix.lower()]
        stat = path.stat()
        status = FileStatus(path, source, datetime.fromtimestamp(stat.st_mtime, UTC))
        try:
            result = importer(path)
        except (FileImportError, OSError) as exc:
            status.error = str(exc)
        else:
            status.workouts, status.warnings = result.workouts, result.warnings
        return status

    def refresh(self) -> WorkoutStore:
        """Re-scan the directory and rebuild the store. Removed files drop out."""
        files: list[FileStatus] = []
        cache: dict[Path, tuple[tuple[int, int], FileStatus]] = {}
        for path in self._candidates():
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            cached = self._cache.get(path)
            status = cached[1] if cached and cached[0] == signature else self._load(path)
            cache[path] = (signature, status)
            files.append(status)
        store = WorkoutStore()
        for status in files:
            store.add_all(status.workouts)
        self._cache, self.files, self.store = cache, files, store
        return store

    def workouts(self) -> list[Workout]:
        return self.store.all()
