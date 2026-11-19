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

  source        runs     distance     duration    avg pace
  garmin           1      8.42 km      0:45:10    5:22 /km
  apple_health     1      5.02 km      0:28:45    5:44 /km
  combined         2     13.44 km      1:13:55    5:30 /km

Workouts:
  2026-11-17 06:30  garmin        running       8.42 km      0:45:10    5:22 /km  garmin_run_2026-11-17.fit
  2026-11-19 18:05  apple_health  running       5.02 km      0:28:45    5:44 /km  apple_health_export_sample.xml
```

Add `--json` to see exactly what an assistant receives through MCP. Other useful variants:

```bash
openclock list --data-dir samples --timezone America/Sao_Paulo --week-of 2026-11-18   # every workout, any sport
openclock summary --data-dir samples --timezone UTC --week-of 2026-11-18              # see the time-zone effect
openclock summary --data-dir samples --timezone America/Sao_Paulo --start 2026-11-01 --end 2026-11-30
openclock summary --data-dir samples --timezone America/Sao_Paulo --week-of 2026-11-18 --period month
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
| Garmin pace 5:22 /km | 2710 s ÷ 8.42 km = 321.9 s/km | — |
| Combined pace 5:30 /km | 4435 s ÷ 13.44 km = 330.0 s/km. Total time over total distance, so it is not the mean of 5:22 and 5:44 | — |

What is **not** counted, and why:

- **Sunday 2026-11-15 22:10 run (3.1 km)**: it is 01:10 on Monday in UTC, but Sunday in São Paulo, so it belongs to the previous week. Run the UTC variant above to see Apple Health jump to 2 runs and 8.12 km.
- **Saturday 2026-11-21 walk (3.2 km)**: the summary totals running by default. `openclock list` shows it.

## 4. Compare with the previous week

```bash
openclock compare --data-dir samples --timezone America/Sao_Paulo --week-of 2026-11-18
```

```text
Week 2026-11-16 to 2026-11-22 vs 2026-11-09 to 2026-11-15 (America/Sao_Paulo) · sport: running

  source        metric       previous      current  change
  garmin        workouts            1            1  +0
                distance      7.50 km      8.42 km  +0.92 km (+12.3%)
                duration      0:41:15      0:45:10  +0:03:55
                avg pace     5:30 /km     5:22 /km  8 s/km faster
  apple_health  workouts            1            1  +0
                distance      3.10 km      5.02 km  +1.92 km (+61.9%)
                duration      0:18:30      0:28:45  +0:10:15
                avg pace     5:58 /km     5:44 /km  14 s/km faster
  combined      workouts            2            2  +0
                distance     10.60 km     13.44 km  +2.84 km (+26.8%)
                duration      0:59:45      1:13:55  +0:14:10
                avg pace     5:38 /km     5:30 /km  8 s/km faster
```

The previous week (2026-11-09 to 2026-11-15) holds `garmin_run_2026-11-10.fit` (7.50 km, 41:15) and the Sunday-night Apple Health run (3.1 km, 18:30). Check by hand:

| Change | Calculation |
|---|---|
| Distance +2.84 km (+26.8%) | 13.44 − 10.60 = 2.84; 2.84 ÷ 10.60 = 26.8% |
| Duration +0:14:10 | 4435 s − (2475 + 1110) s = 850 s |
| Pace 8 s/km faster | previous 3585 s ÷ 10.60 km = 338.2 s/km (5:38); current 330.0 s/km (5:30); 338.2 − 330.0 = 8.2 |

`--period month` compares November with October. Months can differ in length, and the output says so in its notes. A custom `--start/--end` range is compared with the same number of days right before it.

## 5. Use it from an AI assistant (MCP)

Start the server over stdio:

```bash
openclock-mcp --data-dir samples --timezone America/Sao_Paulo
```

To connect it to an MCP client, see [docs/mcp.md](mcp.md). The client then calls `summarize_period` and answers in plain language with the same numbers as above.

## 6. Re-import and duplicates

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

## 7. Run the tests

```bash
pytest
```

See [docs/testing.md](testing.md) for what each test file covers.
