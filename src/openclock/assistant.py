"""Conversational assistant for chat channels (Mode B), built on the Claude Messages API.

The assistant calls the **same MCP tools** that Mode A exposes. It connects in-process to
``openclock.mcp_server`` with the MCP client, so a chat answer and an answer from the user's own
AI app always come from identical numbers. See docs/adr/0009-telegram-bot.md.

Requires the ``bot`` extra: ``pip install "openclock[bot]"``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import Client

from openclock.mcp_server import INSTRUCTIONS, create_server

MODEL_ENV = "OPENCLOCK_MODEL"
EFFORT_ENV = "OPENCLOCK_EFFORT"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
#: Models that accept server-side refusal fallbacks (``fallbacks="default"``).
_FALLBACK_MODELS = {
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
    "claude-fable-5-2",
    "claude-fable-5-1",
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_ROUNDS = 8

CHAT_GUIDELINES = """\
You are OpenClock's training assistant, answering in a chat app on a phone.
- Reply in the language the user writes in (Brazilian Portuguese if they write Portuguese).
- Keep replies short: a few lines of plain text. No tables and no Markdown headings; simple \
"-" bullets are fine.
- The user's time zone is {timezone}. Pass it as `timezone` to every tool call.
- Use the tools for every number. If a tool returns an error, explain it briefly and ask \
what is needed (for example a time zone or a goal).
"""


@dataclass(slots=True)
class Usage:
    """Token counts for one reply (all model calls in the tool loop)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    model_calls: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.model_calls += 1


@dataclass(slots=True)
class Reply:
    text: str
    #: The full conversation to send next time (append-only; blocks are kept unchanged).
    messages: list[dict[str, Any]]
    stop_reason: str | None
    usage: Usage = field(default_factory=Usage)
    tools_used: list[str] = field(default_factory=list)


class Assistant:
    """Answers questions about one user's workouts with Claude and the OpenClock tools."""

    def __init__(
        self,
        data_dir: str | Path,
        timezone: str,
        client: Any | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
    ) -> None:
        if client is None:
            from anthropic import AsyncAnthropic  # imported lazily: optional dependency

            client = AsyncAnthropic()
        self.client = client
        self.server = create_server(data_dir)
        self.timezone = timezone
        self.model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
        self.effort = effort or os.environ.get(EFFORT_ENV) or DEFAULT_EFFORT
        self.max_tool_rounds = max_tool_rounds
        self.system = INSTRUCTIONS + "\n" + CHAT_GUIDELINES.format(timezone=timezone)

    def _request(self, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> dict:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": self.system,
            "tools": tools,
            "messages": messages,
            "output_config": {"effort": self.effort},
            # Cache the growing conversation prefix (tools + system + history).
            "cache_control": {"type": "ephemeral"},
        }
        if self.model in _FALLBACK_MODELS:
            # If a safety classifier declines, the API retries on a suitable model in-call.
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    async def ask(self, text: str, history: list[dict[str, Any]] | None = None) -> Reply:
        """Answer ``text``, continuing ``history`` (the ``messages`` of a previous Reply)."""
        messages = list(history or []) + [{"role": "user", "content": text}]
        usage, tools_used = Usage(), []
        async with Client(self.server) as mcp:
            listed = (await mcp.list_tools()).tools
            tools = sorted(
                (
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.input_schema,
                    }
                    for t in listed
                ),
                key=lambda t: t["name"],  # deterministic order keeps the prompt cache valid
            )
            response = None
            for _ in range(self.max_tool_rounds):
                response = await self.client.beta.messages.create(**self._request(tools, messages))
                usage.add(response.usage)
                # Keep every block (thinking included) exactly as returned.
                messages.append(
                    {"role": "assistant", "content": [b.to_dict() for b in response.content]}
                )
                if response.stop_reason != "tool_use":
                    break
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    tools_used.append(block.name)
                    results.append(await _run_tool(mcp, block.id, block.name, block.input))
                messages.append({"role": "user", "content": results})
            else:
                return Reply(
                    "I could not finish this answer. Please try a simpler question.",
                    messages,
                    "max_tool_rounds",
                    usage,
                    tools_used,
                )

        assert response is not None
        if response.stop_reason == "refusal":
            text_out = "I can't help with that request."
        else:
            text_out = "\n".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "max_tokens":
                text_out += "\n[reply cut short]"
        return Reply(text_out or "(no answer)", messages, response.stop_reason, usage, tools_used)


async def _run_tool(mcp: Client, tool_use_id: str, name: str, arguments: Any) -> dict[str, Any]:
    result = await mcp.call_tool(name, arguments if isinstance(arguments, dict) else {})
    if result.is_error:
        message = " ".join(getattr(c, "text", "") for c in result.content) or "tool error"
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": message,
            "is_error": True,
        }
    if result.structured_content is not None:
        payload = json.dumps(result.structured_content, ensure_ascii=False)
    else:
        payload = " ".join(getattr(c, "text", "") for c in result.content)
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": payload}
