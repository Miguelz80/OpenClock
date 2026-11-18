# Testing

## Setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
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
| Periods | `tests/test_periods.py` | Weeks run Monday to Monday in the user's time zone; a Sunday-night run in São Paulo is not counted in the next UTC week; DST weeks have correct length; end bounds are exclusive. |
| Store | `tests/test_store.py` | Re-importing the same records replaces them, so totals do not change. |
| Metrics | `tests/test_metrics.py` | Totals per source; missing metrics are counted, not zeroed; possible duplicates across devices are flagged and the combined total is withheld until a policy is chosen. |
| Report | `tests/test_report.py` | Units (km, `H:MM:SS`) and `unavailable` markers in output. |

## Writing tests

- Use synthetic data only. `tests/helpers.py` has `make_workout()` for quick records.
- Prefer one behaviour per test, named after the behaviour (`test_reimport_replaces_instead_of_adding`).
- When you fix a bug, add a test that fails without the fix.
