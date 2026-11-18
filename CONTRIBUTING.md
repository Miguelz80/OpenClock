# Contributing to OpenClock

Thanks for your interest! OpenClock is an early prototype, and small, focused contributions are the most helpful.

## Ground rules

- **Synthetic data only.** Never commit, paste or attach real Garmin or Apple Health exports, GPS routes, credentials or screenshots with personal data, in code, tests, issues or logs.
- **Numbers come from code.** Any figure the assistant reports must be produced by OpenClock's functions and be reproducible from the input files.
- **Docs travel with behaviour.** If a change alters what OpenClock does, update the README or `docs/` in the same commit.
- **No unofficial integrations.** No scraping, unofficial WhatsApp libraries or reverse-engineered APIs.

## Workflow

1. Open or pick an [issue](https://github.com/Miguelz80/OpenClock/issues) describing the use case or problem.
2. Create a branch from `main` named `<type>/<area>` (see [ADR 0006](docs/adr/0006-branching.md)), e.g. `feat/importer-tcx` or `fix/apple-units`.
3. Make your change with tests.
4. Run the checks locally (see below).
5. Open a pull request against `main`, or against the parent branch for stacked work, and explain what changed and how you verified it.

## Development setup

Development setup and test commands are documented in [docs/testing.md](docs/testing.md) once the Python package lands.

## Decisions

Changes with lasting architectural impact need an [ADR](docs/adr/) in the same pull request.

## Language

The repository is written in English so it is accessible to everyone. Issues and discussions in other languages are welcome. A maintainer may reply in English to keep the history searchable.
