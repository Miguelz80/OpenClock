# Milestone 1 demo: "How far did I run this week on each source?"

This walkthrough runs OpenClock on the synthetic files in [`samples/`](../samples/) and shows how to check every number by hand.

## 1. Install

```bash
git clone https://github.com/Miguelz80/OpenClock.git
cd OpenClock
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## 2. Ask the question from the command line

The CLI calls the same functions as the MCP tools.

```bash
openclock summary --data-dir samples --timezone America/Sao_Paulo --week-of 2026-11-18
```

```text
Week 2026-11-16 to 2026-11-22 (America/Sao_Paulo) · sport: running

  source        runs     distance     duration
  garmin           1      8.42 km      0:45:10
  apple_health     1      5.02 km      0:28:45
  combined         2     13.44 km      1:13:55

Workouts:
  2026-11-17 06:30  garmin        running       8.42 km      0:45:10  garmin_run_2026-11-17.fit
  2026-11-19 18:05  apple_health  running       5.02 km      0:28:45  apple_health_export_sample.xml
```

Add `--json` to see exactly what an assistant receives through MCP. Other useful variants:

```bash
openclock list --data-dir samples --timezone America/Sao_Paulo --week-of 2026-11-18   # every workout, any sport
openclock summary --data-dir samples --timezone UTC --week-of 2026-11-18              # see the time-zone effect
openclock summary --data-dir samples --timezone America/Sao_Paulo --start 2026-11-01 --end 2026-11-30
```

## 3. Check the numbers by hand

| Number | Where it comes from | How to verify |
|---|---|---|
| Garmin 8.42 km | `session.total_distance = 8420.00 m` in `garmin_run_2026-11-17.fit` | `python -c "from garmin_fit_sdk import Decoder, Stream; print(Decoder(Stream.from_file('samples/garmin_run_2026-11-17.fit')).read()[0]['session_mesgs'])"` |
| Garmin 0:45:10 | `session.total_timer_time = 2710 s` (active time; `total_elapsed_time` 2750 s includes a pause) | same command |
| Apple 5.02 km | `<WorkoutStatistics … sum="5.02" unit="km"/>` of the workout starting `2026-11-19 18:05:00 -0300` | open `samples/apple_health_export_sample.xml` |
| Apple 0:28:45 | `duration="28.75" durationUnit="min"`, so 28.75 × 60 = 1725 s | same file |
| Combined 13.44 km | 8.42 + 5.02. No possible duplicates: the runs are on different days | `"possible_duplicates": []` in `--json` |
| Combined 1:13:55 | 2710 s + 1725 s = 4435 s | — |

What is **not** counted, and why:

- **Sunday 2026-11-15 22:10 run (3.1 km)**: it is 01:10 on Monday in UTC, but Sunday in São Paulo, so it belongs to the previous week. Run the UTC variant above to see Apple Health jump to 2 runs and 8.12 km.
- **Saturday 2026-11-21 walk (3.2 km)**: the summary totals running by default. `openclock list` shows it.

## 4. Use it from an AI assistant (MCP)

Start the server over stdio:

```bash
openclock-mcp --data-dir samples --timezone America/Sao_Paulo
```

To connect it to an MCP client, see [docs/mcp.md](mcp.md). The client then calls `summarize_period` and answers in plain language with the same numbers as above.

## 5. Re-import and duplicates

- **Re-importing** a file, or dropping a renamed copy into the data folder, does not change any total. Workouts are keyed by a stable ID (see [architecture](architecture.md#2-normalized-record)).
- **Same run on two devices:** copy the Garmin sample into a new folder with an Apple export of the same run, and the combined total is withheld:

```bash
mkdir -p /tmp/openclock-dup
cp samples/garmin_run_2026-11-17.fit /tmp/openclock-dup/
python - <<'EOF'
from datetime import datetime
from openclock.synthetic import AppleWorkout, apple_health_xml
run = AppleWorkout(datetime.fromisoformat("2026-11-17T06:30:20-03:00"),
                   datetime.fromisoformat("2026-11-17T07:15:30-03:00"), 44.9, 8.39)
open("/tmp/openclock-dup/export.xml", "w").write(apple_health_xml([run]))
EOF
openclock summary --data-dir /tmp/openclock-dup --timezone America/Sao_Paulo --week-of 2026-11-18
openclock summary --data-dir /tmp/openclock-dup --timezone America/Sao_Paulo --week-of 2026-11-18 --duplicates prefer_garmin
```

The first command lists the pair under "Possible duplicates" and prints `combined withheld`. The second keeps the Garmin record and reports 8.42 km.

## 6. Run the tests

```bash
pytest
```

See [docs/testing.md](testing.md) for what each test file covers.
