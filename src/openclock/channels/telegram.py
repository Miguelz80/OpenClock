"""Telegram bot for the messaging pilot (Mode B).

- Commands (/semana, /comparar, /metas) answer from ``openclock.service`` directly: no AI cost.
- Free-form questions go to ``openclock.assistant`` (Claude + the OpenClock MCP tools).
- Only chats listed in the pilot config are served; each maps to its own data folder.
- ``send-weekly`` pushes the weekly report; run it from cron (Telegram needs no templates).

Usage::

    export TELEGRAM_BOT_TOKEN=...   ANTHROPIC_API_KEY=...
    openclock-telegram run --config telegram.toml
    openclock-telegram send-weekly --config telegram.toml

See docs/telegram.md and docs/adr/0009-telegram-bot.md.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2

from openclock import service
from openclock.channels.messages import LANGUAGES, t, week_report
from openclock.library import Library
from openclock.periods import resolve_timezone

log = logging.getLogger("openclock.telegram")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
API_BASE = "https://api.telegram.org"
MAX_MESSAGE = 4000  # Telegram's limit is 4096 characters; keep a margin
MAX_TURNS = 20  # questions per conversation before it is restarted (keeps history append-only)

COMMANDS = {
    "start": "help",
    "help": "help",
    "ajuda": "help",
    "semana": "week",
    "week": "week",
    "comparar": "compare",
    "compare": "compare",
    "metas": "goals",
    "goals": "goals",
    "novo": "new",
    "new": "new",
    "privacidade": "privacy",
    "privacy": "privacy",
}


# --- configuration ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PilotUser:
    chat_id: int
    data_dir: Path
    timezone: str
    language: str = "pt"
    weekly_report: bool = True
    name: str | None = None


def load_config(path: str | Path) -> list[PilotUser]:
    """Read ``[[user]]`` tables from a TOML file. Relative data folders are resolved against
    the config file's folder. Secrets never go in this file."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path.name}: invalid TOML ({exc})") from exc
    users: list[PilotUser] = []
    for i, raw in enumerate(data.get("user", []), start=1):
        where = f"{path.name}: user {raw.get('name') or i}"
        if "token" in raw or "api_key" in raw:
            raise ValueError(f"{where}: secrets belong in environment variables, not here")
        try:
            chat_id = int(raw["chat_id"])
            data_dir = Path(raw["data_dir"])
            timezone = str(raw["timezone"])
        except KeyError as exc:
            raise ValueError(f"{where}: '{exc.args[0]}' is required") from exc
        resolve_timezone(timezone)
        language = raw.get("language", "pt")
        if language not in LANGUAGES:
            raise ValueError(f"{where}: language must be one of {', '.join(LANGUAGES)}")
        if not data_dir.is_absolute():
            data_dir = (path.parent / data_dir).resolve()
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
        raise ValueError(f"{path.name}: each chat_id may appear only once")
    return users


# --- Telegram Bot API ------------------------------------------------------------------------


class TelegramError(RuntimeError):
    pass


class TelegramAPI:
    """Minimal Bot API client (JSON over HTTPS). The token is never logged."""

    def __init__(
        self, token: str, http: httpx2.AsyncClient | None = None, base_url: str = API_BASE
    ):
        if not token:
            raise ValueError(f"Telegram bot token missing; set {TOKEN_ENV}")
        self._url = f"{base_url}/bot{token}"
        self._http = http or httpx2.AsyncClient(timeout=60)

    async def call(self, method: str, **params: Any) -> Any:
        try:
            response = await self._http.post(f"{self._url}/{method}", json=params)
        except httpx2.HTTPError as exc:
            # Re-raise without the URL, which contains the token.
            raise TelegramError(f"{method}: network error ({type(exc).__name__})") from None
        body = response.json()
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', response.status_code)}")
        return body["result"]

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return await self.call("getUpdates", **params)

    async def send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            await self.call("sendMessage", chat_id=chat_id, text=chunk)

    async def send_typing(self, chat_id: int) -> None:
        await self.call("sendChatAction", chat_id=chat_id, action="typing")

    async def close(self) -> None:
        await self._http.aclose()


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Split on line breaks so each chunk fits in one Telegram message."""
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


# --- bot -------------------------------------------------------------------------------------


AssistantFactory = Callable[[PilotUser], Any]


def _default_assistant(user: PilotUser) -> Any:
    from openclock.assistant import Assistant

    return Assistant(user.data_dir, user.timezone)


@dataclass(slots=True)
class _Conversation:
    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0


class Bot:
    def __init__(
        self,
        api: TelegramAPI,
        users: list[PilotUser],
        assistant_factory: AssistantFactory = _default_assistant,
        usage_log: str | Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.api = api
        self.users = {u.chat_id: u for u in users}
        self.assistant_factory = assistant_factory
        self.usage_log = Path(usage_log) if usage_log else None
        self.now = now
        self.max_turns = max_turns
        self._assistants: dict[int, Any] = {}
        self._libraries: dict[int, Library] = {}
        self._conversations: dict[int, _Conversation] = {}

    # reports ----------------------------------------------------------------------------------

    def _library(self, user: PilotUser) -> Library:
        if user.chat_id not in self._libraries:
            self._libraries[user.chat_id] = Library(user.data_dir)
        return self._libraries[user.chat_id]

    def report(self, user: PilotUser, kind: str = "week", previous_week: bool = False) -> str:
        """The text for /semana, /comparar or /metas (or the weekly push)."""
        library = self._library(user)
        local_now = self.now().astimezone(resolve_timezone(user.timezone))
        day = local_now.date() - timedelta(days=7 if previous_week else 0)
        common = {"timezone": user.timezone, "reference_date": day.isoformat()}
        summary = service.summarize_period(library, **common)
        comparison = goals = None
        if kind in ("week", "compare"):
            comparison = service.compare_periods(library, **common)
        if kind in ("week", "goals"):
            goals = service.goal_progress(
                library, as_of=local_now.isoformat(timespec="minutes"), history=0, **common
            )
        if kind == "compare":
            return week_report(user.language, summary, comparison)
        if kind == "goals":
            return week_report(user.language, summary, None, goals)
        return week_report(user.language, summary, comparison, goals)

    async def send_weekly_reports(self, previous_week: bool = True) -> int:
        """Send the weekly report to every user with ``weekly_report = true``."""
        sent = 0
        for user in self.users.values():
            if not user.weekly_report:
                continue
            try:
                await self.api.send_message(
                    user.chat_id, self.report(user, previous_week=previous_week)
                )
                sent += 1
            except (TelegramError, ValueError, FileNotFoundError) as exc:
                log.error("weekly report for %s failed: %s", _chat_label(user.chat_id), exc)
        return sent

    # messages ---------------------------------------------------------------------------------

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        text = message.get("text")
        chat_id = (message.get("chat") or {}).get("id")
        if not text or chat_id is None:
            return
        user = self.users.get(chat_id)
        if user is None:
            log.info("message from a chat that is not in the pilot: %s", _chat_label(chat_id))
            await self.api.send_message(chat_id, t("pt", "not_allowed", chat_id=chat_id))
            return
        await self.handle_text(user, text.strip())

    async def handle_text(self, user: PilotUser, text: str) -> None:
        lang = user.language
        if text.startswith("/"):
            name = text[1:].split()[0].split("@")[0].lower()
            command = COMMANDS.get(name)
            if command == "help":
                await self.api.send_message(user.chat_id, t(lang, "help"))
            elif command == "privacy":
                await self.api.send_message(user.chat_id, t(lang, "privacy"))
            elif command == "new":
                self._conversations.pop(user.chat_id, None)
                await self.api.send_message(user.chat_id, t(lang, "new_conversation"))
            elif command in ("week", "compare", "goals"):
                try:
                    reply = self.report(user, command)
                except (ValueError, FileNotFoundError) as exc:
                    log.error("report for %s failed: %s", _chat_label(user.chat_id), exc)
                    reply = t(lang, "error")
                await self.api.send_message(user.chat_id, reply)
            else:
                await self.api.send_message(user.chat_id, t(lang, "help"))
            return
        await self._answer(user, text)

    async def _answer(self, user: PilotUser, text: str) -> None:
        conversation = self._conversations.setdefault(user.chat_id, _Conversation())
        prefix = ""
        if conversation.turns >= self.max_turns:
            conversation = self._conversations[user.chat_id] = _Conversation()
            prefix = t(user.language, "conversation_reset") + "\n"
        if user.chat_id not in self._assistants:
            self._assistants[user.chat_id] = self.assistant_factory(user)
        try:
            await self.api.send_typing(user.chat_id)
            reply = await self._assistants[user.chat_id].ask(text, conversation.messages)
        except TelegramError:
            raise
        except Exception as exc:  # the AI call or a tool failed; never leave the user hanging
            log.error("assistant failed for %s: %s", _chat_label(user.chat_id), type(exc).__name__)
            await self.api.send_message(user.chat_id, t(user.language, "error"))
            return
        conversation.messages = reply.messages
        conversation.turns += 1
        self._log_usage(user, reply)
        await self.api.send_message(user.chat_id, prefix + reply.text)

    def _log_usage(self, user: PilotUser, reply: Any) -> None:
        """Append token counts (never message text) for cost tracking."""
        if self.usage_log is None:
            return
        usage = reply.usage
        entry = {
            "ts": self.now().astimezone(UTC).isoformat(timespec="seconds"),
            "chat": _chat_label(user.chat_id),
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

    async def run_forever(self, poll_timeout: int = 30) -> None:
        offset: int | None = None
        log.info("polling for %d pilot chat(s)", len(self.users))
        while True:
            try:
                updates = await self.api.get_updates(offset, poll_timeout)
            except TelegramError as exc:
                log.warning("getUpdates failed: %s; retrying in 5 s", exc)
                await asyncio.sleep(5)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    await self.handle_update(update)
                except TelegramError as exc:
                    log.warning("sending a reply failed: %s", exc)


def _chat_label(chat_id: int) -> str:
    """A short, stable pseudonym for logs."""
    return hashlib.sha256(str(chat_id).encode()).hexdigest()[:12]


# --- usage summary ---------------------------------------------------------------------------


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


# --- command line ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openclock-telegram", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Answer messages (long polling)")
    run.add_argument("--config", required=True)
    run.add_argument("--usage-log", default="openclock-usage.jsonl")
    weekly = sub.add_parser("send-weekly", help="Send the weekly report (run it from cron)")
    weekly.add_argument("--config", required=True)
    weekly.add_argument(
        "--current-week", action="store_true", help="Report the current week, not the last one"
    )
    preview = sub.add_parser("preview", help="Print a report locally; no Telegram needed")
    preview.add_argument("--config", required=True)
    preview.add_argument("--chat-id", type=int, help="Default: the first user in the config")
    preview.add_argument("--kind", choices=["week", "compare", "goals"], default="week")
    preview.add_argument("--as-of", help="Pretend it is this ISO date-time (for demos)")
    usage = sub.add_parser("usage", help="Summarize token usage (and cost, given prices)")
    usage.add_argument("--usage-log", default="openclock-usage.jsonl")
    usage.add_argument("--price-input", type=float, help="USD per million input tokens")
    usage.add_argument("--price-output", type=float, help="USD per million output tokens")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx2 logs request URLs at INFO level, and Telegram URLs contain the bot token.
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    try:
        if args.command == "usage":
            print(
                json.dumps(
                    summarize_usage(args.usage_log, args.price_input, args.price_output), indent=2
                )
            )
            return 0
        users = load_config(args.config)
        if args.command == "preview":
            user = (
                next((u for u in users if u.chat_id == args.chat_id), None)
                if args.chat_id
                else (users[0] if users else None)
            )
            if user is None:
                print("error: no such user in the config", file=sys.stderr)
                return 2
            now = (
                (lambda: datetime.fromisoformat(args.as_of))
                if args.as_of
                else (lambda: datetime.now(UTC))
            )
            bot = Bot(api=None, users=users, now=now)  # type: ignore[arg-type]
            print(bot.report(user, args.kind))
            return 0
        api = TelegramAPI(os.environ.get(TOKEN_ENV, ""))
        if args.command == "send-weekly":
            sent = asyncio.run(Bot(api, users).send_weekly_reports(not args.current_week))
            print(f"sent {sent} weekly report(s)")
            return 0
        asyncio.run(Bot(api, users, usage_log=args.usage_log).run_forever())
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
