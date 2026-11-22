import json
from pathlib import Path

from openclock.cli import main

SAMPLES = str(Path(__file__).parent.parent / "samples")
BASE = ["--data-dir", SAMPLES, "--timezone", "America/Sao_Paulo", "--week-of", "2026-11-18"]


def test_summary_table(capsys):
    assert main(["summary", *BASE]) == 0
    out = capsys.readouterr().out
    assert "Week 2026-11-16 to 2026-11-22 (America/Sao_Paulo)" in out
    assert "8.42 km" in out and "5.02 km" in out and "13.44 km" in out
    assert "1:13:55" in out


def test_summary_json_matches_mcp_output(capsys):
    assert main(["summary", *BASE, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["combined"]["distance_km"] == 13.44


def test_list(capsys):
    assert main(["list", *BASE, "--source", "apple_health"]) == 0
    out = capsys.readouterr().out
    assert "apple_health_export_sample.xml" in out
    assert "garmin_run" not in out


def test_samples_command(tmp_path, capsys):
    assert main(["samples", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "apple_health_export_sample.xml",
        "garmin_run_2026-11-10.fit",
        "garmin_run_2026-11-17.fit",
    ]


def test_error_exit_code(capsys):
    assert main(["summary", "--data-dir", SAMPLES, "--timezone", "Nowhere/City"]) == 2
    assert "Unknown time zone" in capsys.readouterr().err


def test_compare_table(capsys):
    assert main(["compare", *BASE]) == 0
    out = capsys.readouterr().out
    assert "Week 2026-11-16 to 2026-11-22 vs 2026-11-09 to 2026-11-15" in out
    assert "+2.84 km (+26.8%)" in out
    assert "8 s/km faster" in out


def test_month_period_flag(capsys):
    assert main(["summary", *BASE, "--period", "month"]) == 0
    assert "Month 2026-11-01 to 2026-11-30" in capsys.readouterr().out


def test_goals_command(capsys):
    args = ["goals", "--data-dir", SAMPLES, "--timezone", "America/Sao_Paulo"]
    assert main([*args, "--as-of", "2026-11-19", "--history", "1"]) == 0
    out = capsys.readouterr().out
    assert "Goals as of end of 2026-11-19" in out
    assert "ON TRACK" in out
    assert "remaining 6.56 km in 3 day(s)" in out
    assert main([*args, "--as-of", "2026-11-19", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["goals_from"] == "goals.toml"


def test_check_command(capsys):
    assert main(["check", "--data-dir", SAMPLES, "--timezone", "America/Sao_Paulo"]) == 0
    out = capsys.readouterr().out
    assert "garmin        2 workout(s) from 2 file(s), 2026-11-10 to 2026-11-17" in out
    assert "Goals: weekly-distance" in out
