"""OpenClock MCP server: read-only workout tools over stdio.

Run it with ``openclock-mcp --data-dir samples --timezone America/Sao_Paulo`` or configure it in
an MCP client (see docs/mcp.md).
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from openclock import __version__, service
from openclock.library import Library

DATA_DIR_ENV = "OPENCLOCK_DATA_DIR"

INSTRUCTIONS = """\
OpenClock gives read-only access to the user's workouts imported from Garmin (.fit) and \
Apple Health (export.xml).
- Use these tools as the only source of numbers. Do not estimate or recompute totals.
- Always state the period (first_day to last_day), the time zone and the source of each number.
- Report metrics marked "unavailable", import errors and items in "notes" (missing or \
possibly outdated data).
- If possible_duplicates is not empty, show the per-source totals, explain the overlap and ask \
the user how to combine before giving a combined total.
- Ask for the user's IANA time zone if a note says UTC was assumed.
- For "how did I change" questions use compare_periods, which always compares equivalent \
periods (week with the previous week, month with the previous month). Quote the changes it \
returns; a lower pace in seconds per km is faster. If the current period has not ended yet, \
say that it is still in progress.
- Do not give medical advice; refer questions about pain, injury or diagnosis to a professional.
"""

_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

TimeZone = Annotated[
    str | None,
    Field(description="IANA time zone, e.g. 'America/Sao_Paulo'. Defaults to OPENCLOCK_TIMEZONE."),
]
StartDate = Annotated[
    str | None, Field(description="First day (inclusive), YYYY-MM-DD. Use with end_date.")
]
EndDate = Annotated[
    str | None, Field(description="Last day (inclusive), YYYY-MM-DD. Use with start_date.")
]
ReferenceDate = Annotated[
    str | None,
    Field(
        description="Without start/end dates: the week or month containing this day. "
        "Defaults to today in the time zone."
    ),
]
PeriodKind = Annotated[
    Literal["week", "month"],
    Field(description="Without start/end dates: ISO week (Mon-Sun) or calendar month."),
]
DuplicatePolicyName = Annotated[
    Literal["flag", "count_all", "prefer_garmin", "prefer_apple_health"],
    Field(
        description="How to combine sources when possible duplicates exist. 'flag' "
        "withholds the combined total; pick another only after asking the user."
    ),
]
SportName = Literal["running", "walking", "cycling", "swimming", "other", "all"]


@contextmanager
def _user_errors() -> Iterator[None]:
    """Turn bad arguments or a missing data folder into a message the assistant can act on."""
    try:
        yield
    except (ValueError, FileNotFoundError) as exc:
        raise ToolError(str(exc)) from exc


def create_server(data_dir: str | Path) -> MCPServer:
    library = Library(data_dir)
    server = MCPServer("OpenClock", instructions=INSTRUCTIONS, version=__version__)

    @server.tool(annotations=_READ_ONLY)
    def list_workouts(
        timezone: TimeZone = None,
        start_date: StartDate = None,
        end_date: EndDate = None,
        reference_date: ReferenceDate = None,
        source: Annotated[
            Literal["garmin", "apple_health"] | None, Field(description="Only this source.")
        ] = None,
        sport: Annotated[SportName, Field(description="Only this sport.")] = "all",
        period: PeriodKind = "week",
    ) -> dict[str, Any]:
        """List workouts in a period (default: this week), with source file, local start time,
        duration, distance, pace and which metrics are unavailable."""
        with _user_errors():
            return service.list_workouts(
                library,
                timezone=timezone,
                start_date=start_date,
                end_date=end_date,
                reference_date=reference_date,
                source=source,
                sport=sport,
                period_kind=period,
            )

    @server.tool(annotations=_READ_ONLY)
    def summarize_period(
        timezone: TimeZone = None,
        start_date: StartDate = None,
        end_date: EndDate = None,
        reference_date: ReferenceDate = None,
        sport: Annotated[SportName, Field(description="Sport to total.")] = "running",
        duplicate_policy: DuplicatePolicyName = "flag",
        period: PeriodKind = "week",
    ) -> dict[str, Any]:
        """Distance, duration, average pace and workout count per source for a period
        (default: this week), possible duplicates across devices, and a combined total when it
        is safe."""
        with _user_errors():
            return service.summarize_period(
                library,
                timezone=timezone,
                start_date=start_date,
                end_date=end_date,
                reference_date=reference_date,
                sport=sport,
                duplicate_policy=duplicate_policy,
                period_kind=period,
            )

    @server.tool(annotations=_READ_ONLY)
    def compare_periods(
        timezone: TimeZone = None,
        start_date: StartDate = None,
        end_date: EndDate = None,
        reference_date: ReferenceDate = None,
        sport: Annotated[SportName, Field(description="Sport to compare.")] = "running",
        duplicate_policy: DuplicatePolicyName = "flag",
        period: PeriodKind = "week",
    ) -> dict[str, Any]:
        """Compare a period (default: this week) with the equivalent period right before it:
        changes in workout count, distance, duration and average pace, per source and combined.
        A custom start/end range is compared with the same number of days before it."""
        with _user_errors():
            return service.compare_periods(
                library,
                timezone=timezone,
                start_date=start_date,
                end_date=end_date,
                reference_date=reference_date,
                sport=sport,
                duplicate_policy=duplicate_policy,
                period_kind=period,
            )

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="openclock-mcp", description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=os.environ.get(DATA_DIR_ENV),
        help=f"Folder with .fit and Apple Health export files (or ${DATA_DIR_ENV}).",
    )
    parser.add_argument(
        "--timezone",
        default=None,
        help=f"Default IANA time zone (or ${service.TIMEZONE_ENV}).",
    )
    args = parser.parse_args(argv)
    if not args.data_dir:
        parser.error(f"--data-dir or {DATA_DIR_ENV} is required")
    if args.timezone:
        os.environ[service.TIMEZONE_ENV] = args.timezone
    create_server(args.data_dir).run()


if __name__ == "__main__":  # pragma: no cover
    main()
