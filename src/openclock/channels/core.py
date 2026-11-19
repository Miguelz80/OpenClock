"""Channel-independent chat logic shared by the Telegram and WhatsApp adapters.

A channel adapter only moves text in and out. Everything else lives here: who is allowed,
commands, reports without AI, free-form questions through ``openclock.assistant``,
conversation history, and the token-usage log.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openclock import service
from openclock.channels.messages import LANGUAGES, t, week_report
from openclock.library import Library
from openclock.periods import resolve_timezone

log = logging.getLogger("openclock.chat")

MAX_TURNS = 20  # questions per conversation before it restarts (keeps history append-only)

COMMANDS = {
    "start": "help",
    "help": "help",
    "ajuda": "help",
    "semana": "week",
    "week": "week",
    "resumo": "week",
    "summary": "week",
    "relatorio": "week",
    "relatório": "week",
    "report": "week",
    "comparar": "compare",
    "compare": "compare",
    "metas": "goals",
    "goals": "goals",
    "novo": "new",
    "new": "new",
    "privacidade": "privacy",
    "privacy": "privacy",
}


@dataclass(frozen=True, slots=True)
class PilotUser:
    #: Telegram chat id, or WhatsApp ``wa_id`` (the phone number in international format).
    chat_id: int | str
    data_dir: Path
    timezone: str
    language: str = "pt"
    weekly_report: bool = True
    name: str | None = None


def parse_users(
    items: Iterable[Mapping[str, Any]],
    source_name: str,
    base_dir: Path,
    id_key: str = "chat_id",
    id_type: type = int,
) -> list[PilotUser]:
    """Validate ``[[user]]`` tables. Relative data folders resolve against ``base_dir``."""
    users: list[PilotUser] = []
    for i, raw in enumerate(items, start=1):
        where = f"{source_name}: user {raw.get('name') or i}"
        if any(k in raw for k in ("token", "api_key", "secret", "access_token")):
            raise ValueError(f"{where}: secrets belong in environment variables, not here")
        try:
            chat_id = id_type(raw[id_key])
            data_dir = Path(raw["data_dir"])
            timezone = str(raw["timezone"])
        except KeyError as exc:
            raise ValueError(f"{where}: '{exc.args[0]}' is required") from exc
        resolve_timezone(timezone)
        language = raw.get("language", "pt")
        if language not in LANGUAGES:
            raise ValueError(f"{where}: language must be one of {', '.join(LANGUAGES)}")
        if not data_dir.is_absolute():
            data_dir = (base_dir / data_dir).resolve()
        users.append(
            PilotUser(
                chat_id=chat_id,
                data_dir=data_dir,
                timezone=timezone,
                language=language,
                weekly_report=bool(raw.get("weekly_report", True)),
                name=raw.get("name"),
            )
        )
    ids = [u.chat_id for u in users]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{source_name}: each {id_key} may appear only once")
    return users


def split_message(text: str, limit: int) -> list[str]:
    """Split on line breaks so each chunk fits in one chat message."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current or not chunks:
        chunks.append(current)
    return [c.rstrip("\n") or " " for c in chunks]


def chat_label(chat_id: int | str) -> str:
    """A short, stable pseudonym for logs."""
    return hashlib.sha256(str(chat_id).encode()).hexdigest()[:12]


AssistantFactory = Callable[[PilotUser], Any]
Send = Callable[[Any, str], Awaitable[None]]


def default_assistant(user: PilotUser) -> Any:
    from openclock.assistant import Assistant

    return Assistant(user.data_dir, user.timezone)


@dataclass(slots=True)
class Conversation:
    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0


class ChatCore:
    """Handles text from pilot users. Subclasses provide ``send`` (and optionally ``typing``)."""

    #: Prefix shown before command names in help text ("/" on Telegram, "" on WhatsApp).
    command_prefix = "/"
    #: Accept a single word such as "semana" as a command, not only "/semana".
    bare_commands = False
    #: Errors raised by the transport; they propagate instead of becoming an apology.
    transport_errors: tuple[type[BaseException], ...] = ()

    def __init__(
        self,
        users: Iterable[PilotUser],
        assistant_factory: AssistantFactory = default_assistant,
        usage_log: str | Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.users = {u.chat_id: u for u in users}
        self.assistant_factory = assistant_factory
        self.usage_log = Path(usage_log) if usage_log else None
        self.now = now
        self.max_turns = max_turns
        self._assistants: dict[Any, Any] = {}
        self._libraries: dict[Any, Library] = {}
        self._conversations: dict[Any, Conversation] = {}

    # transport hooks --------------------------------------------------------------------------

    async def send(self, chat_id: Any, text: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def typing(self, chat_id: Any) -> None:
        """Show a 'typing…' indicator where the channel supports it."""

    # reports ----------------------------------------------------------------------------------

    def _library(self, user: PilotUser) -> Library:
        if user.chat_id not in self._libraries:
            self._libraries[user.chat_id] = Library(user.data_dir)
        return self._libraries[user.chat_id]

    def report_data(self, user: PilotUser, previous_week: bool = False) -> dict[str, Any]:
        """Summary, comparison and goals for the user's current (or previous) week."""
        library = self._library(user)
        local_now = self.now().astimezone(resolve_timezone(user.timezone))
        day = local_now.date() - timedelta(days=7 if previous_week else 0)
        common = {"timezone": user.timezone, "reference_date": day.isoformat()}
        return {
            "summary": service.summarize_period(library, **common),
            "comparison": service.compare_periods(library, **common),
            "goals": service.goal_progress(
                library, as_of=local_now.isoformat(timespec="minutes"), history=0, **common
            ),
        }

    def report(self, user: PilotUser, kind: str = "week", previous_week: bool = False) -> str:
        """The text for the week / compare / goals commands (or the weekly push)."""
        data = self.report_data(user, previous_week)
        if kind == "compare":
            return week_report(user.language, data["summary"], data["comparison"])
        if kind == "goals":
            return week_report(user.language, data["summary"], None, data["goals"])
        return week_report(user.language, data["summary"], data["comparison"], data["goals"])

    # messages ---------------------------------------------------------------------------------

    def command_for(self, text: str) -> str | None:
        words = text.split()
        if not words:
            return None
        if text.startswith("/"):
            return COMMANDS.get(words[0][1:].split("@")[0].lower(), "unknown")
        if self.bare_commands and len(words) == 1:
            return COMMANDS.get(words[0].lower().strip("!?.,"))
        return None

    async def handle_text(self, user: PilotUser, text: str) -> None:
        lang = user.language
        command = self.command_for(text)
        if command is None:
            await self._answer(user, text)
        elif command == "privacy":
            await self.send(user.chat_id, t(lang, "privacy"))
        elif command == "new":
            self._conversations.pop(user.chat_id, None)
            await self.send(user.chat_id, t(lang, "new_conversation"))
        elif command in ("week", "compare", "goals"):
            try:
                reply = self.report(user, command)
            except (ValueError, FileNotFoundError) as exc:
                log.error("report for %s failed: %s", chat_label(user.chat_id), exc)
                reply = t(lang, "error")
            await self.send(user.chat_id, reply)
        else:  # help, or an unknown /command
            await self.send(user.chat_id, t(lang, "help", p=self.command_prefix))

    async def _answer(self, user: PilotUser, text: str) -> None:
        conversation = self._conversations.setdefault(user.chat_id, Conversation())
        prefix = ""
        if conversation.turns >= self.max_turns:
            conversation = self._conversations[user.chat_id] = Conversation()
            prefix = t(user.language, "conversation_reset") + "\n"
        if user.chat_id not in self._assistants:
            self._assistants[user.chat_id] = self.assistant_factory(user)
        try:
            await self.typing(user.chat_id)
            reply = await self._assistants[user.chat_id].ask(text, conversation.messages)
        except self.transport_errors:
            raise
        except Exception as exc:  # the AI call or a tool failed; never leave the user hanging
            log.error("assistant failed for %s: %s", chat_label(user.chat_id), type(exc).__name__)
            await self.send(user.chat_id, t(user.language, "error"))
            return
        conversation.messages = reply.messages
        conversation.turns += 1
        self._log_usage(user, reply)
        await self.send(user.chat_id, prefix + reply.text)

    def _log_usage(self, user: PilotUser, reply: Any) -> None:
        """Append token counts (never message text) for cost tracking."""
        if self.usage_log is None:
            return
        usage = reply.usage
        entry = {
            "ts": self.now().astimezone(UTC).isoformat(timespec="seconds"),
            "chat": chat_label(user.chat_id),
            "model": getattr(self._assistants.get(user.chat_id), "model", None),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "model_calls": usage.model_calls,
            "tools": reply.tools_used,
            "stop_reason": reply.stop_reason,
        }
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def summarize_usage(
    path: str | Path, price_input: float | None = None, price_output: float | None = None
) -> dict[str, Any]:
    """Totals from a usage log. Prices are USD per million tokens, given by the operator
    (check the current price list); cache reads and writes are priced at 0.1x / 1.25x input."""
    totals = {
        "replies": 0,
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    chats: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        totals["replies"] += 1
        chats.add(entry["chat"])
        for key in totals:
            if key != "replies":
                totals[key] += entry.get(key, 0)
    result: dict[str, Any] = {**totals, "chats": len(chats)}
    if price_input is not None and price_output is not None:
        cost = (
            totals["input_tokens"] * price_input
            + totals["cache_read_input_tokens"] * price_input * 0.1
            + totals["cache_creation_input_tokens"] * price_input * 1.25
            + totals["output_tokens"] * price_output
        ) / 1_000_000
        result["estimated_cost_usd"] = round(cost, 4)
        result["estimated_cost_per_reply_usd"] = (
            round(cost / totals["replies"], 5) if totals["replies"] else None
        )
    return result
