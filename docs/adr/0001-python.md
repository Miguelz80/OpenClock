# 0001. Python as the implementation language

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

OpenClock needs to decode Garmin FIT files, stream large Apple Health XML exports, compute time-zone-aware totals and expose them over MCP. Contributors are likely to come from data and sports-science backgrounds.

## Decision

Use Python (3.11+) with:

- [`garmin-fit-sdk`](https://pypi.org/project/garmin-fit-sdk/), Garmin's official FIT decoder.
- Standard library `zoneinfo` for time zones and `xml.etree` `iterparse` (through `defusedxml`) for Apple Health.
- The official [MCP Python SDK](https://pypi.org/project/mcp/) (v2, `MCPServer`).
- `pytest` for tests and `ruff` for linting.

## Consequences

- Official SDKs exist for both FIT and MCP, so fewer custom parsers to maintain. The same FIT SDK encodes the synthetic samples, so test files are produced by Garmin's own code rather than a hand-written encoder.
- `garmin-fit-sdk` is distributed under Garmin's FIT Protocol License, not MIT. OpenClock depends on it but does not vendor or modify it.
- Data-analysis libraries (pandas, numpy) are available if later milestones need them, but they are not dependencies today.
- A future iOS companion app (for Apple Health sync) will be Swift. It will send data to the Python core and will not share code with it.
