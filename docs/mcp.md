# MCP server

`openclock-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io/) server that runs over **stdio** and exposes **read-only** tools: `list_workouts`, `summarize_period`, `compare_periods` and `goal_progress`. It is built on the official MCP Python SDK (v2, `MCPServer`).

## Running

```bash
openclock-mcp --data-dir /path/to/exports --timezone America/Sao_Paulo
```

| Option | Environment variable | Meaning |
|---|---|---|
| `--data-dir` | `OPENCLOCK_DATA_DIR` | Folder scanned (recursively) for `.fit`, `.xml` and `.zip` files. Hidden files and folders are skipped. |
| — | `OPENCLOCK_GOALS_FILE` | Goals file. Default: `goals.toml` inside the data folder. |
| `--timezone` | `OPENCLOCK_TIMEZONE` | Default IANA time zone for week boundaries. Each tool call can override it. Without one, UTC is used and the response says so. |

The folder is re-scanned on every call. Files are re-parsed only when their size or modification time changes, so new exports can be dropped in while the server runs.

## Mode A: install in your own AI app

Mode A runs OpenClock on your computer and plugs it into an AI app you already use. Your workout files never leave your machine, except the numbers the app sends to its own model. OpenClock costs nothing to run this way.

1. **Install** (Python 3.11+):

   ```bash
   git clone https://github.com/Miguelz80/OpenClock.git
   cd OpenClock
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   python -m pip install -e .
   ```

2. **Put your exports in a folder**, e.g. `~/openclock-data`: `.fit` files from Garmin Connect, and `export.xml` or `export.zip` from the Health app. You can add a `goals.toml` (see [`samples/goals.toml`](../samples/goals.toml)). To try it first, use the `samples/` folder.

3. **Check that it works**:

   ```bash
   openclock summary --data-dir ~/openclock-data --timezone America/Sao_Paulo
   ```

4. **Connect your AI app** (use absolute paths):

   - **Claude Desktop:** Settings → Developer → Edit Config, then add:

     ```json
     {
       "mcpServers": {
         "openclock": {
           "command": "/absolute/path/to/OpenClock/.venv/bin/openclock-mcp",
           "args": ["--data-dir", "/absolute/path/to/openclock-data", "--timezone", "America/Sao_Paulo"]
         }
       }
     }
     ```

     On Windows the command is `C:\\path\\to\\OpenClock\\.venv\\Scripts\\openclock-mcp.exe` (backslashes are doubled inside JSON). Restart the app.

   - **Claude Code:**

     ```bash
     claude mcp add openclock -- /absolute/path/to/OpenClock/.venv/bin/openclock-mcp --data-dir /absolute/path/to/openclock-data --timezone America/Sao_Paulo
     ```

   - **Other apps:** any MCP client that can launch a local **stdio** server works with the same command and arguments.

5. **Ask**: "Quanto corri nesta semana em cada fonte?", "Como mudei desde a semana passada?", "Qual meta ficou pendente?"

> The server is tested over stdio with the official SDK client (`tests/test_mcp_server.py::test_stdio_server_end_to_end`). It has **not yet been tried in a specific desktop app**; please report results in an issue.

If you'd rather not install anything, the [Telegram bot](telegram.md) (Mode B) uses the same tools.

## Tools

`list_workouts`, `summarize_period` and `compare_periods` take the same period arguments:

| Argument | Default | Meaning |
|---|---|---|
| `timezone` | `OPENCLOCK_TIMEZONE`, else UTC | IANA zone such as `America/Sao_Paulo` |
| `period` | `week` | `week` (ISO, Monday to Sunday) or `month` (calendar month) |
| `reference_date` | today in `timezone` | Selects the week or month containing this day |
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

- Each totals block also has `avg_pace` (e.g. `"5:30 /km"`), `avg_pace_s_per_km`, `avg_pace_based_on_workouts` and `longest_km`. Average pace is **total time ÷ total distance** over workouts that have both, so longer runs weigh more.
- Missing metrics are the string `"unavailable"`, never `0`.
- `notes` lists, in plain language, everything an answer should mention: an assumed time zone, workouts missing distance or duration, sources with no files, data that ends before the period (possibly outdated export), files that failed to import, and withheld combined totals.

### `compare_periods`

Compares the period with the **equivalent period right before it**: the previous ISO week, the previous calendar month, or the same number of days before a custom range. Same extra arguments as `summarize_period`.

Response: `current` and `previous` (each a full `summarize_period` result, with workouts and source files), plus `changes`:

```json
"changes": {
  "by_source": {"garmin": {"...": "..."}, "apple_health": {"...": "..."}},
  "combined": {
    "workout_count": {"current": 2, "previous": 2, "change": 0},
    "distance_km":   {"current": 13.44, "previous": 10.6, "change": 2.84, "change_pct": 26.8},
    "duration":      {"current": "1:13:55", "previous": "0:59:45", "change": "+0:14:10",
                      "change_s": 850.0, "change_pct": 23.7},
    "avg_pace":      {"current": "5:30 /km", "previous": "5:38 /km",
                      "change_s_per_km": -8.2, "direction": "faster"}
  },
  "combined_withheld_reason": null
}
```

- A negative `change_s_per_km` means faster.
- `change_pct` is `"unavailable"` when the previous value is 0.
- If either period has possible duplicates under the `flag` policy, `combined` is `null` and `combined_withheld_reason` explains why. Per-source changes remain valid.
- `notes` flags months of different lengths and an empty previous period.

### `list_workouts`

The workouts in the period, each with source, `source_id`, local and UTC start, duration, distance, pace, `unavailable_metrics` and `source_file`.

| Extra argument | Default | Meaning |
|---|---|---|
| `source` | all | `garmin` or `apple_health` |
| `sport` | `all` | as above |

### `goal_progress`

Progress towards the user's goals in the week or month that contains `reference_date`.

| Argument | Default | Meaning |
|---|---|---|
| `timezone` | as above | |
| `as_of` | now | Evaluate as of this moment. A date (`2026-11-19`) means the end of that day; a date-time is also accepted. Workouts after `as_of` are ignored. |
| `reference_date` | the day of `as_of` | Any day inside the week or month to evaluate |
| `goals` | goals file | Goals stated by the user in the conversation (they replace the file for this call) |
| `duplicate_policy` | `flag` | As in `summarize_period`. With `flag`, combined goals become `unavailable` when duplicates exist |
| `history` | 4 | Number of previous periods to include (0 to 12) |

A goal:

| Field | Values |
|---|---|
| `metric` | `distance_km`, `duration_min`, `workout_count` (totals); `avg_pace` (met at or below the target); `longest_km` (one workout at least that long) |
| `target` | km, minutes or count; pace as `"M:SS"` per km |
| `per` | `week` (default) or `month` |
| `sport` | default `running` |
| `source` | `combined` (default), `garmin` or `apple_health` |
| `id`, `description` | optional labels |

Each result has `status`, `actual`/`actual_display`, `target`, `progress_pct`, `elapsed_pct`, `expected_by_now` (pro-rata target, totals only), `remaining`, `days_left`, `based_on` (the workouts and files used), `history` and `recent` (periods met out of those with data, plus their average).

| Status | Meaning |
|---|---|
| `met` | Target reached (in a period still in progress: reached already) |
| `on_track` / `behind` | Period in progress; the total is at / below the pro-rata target |
| `in_progress` | Pace or longest-run goal not reached yet, period still open |
| `not_met` | Period over, target not reached |
| `not_started` | The period starts after `as_of` |
| `no_data` | The period ends before the first imported workout. Unknown, which is not the same as zero |
| `unavailable` | Cannot be computed: missing metrics, or duplicates not yet resolved |

## Server instructions

The server sends instructions to the assistant: use the tools as the only source of numbers; always state the period, time zone and source; mention unavailable metrics and notes; ask before combining sources when duplicates are flagged; use `compare_periods` for changes over time, so periods are always equivalent; use only goals the user stated, and tie every suggested adjustment to a goal and to the numbers behind it, as a small, gradual option; refer questions about pain, injury or diagnosis to a professional. See `INSTRUCTIONS` in [`src/openclock/mcp_server.py`](../src/openclock/mcp_server.py).

## Errors

Invalid arguments (unknown time zone, half a date range, unknown sport or policy) and a missing data folder return an MCP tool error with a message the assistant can relay or correct.
