# MCP server

`openclock-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io/) server that runs over **stdio** and exposes two **read-only** tools. It is built on the official MCP Python SDK (v2, `MCPServer`).

## Running

```bash
openclock-mcp --data-dir /path/to/exports --timezone America/Sao_Paulo
```

| Option | Environment variable | Meaning |
|---|---|---|
| `--data-dir` | `OPENCLOCK_DATA_DIR` | Folder scanned (recursively) for `.fit`, `.xml` and `.zip` files. Hidden files and folders are skipped. |
| `--timezone` | `OPENCLOCK_TIMEZONE` | Default IANA time zone for week boundaries. Each tool call can override it. Without one, UTC is used and the response says so. |

The folder is re-scanned on every call. Files are re-parsed only when their size or modification time changes, so new exports can be dropped in while the server runs.

## Connecting a client

Use absolute paths. Example for clients configured with an `mcpServers` JSON block, such as Claude Desktop:

```json
{
  "mcpServers": {
    "openclock": {
      "command": "/absolute/path/to/OpenClock/.venv/bin/openclock-mcp",
      "args": ["--data-dir", "/absolute/path/to/OpenClock/samples", "--timezone", "America/Sao_Paulo"]
    }
  }
}
```

Claude Code:

```bash
claude mcp add openclock -- /absolute/path/to/OpenClock/.venv/bin/openclock-mcp --data-dir /absolute/path/to/OpenClock/samples --timezone America/Sao_Paulo
```

> The server is tested over stdio with the SDK's own client (`tests/test_mcp_server.py::test_stdio_server_end_to_end`). It has **not yet been tried in a specific desktop app**; please report results in an issue.

## Tools

Both tools take the same period arguments:

| Argument | Default | Meaning |
|---|---|---|
| `timezone` | `OPENCLOCK_TIMEZONE`, else UTC | IANA zone such as `America/Sao_Paulo` |
| `reference_date` | today in `timezone` | Selects the ISO week (Monday to Sunday) containing this day |
| `start_date`, `end_date` | — | A custom inclusive range (`YYYY-MM-DD`). Give both, or neither. |

### `summarize_period`

Totals per source for the period.

| Extra argument | Default | Meaning |
|---|---|---|
| `sport` | `running` | `running`, `walking`, `cycling`, `swimming`, `other` or `all` |
| `duplicate_policy` | `flag` | `flag` withholds the combined total when possible duplicates exist; `count_all`, `prefer_garmin`, `prefer_apple_health` combine anyway, as chosen by the user |

Response (abridged, from the demo samples):

```json
{
  "period": {"kind": "week", "timezone": "America/Sao_Paulo",
             "first_day": "2026-11-16", "last_day": "2026-11-22", "...": "..."},
  "sport": "running",
  "by_source": {
    "garmin":       {"workout_count": 1, "distance_km": 8.42, "duration": "0:45:10", "...": "..."},
    "apple_health": {"workout_count": 1, "distance_km": 5.02, "duration": "0:28:45", "...": "..."}
  },
  "sources_without_data": [],
  "possible_duplicates": [],
  "combined": {"workout_count": 2, "distance_km": 13.44, "duration": "1:13:55", "...": "..."},
  "combined_withheld_reason": null,
  "workouts": [{"source": "garmin", "source_file": "garmin_run_2026-11-17.fit", "...": "..."}],
  "data_status": {"garmin": {"files": ["..."], "latest_workout_start": "2026-11-17T06:30:00-03:00"}},
  "notes": []
}
```

- Missing metrics are the string `"unavailable"`, never `0`.
- `notes` lists, in plain language, everything an answer should mention: an assumed time zone, workouts missing distance or duration, sources with no files, data that ends before the period (possibly outdated export), files that failed to import, and withheld combined totals.

### `list_workouts`

The workouts in the period, each with source, `source_id`, local and UTC start, duration, distance, `unavailable_metrics` and `source_file`.

| Extra argument | Default | Meaning |
|---|---|---|
| `source` | all | `garmin` or `apple_health` |
| `sport` | `all` | as above |

## Server instructions

The server sends instructions to the assistant: use the tools as the only source of numbers; always state the period, time zone and source; mention unavailable metrics and notes; ask before combining sources when duplicates are flagged; compare equivalent periods; refer questions about pain, injury or diagnosis to a professional. See `INSTRUCTIONS` in [`src/openclock/mcp_server.py`](../src/openclock/mcp_server.py).

## Errors

Invalid arguments (unknown time zone, half a date range, unknown sport or policy) and a missing data folder return an MCP tool error with a message the assistant can relay or correct.
