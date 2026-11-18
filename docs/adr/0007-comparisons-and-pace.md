# 0007. Equivalent-period comparisons and distance-weighted pace

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

"How did my distance, duration and pace change since last week?" can be answered misleadingly: by comparing a full week with a partial one, a 31-day month with a 30-day one without saying so, or by averaging per-run paces so that a 2 km jog counts as much as a 15 km long run.

## Decision

- `compare_periods` compares a period only with its **equivalent predecessor**:
  - week → previous ISO week;
  - month → previous calendar month. The lengths can differ, so the response notes the number of days on each side. Totals are not normalized per day, because a calendar month is what users mean by "last month";
  - custom range → the same number of days immediately before it.
  
  `metrics.compare` refuses periods of different kinds, or custom periods of different lengths.
- **Average pace** = total duration ÷ total distance, over workouts that have both metrics and a distance above zero. The response includes how many workouts the pace is based on.
- Changes are reported as absolute and percentage values. Percentages are undefined (`"unavailable"`) when the previous value is 0. Pace change is in seconds per km, labelled `faster`, `slower` or `same` (same = less than 0.5 s/km).
- Under the `flag` policy, duplicates in either period withhold the combined comparison. Per-source changes are still returned.

## Consequences

- An in-progress week is compared with a complete previous week. The assistant should mention that the current week is not over; a "to date" comparison may be added later if users ask for it.
- Distance-weighted pace matches how Garmin Connect and most training logs report average pace over multiple activities.
