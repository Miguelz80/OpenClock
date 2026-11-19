# Testing

## Setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"   # includes the bot dependencies used in tests
```

## Run the checks

```bash
pytest            # tests
ruff check .      # lint
ruff format .     # format (CI runs `ruff format --check .`)
```

CI runs the same commands on Python 3.11, 3.12 and 3.13 for every pull request (`.github/workflows/ci.yml`).

## What is covered

| Area | Test file | What it guarantees |
|---|---|---|
| Normalized record | `tests/test_models.py` | Start times are stored in UTC, naive or negative values are rejected, missing metrics stay `None`. |
| Periods | `tests/test_periods.py` | Weeks run Monday to Monday in the user's time zone; months and the previous equivalent week, month (across the year boundary) or custom range; a Sunday-night run in São Paulo is not counted in the next UTC week; DST weeks have correct length; end bounds are exclusive. |
| Store | `tests/test_store.py` | Re-importing the same records replaces them, so totals do not change. |
| Metrics | `tests/test_metrics.py` | Totals per source; pace is total time over total distance of complete workouts; deltas and percentage changes; comparisons refuse different kinds of periods; missing metrics are counted, not zeroed; possible duplicates across devices are flagged and the combined total is withheld until a policy is chosen. |
| Garmin FIT importer | `tests/test_importer_fit.py` | The committed sample matches the generator; meters and seconds keep FIT precision; re-imports and renamed copies keep the same IDs; missing distance or duration is `None`; multisport files give one workout per session; corrupted or non-FIT files are rejected. |
| Apple Health importer | `tests/test_importer_apple.py` | The committed sample matches the generator; `km`/`mi`/`m`/`yd` and `min`/`s`/`hr` are converted; both the `WorkoutStatistics` and legacy `totalDistance` formats are read; `.zip` exports work; unknown units become unavailable with a warning; malformed XML and entity-expansion attacks are rejected. |
| Goals | `tests/test_goals.py` | Parsing and validation of goals and pace targets (`"5:30"`); `goals.toml` loading; every status (`on_track`, `behind`, `met`, `not_met`, `in_progress`, `not_started`, `no_data`, `unavailable`); `as_of` ignores later workouts; per-source goals; history and recent average; duplicates make combined goals unavailable until a policy is chosen. |
| Report | `tests/test_report.py` | Units (km, `H:MM:SS`) and `unavailable` markers in output. |
| Library | `tests/test_library.py` | A data folder with copies of the same files yields the same workouts; new and deleted files are picked up; unchanged files are not re-parsed; broken files are reported without stopping the import. |
| Service | `tests/test_service.py` | **The milestone questions** answered from `samples/`: 8.42 km + 5.02 km = 13.44 km this week, and +2.84 km (+26.8%), 8 s/km faster than last week, and goal progress from `samples/goals.toml`; month summary and comparison; inline goals override the file; UTC vs São Paulo week boundaries; assumed time zone, missing source and outdated data appear in `notes`; duplicates across devices withhold the combined total; invalid arguments are rejected. |
| MCP server | `tests/test_mcp_server.py` | Both tools are listed as read-only; calls return the expected structured data in-process and through a real `openclock-mcp` stdio subprocess; bad arguments become tool errors. |
| Assistant | `tests/test_assistant.py` | With a scripted fake Claude client: questions are answered through the real MCP tools (tool results carry the sample totals); request settings (model, effort, fallbacks, caching, no `thinking` param); thinking blocks passed back unchanged; append-only history; tool errors returned as `is_error`; refusals; bounded tool loop; model and effort configurable. |
| Telegram | `tests/test_telegram.py` | With a mock Bot API: commands answered without AI (pt-BR and English); chats outside the pilot get no data; free-form questions keep history and log usage without text or chat id; `/novo` and the 20-question restart; weekly push covers the previous week; polling offsets; errors never leak the token; config validation; usage cost summary. |
| CLI | `tests/test_cli.py` | Table and `--json` output, `list` filtering, sample regeneration and error exit codes. |

## Writing tests

- Use synthetic data only. `tests/helpers.py` has `make_workout()` for quick records, `openclock.synthetic.fit_bytes()` builds FIT files in memory and `openclock.synthetic.apple_health_xml()` builds Apple Health exports.
- Prefer one behaviour per test, named after the behaviour (`test_reimport_replaces_instead_of_adding`).
- When you fix a bug, add a test that fails without the fix.
