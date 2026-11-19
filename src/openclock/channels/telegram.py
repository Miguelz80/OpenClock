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
import json
import logging
import os
import sys
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

from openclock.channels import core
from openclock.channels.core import (
    MAX_TURNS,
    AssistantFactory,
    ChatCore,
    PilotUser,
    chat_label,
    default_assistant,
    parse_users,
    summarize_usage,
)
from openclock.channels.messages import t

__all__ = [
    "Bot",
    "PilotUser",
    "TelegramAPI",
    "TelegramError",
    "load_config",
    "main",
    "split_message",
    "summarize_usage",
]

log = logging.getLogger("openclock.telegram")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
API_BASE = "https://api.telegram.org"
MAX_MESSAGE = 4000  # Telegram's limit is 4096 characters; keep a margin


def load_config(path: str | Path) -> list[PilotUser]:
    """Read ``[[user]]`` tables (``chat_id``, ``data_dir``, ``timezone``, …) from a TOML file.
    Relative data folders resolve against the config file's folder. No secrets here."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path.name}: invalid TOML ({exc})") from exc
    return parse_users(data.get("user", []), path.name, path.parent, "chat_id", int)


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    return core.split_message(text, limit)


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


# --- bot -------------------------------------------------------------------------------------


class Bot(ChatCore):
    """Telegram transport over the shared chat logic in ``openclock.channels.core``."""

    command_prefix = "/"
    bare_commands = False
    transport_errors = (TelegramError,)

    def __init__(
        self,
        api: TelegramAPI,
        users: list[PilotUser],
        assistant_factory: AssistantFactory = default_assistant,
        usage_log: str | Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_turns: int = MAX_TURNS,
    ) -> None:
        super().__init__(users, assistant_factory, usage_log, now, max_turns)
        self.api = api

    async def send(self, chat_id: Any, text: str) -> None:
        await self.api.send_message(chat_id, text)

    async def typing(self, chat_id: Any) -> None:
        await self.api.send_typing(chat_id)

    async def send_weekly_reports(self, previous_week: bool = True) -> int:
        """Send the weekly report to every user with ``weekly_report = true``."""
        sent = 0
        for user in self.users.values():
            if not user.weekly_report:
                continue
            try:
                await self.send(user.chat_id, self.report(user, previous_week=previous_week))
                sent += 1
            except (TelegramError, ValueError, FileNotFoundError) as exc:
                log.error("weekly report for %s failed: %s", chat_label(user.chat_id), exc)
        return sent

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        text = message.get("text")
        chat_id = (message.get("chat") or {}).get("id")
        if not text or chat_id is None:
            return
        user = self.users.get(chat_id)
        if user is None:
            log.info("message from a chat that is not in the pilot: %s", chat_label(chat_id))
            await self.send(chat_id, t("pt", "not_allowed", chat_id=chat_id))
            return
        await self.handle_text(user, text.strip())

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
