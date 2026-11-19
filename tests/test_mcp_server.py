import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from openclock.mcp_server import create_server

SAMPLES = Path(__file__).parent.parent / "samples"
ARGS = {"timezone": "America/Sao_Paulo", "reference_date": "2026-11-18"}


def _structured(result):
    assert not result.is_error, result.content
    return result.structured_content


def test_tools_are_listed_as_read_only():
    async def run():
        async with Client(create_server(SAMPLES)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == {"list_workouts", "summarize_period", "compare_periods"}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert "timezone" in tool.input_schema["properties"]


def test_summarize_period_over_mcp():
    async def run():
        async with Client(create_server(SAMPLES)) as client:
            return await client.call_tool("summarize_period", ARGS)

    data = _structured(asyncio.run(run()))
    assert data["by_source"]["garmin"]["distance_km"] == 8.42
    assert data["by_source"]["apple_health"]["distance_km"] == 5.02
    assert data["combined"]["distance_km"] == 13.44


def test_list_workouts_over_mcp():
    async def run():
        async with Client(create_server(SAMPLES)) as client:
            return await client.call_tool("list_workouts", ARGS | {"sport": "running"})

    data = _structured(asyncio.run(run()))
    assert data["workout_count"] == 2


def test_compare_periods_over_mcp():
    async def run():
        async with Client(create_server(SAMPLES)) as client:
            return await client.call_tool("compare_periods", ARGS)

    data = _structured(asyncio.run(run()))
    combined = data["changes"]["combined"]
    assert combined["distance_km"] == {
        "current": 13.44,
        "previous": 10.6,
        "change": 2.84,
        "change_pct": 26.8,
    }
    assert combined["avg_pace"]["direction"] == "faster"


def test_invalid_argument_is_a_tool_error():
    async def run():
        async with Client(create_server(SAMPLES)) as client:
            return await client.call_tool("summarize_period", {"timezone": "Mars/Base"})

    result = asyncio.run(run())
    assert result.is_error
    assert "Unknown time zone" in result.content[0].text


def test_stdio_server_end_to_end():
    """Launch `openclock-mcp` as a real subprocess, the way an MCP client does."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "openclock.mcp_server", "--data-dir", str(SAMPLES)],
    )

    async def run():
        async with Client(params) as client:
            return await client.call_tool("summarize_period", ARGS)

    result = asyncio.run(run())
    data = _structured(result) or json.loads(result.content[0].text)
    assert data["combined"]["distance_km"] == 13.44
