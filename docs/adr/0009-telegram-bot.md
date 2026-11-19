# 0009. Telegram bot: Messages API loop over the in-process MCP tools

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

The maintainer wants both modes: people who prefer their own AI app install the MCP server (Mode A), and a hosted chat bot serves everyone else (Mode B, Telegram pilot first, per ADR 0003). The bot needs an LLM, which the operator pays for, and must give the same numbers as Mode A.

## Decision

- **Same tools as Mode A.** `openclock.assistant` connects to `openclock.mcp_server` **in-process** with the MCP client. Model answers in both modes therefore come from identical tool code, schemas and instructions.
- **Claude Messages API with a manual tool loop** (`anthropic` SDK), not Managed Agents. The project is open source and self-hosted: each operator runs the bot next to their participants' data folders, and the tools are local Python calls. Managed Agents would add a beta dependency and session-runtime billing, and its sandbox would still have to call back into the host for every tool. The manual loop also keeps the conversation append-only and is easy to test with a scripted client.
- **Model:** `claude-opus-5-5` by default, with `output_config.effort = "medium"`. The operator can change both with `OPENCLOCK_MODEL` / `OPENCLOCK_EFFORT`. The model choice is a cost/quality decision for the operator, documented in docs/telegram.md.
- **Refusal fallbacks** (`server-side-fallback-2026-07-01`, `fallbacks: "default"`) are on for models that support them. If a safety classifier declines, the API retries on a suitable model within the same call.
- **Prompt caching** (`cache_control` on the request), with tools sorted by name so the prefix is stable.
- **History is append-only.** Every returned block, thinking included, is passed back unchanged. Instead of trimming old turns, a conversation restarts after 20 questions (or on `/novo`).
- **Commands don't use AI.** `/semana`, `/comparar`, `/metas` and the weekly push are formatted straight from `openclock.service`, at no cost and with no model in the loop.
- **Access control:** only chats listed in `telegram.toml` are served, each mapped to its own data folder. Secrets live only in environment variables, and the config loader rejects a token in the file.
- **Cost measurement:** each AI reply appends its token counts (no text, hashed chat id) to a JSONL log. `openclock-telegram usage` turns the log into a cost estimate at prices the operator supplies.

## Consequences

- Operator cost is per free-form question, and the pilot measures it. Reports are free.
- A WhatsApp adapter can reuse `assistant.py` and `channels/messages.py` unchanged. Only the transport, templates and 24-hour-window handling are new.
- In-memory conversations are lost on restart. That is acceptable, even desirable, for privacy in a pilot. A public version needs per-user storage with consent and deletion.
- The real Telegram and Claude APIs are exercised only in the pilot itself. CI uses mocks.
