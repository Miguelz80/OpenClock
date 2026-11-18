# 0005. Duplicate flagging and time-zone-aware periods

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

"How far did I run this week?" has two traps:

1. **Week boundaries depend on the time zone.** A run at 22:00 on Sunday in São Paulo (UTC−3) is 01:00 on Monday in UTC. Grouping in UTC puts it in the wrong week.
2. **The same run can exist in two sources.** A person may wear both watches, or Garmin Connect may sync the run into Apple Health. Adding the two would double the distance.

## Decision

- Periods are computed in the **IANA time zone chosen by the user** (for example `America/Sao_Paulo`). A week is ISO 8601: Monday 00:00 inclusive to the next Monday 00:00 exclusive. The time zone is required by the MCP tools, or taken from `OPENCLOCK_TIMEZONE`. The response always states which time zone was used.
- Two workouts are **possible duplicates** when they come from different sources, have the same sport, and their time ranges overlap for at least 50% of the shorter one. A workout without duration is compared by start time only, within 5 minutes.
- Totals are always reported **per source**. A **combined total** is computed only when no possible duplicates exist, or when the caller explicitly picks a policy:
  - `flag` (default): list duplicates and withhold the combined total.
  - `count_all`: add everything and say so.
  - `prefer_garmin` / `prefer_apple_health`: for each duplicate pair, keep the preferred source.

## Consequences

- The assistant must ask the user before combining sources when duplicates exist. This adds a conversational step, but the answer stays correct.
- Thresholds are heuristics. They are constants in `metrics.py` with tests, and can be tuned with real-world feedback.
