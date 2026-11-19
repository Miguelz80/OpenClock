# Architecture Decision Records

Each ADR records one decision: the context, what was decided, and its consequences. ADRs are not edited after acceptance. A new ADR supersedes an old one.

| # | Title | Status |
|---|---|---|
| [0001](0001-python.md) | Python as the implementation language | Accepted |
| [0002](0002-mit-license.md) | MIT license | Accepted |
| [0003](0003-channel-strategy.md) | MCP first, Telegram pilot, WhatsApp later | Accepted |
| [0004](0004-data-sources.md) | Manual file import first; no Strava | Accepted |
| [0005](0005-duplicates-and-time-zones.md) | Duplicate flagging and time-zone-aware periods | Accepted |
| [0006](0006-branching.md) | One branch per area, merged through pull requests | Accepted |

To add one, copy [template.md](template.md), give it the next number, and include it in the pull request that implements the decision.
