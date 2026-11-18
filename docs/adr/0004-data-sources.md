# 0004. Manual file import first; no Strava

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

Neither Garmin nor Apple offers a turnkey integration with AI assistants. Research on 2026-11-18 found:

- **Garmin:** the Connect Developer Program has a personal tier (pull-only) and a business tier (Activity/Health APIs with push), which requires approval. A September 2026 report says new access was paused. This has not been confirmed on Garmin's portal.
- **Apple Health:** there is no cloud API. HealthKit data lives on the iPhone and can be read only by an iOS app with user permission, by an iOS Shortcut, or through the manual "Export All Health Data" archive.
- **Garmin → Apple Health:** Garmin Connect can write workouts into Apple Health, so the same run may appear in both sources.
- **Strava:** since November 2024, Strava's API agreement explicitly prohibits using data obtained through its API in AI models or similar applications, and limits showing data to anyone other than the athlete.

## Decision

- Milestone 1 imports **files the user exports manually**: `.fit` from Garmin Connect and `export.xml` from Apple Health.
- **Strava is not used** as a bridge, because its terms conflict with the core purpose of the project.
- Automatic sync (Garmin API, an iOS app or Shortcut) is evaluated in milestone 4, after official access and user consent are confirmed.

## Consequences

- Users need a manual step at first. This is acceptable for validating the value of the answers.
- Importers are file-based and pure, so they are easy to test with synthetic data. API connectors can later reuse them, since the Garmin API also delivers FIT files.
- Duplicate detection is required from day one (see ADR 0005).
- Sources (secondary, to be confirmed):
  [DC Rainmaker on Strava API changes](https://dcrainmaker.com/2024/11/stravas-changes-to-kill-off-apps.html),
  [Garmin Developer Program](https://developer.garmin.com/gc-developer-program/overview),
  [Terra on the Garmin program pause](https://tryterra.co/blog/garmin-connect-developer-program-pause).
