"""WhatsApp channel over the official WhatsApp Business Platform (Cloud API).

- Incoming messages arrive on a webhook (``serve``); each POST is checked against the app
  secret (``X-Hub-Signature-256``) before anything is read.
- Replies to a user's message are free-form text (inside the 24-hour customer-service window).
- The weekly report is business-initiated, so ``send-weekly`` sends a **pre-approved message
  template** with short parameters; when the user replies, the full report and questions follow
  as normal messages.
- Commands are plain words ("semana", "metas", ...); everything else goes to the assistant.

Never use unofficial WhatsApp libraries: they break WhatsApp's terms. Before a public launch,
confirm Meta's policy on AI assistants and current pricing (docs/adr/0003, docs/whatsapp.md).

Usage::

    export WHATSAPP_ACCESS_TOKEN=... WHATSAPP_APP_SECRET=... WHATSAPP_VERIFY_TOKEN=...
    export ANTHROPIC_API_KEY=...
    openclock-whatsapp serve --config whatsapp.toml --port 8080
    openclock-whatsapp send-weekly --config whatsapp.toml
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import tomllib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx2
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

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
from openclock.channels.messages import TEXT, t

log = logging.getLogger("openclock.whatsapp")

TOKEN_ENV = "WHATSAPP_ACCESS_TOKEN"
APP_SECRET_ENV = "WHATSAPP_APP_SECRET"
VERIFY_TOKEN_ENV = "WHATSAPP_VERIFY_TOKEN"
GRAPH_BASE = "https://graph.facebook.com"
MAX_MESSAGE = 4000  # WhatsApp text bodies are limited to 4096 characters
_GRAPH_VERSION = re.compile(r"^v\d+\.\d+$")

ONLY_TEXT = {
    "pt": "Por enquanto eu só entendo mensagens de texto.",
    "en": "For now I only understand text messages.",
}

#: Suggested body of the weekly template, to register in WhatsApp Manager (category: Utility).
#: Parameters: {{1}} period, {{2}} distance, {{3}} workouts, {{4}} pace, {{5}} change.
TEMPLATE_BODY = {
    "pt": (
        "Seu resumo semanal do OpenClock ({{1}}): {{2}} em {{3}} treino(s), ritmo médio {{4}}. "
        "Em relação à semana anterior: {{5}}. Responda esta mensagem para ver o relatório "
        "completo ou fazer uma pergunta."
    ),
    "en": (
        "Your OpenClock weekly summary ({{1}}): {{2}} in {{3}} workout(s), average pace {{4}}. "
        "Compared with the previous week: {{5}}. Reply to this message for the full report or "
        "to ask a question."
    ),
}


# --- configuration ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WhatsAppSettings:
    phone_number_id: str
    graph_version: str
    weekly_template: str = "openclock_weekly_report"
    template_language: dict[str, str] = field(
        default_factory=lambda: {"pt": "pt_BR", "en": "en_US"}
    )


def load_config(path: str | Path) -> tuple[WhatsAppSettings, list[PilotUser]]:
    """Read the ``[whatsapp]`` table and ``[[user]]`` tables (``wa_id``, ``data_dir``,
    ``timezone``, …). Secrets go in environment variables, never in this file."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path.name}: invalid TOML ({exc})") from exc
    raw = data.get("whatsapp", {})
    if any(k in raw for k in ("token", "access_token", "app_secret", "verify_token")):
        raise ValueError(f"{path.name}: secrets belong in environment variables, not here")
    try:
        settings = WhatsAppSettings(
            phone_number_id=str(raw["phone_number_id"]),
            graph_version=str(raw["graph_version"]),
            weekly_template=str(raw.get("weekly_template", "openclock_weekly_report")),
            template_language={"pt": "pt_BR", "en": "en_US", **raw.get("template_language", {})},
        )
    except KeyError as exc:
        raise ValueError(f"{path.name}: [whatsapp] '{exc.args[0]}' is required") from exc
    if not _GRAPH_VERSION.match(settings.graph_version):
        raise ValueError(f"{path.name}: graph_version must look like 'v23.0'")
    users = parse_users(data.get("user", []), path.name, path.parent, "wa_id", str)
    for user in users:
        if not str(user.chat_id).isdigit():
            raise ValueError(
                f"{path.name}: wa_id must be digits only, with country code (e.g. 5511900000000)"
            )
    return settings, users


# --- Cloud API -------------------------------------------------------------------------------


class WhatsAppError(RuntimeError):
    pass


class WhatsAppAPI:
    """Sends messages through the Cloud API. The access token is sent as a header and is
    never logged or included in errors."""

    def __init__(
        self,
        token: str,
        settings: WhatsAppSettings,
        http: httpx2.AsyncClient | None = None,
        base_url: str = GRAPH_BASE,
    ) -> None:
        if not token:
            raise ValueError(f"WhatsApp access token missing; set {TOKEN_ENV}")
        self._url = f"{base_url}/{settings.graph_version}/{settings.phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http or httpx2.AsyncClient(timeout=30)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http.post(self._url, json=payload, headers=self._headers)
        except httpx2.HTTPError as exc:
            raise WhatsAppError(f"network error ({type(exc).__name__})") from None
        body = response.json() if response.content else {}
        if response.status_code >= 400:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise WhatsAppError(
                f"HTTP {response.status_code}: {error.get('message', 'request failed')} "
                f"(code {error.get('code')})"
            )
        return body

    async def send_text(self, to: str, text: str) -> None:
        for chunk in core.split_message(text, MAX_MESSAGE):
            await self._post(
                {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to,
                    "type": "text",
                    "text": {"preview_url": False, "body": chunk},
                }
            )

    async def send_template(self, to: str, name: str, language: str, params: list[str]) -> None:
        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": name,
                    "language": {"code": language},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": p} for p in params],
                        }
                    ],
                },
            }
        )

    async def close(self) -> None:
        await self._http.aclose()


# --- bot -------------------------------------------------------------------------------------


def _template_text(value: str) -> str:
    """Template parameters may not contain line breaks, tabs or 4+ consecutive spaces."""
    return re.sub(r"\s+", " ", value).strip() or "-"


class WhatsAppBot(ChatCore):
    """WhatsApp transport over the shared chat logic in ``openclock.channels.core``."""

    command_prefix = ""
    bare_commands = True
    transport_errors = (WhatsAppError,)

    def __init__(
        self,
        api: WhatsAppAPI | None,
        settings: WhatsAppSettings,
        users: list[PilotUser],
        assistant_factory: AssistantFactory = default_assistant,
        usage_log: str | Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_turns: int = MAX_TURNS,
    ) -> None:
        super().__init__(users, assistant_factory, usage_log, now, max_turns)
        self.api = api
        self.settings = settings
        self._seen: OrderedDict[str, None] = OrderedDict()  # webhook deliveries can repeat
        self._told_not_allowed: set[str] = set()

    async def send(self, chat_id: Any, text: str) -> None:
        assert self.api is not None
        await self.api.send_text(str(chat_id), text)

    # weekly template -------------------------------------------------------------------------

    def template_params(self, user: PilotUser, previous_week: bool = True) -> list[str]:
        """The five parameters of the weekly template, from the same numbers as the report."""
        lang = user.language
        data = self.report_data(user, previous_week)
        summary = data["summary"]
        period = summary["period"]
        first, last = (
            date.fromisoformat(period["first_day"]),
            date.fromisoformat(period["last_day"]),
        )
        fmt = "%d/%m" if lang == "pt" else "%b %d"
        sep = " a " if lang == "pt" else " to "
        period_text = first.strftime(fmt) + sep + last.strftime(fmt)
        combined = summary["combined"]
        unavailable = t(lang, "unavailable")
        decimal = TEXT[lang]["decimal"]
        if combined is None:
            distance = workouts = pace = unavailable
        else:
            km = combined["distance_km"]
            distance = (
                f"{km:.2f} km".replace(".", decimal) if isinstance(km, float) else unavailable
            )
            workouts = str(combined["workout_count"])
            pace = combined["avg_pace"].replace(" /km", "/km")
        change = unavailable
        changes = data["comparison"]["changes"]["combined"]
        if changes:
            delta, pct = changes["distance_km"]["change"], changes["distance_km"]["change_pct"]
            if isinstance(delta, int | float):
                change = f"{'+' if delta >= 0 else '-'}{abs(delta):.2f} km".replace(".", decimal)
                if isinstance(pct, int | float):
                    pct_text = f"{abs(pct):.1f}".replace(".", decimal)
                    change += f" ({'+' if pct >= 0 else '-'}{pct_text}%)"
        return [_template_text(v) for v in (period_text, distance, workouts, pace, change)]

    async def send_weekly_reports(self, previous_week: bool = True) -> int:
        """Send the weekly template to every user with ``weekly_report = true``."""
        assert self.api is not None
        sent = 0
        for user in self.users.values():
            if not user.weekly_report:
                continue
            try:
                await self.api.send_template(
                    str(user.chat_id),
                    self.settings.weekly_template,
                    self.settings.template_language[user.language],
                    self.template_params(user, previous_week),
                )
                sent += 1
            except (WhatsAppError, ValueError, FileNotFoundError) as exc:
                log.error("weekly template for %s failed: %s", chat_label(user.chat_id), exc)
        return sent

    # webhook ---------------------------------------------------------------------------------

    def _first_time(self, message_id: str) -> bool:
        if message_id in self._seen:
            return False
        self._seen[message_id] = None
        if len(self._seen) > 1000:
            self._seen.popitem(last=False)
        return True

    async def handle_webhook(self, payload: dict[str, Any]) -> None:
        """Process a verified webhook payload (``object: whatsapp_business_account``)."""
        if payload.get("object") != "whatsapp_business_account":
            return
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if change.get("field") != "messages":
                    continue
                for message in value.get("messages", []):
                    try:
                        await self._handle_message(message)
                    except WhatsAppError as exc:
                        log.warning("sending a reply failed: %s", exc)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        sender, message_id = str(message.get("from", "")), str(message.get("id", ""))
        if not sender or not self._first_time(message_id):
            return
        user = self.users.get(sender)
        if user is None:
            log.info("message from a number that is not in the pilot: %s", chat_label(sender))
            if sender not in self._told_not_allowed:  # answer once, not to every message
                self._told_not_allowed.add(sender)
                await self.send(sender, t("pt", "not_allowed", chat_id=sender))
            return
        if message.get("type") != "text":
            await self.send(sender, ONLY_TEXT[user.language])
            return
        text = (message.get("text") or {}).get("body", "").strip()
        if text:
            await self.handle_text(user, text)


def verify_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def create_app(bot: WhatsAppBot, verify_token: str, app_secret: str) -> Starlette:
    """The webhook as an ASGI app: GET for Meta's verification, POST for messages."""
    if not verify_token or not app_secret:
        raise ValueError(f"set {VERIFY_TOKEN_ENV} and {APP_SECRET_ENV}")

    async def verify(request: Request) -> Response:
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and hmac.compare_digest(
            q.get("hub.verify_token", ""), verify_token
        ):
            return PlainTextResponse(q.get("hub.challenge", ""))
        return PlainTextResponse("forbidden", status_code=403)

    async def receive(request: Request) -> Response:
        body = await request.body()
        if not verify_signature(body, request.headers.get("x-hub-signature-256"), app_secret):
            log.warning("rejected a webhook call with a bad signature")
            return PlainTextResponse("invalid signature", status_code=401)
        try:
            payload = json.loads(body)
        except ValueError:
            return PlainTextResponse("invalid JSON", status_code=400)
        # Acknowledge at once; Meta retries deliveries that are not answered quickly.
        return JSONResponse({"ok": True}, background=BackgroundTask(bot.handle_webhook, payload))

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/webhook", verify, methods=["GET"]),
            Route("/webhook", receive, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
        ]
    )


# --- command line ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openclock-whatsapp", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the webhook server")
    serve.add_argument("--config", required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--usage-log", default="openclock-usage.jsonl")
    weekly = sub.add_parser("send-weekly", help="Send the weekly template (run it from cron)")
    weekly.add_argument("--config", required=True)
    weekly.add_argument("--current-week", action="store_true")
    template = sub.add_parser("template", help="Print the weekly template to register with Meta")
    template.add_argument("--config", required=True)
    template.add_argument("--chat-id", help="Show example parameters for this wa_id")
    template.add_argument("--as-of", help="Pretend it is this ISO date-time (for demos)")
    usage = sub.add_parser("usage", help="Summarize token usage (and cost, given prices)")
    usage.add_argument("--usage-log", default="openclock-usage.jsonl")
    usage.add_argument("--price-input", type=float)
    usage.add_argument("--price-output", type=float)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    try:
        if args.command == "usage":
            summary = summarize_usage(args.usage_log, args.price_input, args.price_output)
            print(json.dumps(summary, indent=2))
            return 0
        settings, users = load_config(args.config)
        if args.command == "template":
            now = (
                (lambda: datetime.fromisoformat(args.as_of))
                if args.as_of
                else (lambda: datetime.now(UTC))
            )
            bot = WhatsAppBot(None, settings, users, now=now)
            print(f"Template name: {settings.weekly_template}  ·  category: Utility\n")
            for lang, body in TEMPLATE_BODY.items():
                print(f"[{settings.template_language[lang]}]\n{body}\n")
            user = next((u for u in users if str(u.chat_id) == args.chat_id), None) or (
                users[0] if users else None
            )
            if user:
                params = bot.template_params(user, previous_week=False)
                print("Example parameters: " + json.dumps(params, ensure_ascii=False))
            return 0
        api = WhatsAppAPI(os.environ.get(TOKEN_ENV, ""), settings)
        if args.command == "send-weekly":
            bot = WhatsAppBot(api, settings, users)
            sent = asyncio.run(bot.send_weekly_reports(not args.current_week))
            print(f"sent {sent} weekly template(s)")
            return 0
        import uvicorn

        bot = WhatsAppBot(api, settings, users, usage_log=args.usage_log)
        app = create_app(
            bot, os.environ.get(VERIFY_TOKEN_ENV, ""), os.environ.get(APP_SECRET_ENV, "")
        )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
