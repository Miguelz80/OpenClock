"""Command-line interface for manual checks of the numbers the MCP server returns."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from openclock import service
from openclock.library import Library
from openclock.synthetic import write_samples


def _period_line(result: dict[str, Any]) -> str:
    p = result["period"]
    label = "Week" if p["kind"] == "week" else "Period"
    return f"{label} {p['first_day']} to {p['last_day']} ({p['timezone']})"


def _workout_lines(workouts: list[dict[str, Any]]) -> list[str]:
    lines = []
    for w in workouts:
        local = w["start_local"][:16].replace("T", " ")
        km = w["distance_km"]
        distance = f"{km:.2f} km" if isinstance(km, float) else km
        lines.append(
            f"  {local}  {w['source']:<13} {w['sport']:<9} {distance:>11}  "
            f"{w['duration']:>11}  {w['source_file']}"
        )
    return lines


def _totals_line(name: str, t: dict[str, Any]) -> str:
    km = t["distance_km"]
    distance = f"{km:.2f} km" if isinstance(km, float) else km
    return f"  {name:<13} {t['workout_count']:>4}  {distance:>11}  {t['duration']:>11}"


def format_summary(result: dict[str, Any]) -> str:
    lines = [f"{_period_line(result)} · sport: {result['sport']}", ""]
    lines.append(
        f"  {'source':<13} {'runs' if result['sport'] == 'running' else 'n':>4}  "
        f"{'distance':>11}  {'duration':>11}"
    )
    for name, totals in result["by_source"].items():
        lines.append(_totals_line(name, totals))
    if result["combined"]:
        lines.append(_totals_line("combined", result["combined"]))
    else:
        lines.append("  combined      withheld (see notes)")
    if result["possible_duplicates"]:
        lines += ["", "Possible duplicates:"]
        for pair in result["possible_duplicates"]:
            ids = " <-> ".join(f"{w['source']}:{w['source_file']}" for w in pair["workouts"])
            lines.append(f"  {ids}  ({pair['reason']})")
    lines += ["", "Workouts:"] + (_workout_lines(result["workouts"]) or ["  none"])
    if result["notes"]:
        lines += ["", "Notes:"] + [f"  - {n}" for n in result["notes"]]
    return "\n".join(lines)


def format_list(result: dict[str, Any]) -> str:
    lines = [_period_line(result), ""]
    lines += _workout_lines(result["workouts"]) or ["  none"]
    if result["notes"]:
        lines += ["", "Notes:"] + [f"  - {n}" for n in result["notes"]]
    return "\n".join(lines)


def _add_query_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-dir", default=os.environ.get("OPENCLOCK_DATA_DIR", "samples"))
    p.add_argument("--timezone", help="IANA time zone, e.g. America/Sao_Paulo")
    p.add_argument("--week-of", dest="reference_date", help="Any day of the week, YYYY-MM-DD")
    p.add_argument("--start", dest="start_date", help="First day, YYYY-MM-DD (with --end)")
    p.add_argument("--end", dest="end_date", help="Last day, YYYY-MM-DD (with --start)")
    p.add_argument("--json", action="store_true", help="Print the raw JSON the MCP tool returns")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openclock", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="Totals per source for a week or date range")
    _add_query_args(summary)
    summary.add_argument("--sport", default="running")
    summary.add_argument(
        "--duplicates",
        default="flag",
        choices=["flag", "count_all", "prefer_garmin", "prefer_apple_health"],
    )

    listing = sub.add_parser("list", help="Workouts in a week or date range")
    _add_query_args(listing)
    listing.add_argument("--sport", default="all")
    listing.add_argument("--source", choices=["garmin", "apple_health"])

    samples = sub.add_parser("samples", help="(Re)generate the synthetic sample files")
    samples.add_argument("directory", nargs="?", default="samples")

    args = parser.parse_args(argv)
    try:
        if args.command == "samples":
            for path in write_samples(args.directory):
                print(f"wrote {path}")
            return 0
        library = Library(args.data_dir)
        common = dict(
            timezone=args.timezone,
            start_date=args.start_date,
            end_date=args.end_date,
            reference_date=args.reference_date,
        )
        if args.command == "summary":
            result = service.summarize_period(
                library, sport=args.sport, duplicate_policy=args.duplicates, **common
            )
            text = format_summary(result)
        else:
            result = service.list_workouts(library, source=args.source, sport=args.sport, **common)
            text = format_list(result)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
