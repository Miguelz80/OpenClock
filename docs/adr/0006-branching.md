# 0006. One branch per area, merged through pull requests

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

The maintainer wants changes grouped by category (for example "WhatsApp" or "Apple importer"), each easy to find, rather than everything committed directly to `main`.

## Decision

- `main` only receives changes through pull requests whose CI passes.
- Each area or milestone step gets its own branch, named `<type>/<area>`:
  - `docs/…`: documentation and ADRs only
  - `feat/…`: new behaviour (for example `feat/importer-fit`, `feat/mcp-server`, `feat/channel-whatsapp`)
  - `fix/…`, `chore/…`, `ci/…`: bug fixes, maintenance, pipelines
- When one branch depends on another, it is branched from it and its pull request targets it ("stacked" PRs). After the parent merges, GitHub retargets the child to `main`.
- Documentation is updated in the same commit that changes behaviour.

## Consequences

- History per area is easy to browse (`git log main -- src/openclock/importers/`, or the PR list).
- Stacked PRs must be merged in order. Each PR description names its parent.
- Branch protection on `main` (require PR and passing checks) should be enabled in the GitHub repository settings by the maintainer.
