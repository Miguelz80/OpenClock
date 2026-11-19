import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openclock.library import Library
from openclock.synthetic import (
    APPLE_DEMO_FILE,
    GARMIN_DEMO_FILE,
    FitSession,
    fit_bytes,
)

SAMPLES = Path(__file__).parent.parent / "samples"


@pytest.fixture
def data_dir(tmp_path):
    for name in (GARMIN_DEMO_FILE, APPLE_DEMO_FILE):
        shutil.copy(SAMPLES / name, tmp_path / name)
    return tmp_path


def test_loads_both_sources(data_dir):
    library = Library(data_dir)
    library.refresh()
    assert len(library.workouts()) == 4  # 1 Garmin + 3 Apple Health
    assert all(f.error is None for f in library.files)


def test_duplicate_files_do_not_change_the_store(data_dir):
    (data_dir / "copies").mkdir()
    shutil.copy(data_dir / GARMIN_DEMO_FILE, data_dir / "copies" / "again.fit")
    shutil.copy(data_dir / APPLE_DEMO_FILE, data_dir / "copies" / "export.xml")
    library = Library(data_dir)
    library.refresh()
    assert len(library.files) == 4
    assert len(library.workouts()) == 4


def test_new_and_removed_files_are_picked_up(data_dir):
    library = Library(data_dir)
    library.refresh()
    extra = data_dir / "extra.fit"
    extra.write_bytes(fit_bytes([FitSession(datetime(2026, 11, 20, 9, tzinfo=UTC), 600, 2000)]))
    library.refresh()
    assert len(library.workouts()) == 5
    extra.unlink()
    library.refresh()
    assert len(library.workouts()) == 4


def test_unchanged_files_are_not_reimported(data_dir, monkeypatch):
    library = Library(data_dir)
    library.refresh()
    calls = []
    monkeypatch.setattr(library, "_load", lambda path: calls.append(path))
    library.refresh()
    assert calls == []
    target = data_dir / GARMIN_DEMO_FILE
    os.utime(target, ns=(0, target.stat().st_mtime_ns + 1_000_000_000))
    monkeypatch.undo()
    library.refresh()
    assert len(library.workouts()) == 4


def test_bad_files_are_reported_not_fatal(data_dir):
    (data_dir / "broken.fit").write_bytes(b"not fit")
    (data_dir / "notes.xml").write_text("<notes/>")
    (data_dir / ".hidden.fit").write_bytes(b"ignored")
    library = Library(data_dir)
    library.refresh()
    errors = {f.path.name: f.error for f in library.files if f.error}
    assert set(errors) == {"broken.fit", "notes.xml"}
    assert len(library.workouts()) == 4


def test_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        Library(tmp_path / "nope").refresh()
