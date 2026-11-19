"""Telegram adapter with a mock HTTP transport (no network, no real token)."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx2
import pytest

from openclock.assistant import Reply, Usage
from openclock.channels.telegram import (
    Bot,
    PilotUser,
    TelegramAPI,
    TelegramError,
    load_config,
    main,
    split_message,
    summarize_usage,
)

SAMPLES = Path(__file__).parent.parent / "samples"
CHAT = 100000001
THURSDAY_NIGHT = datetime.fromisoformat("2026-11-20T00:00:00-03:00")
MONDAY_MORNING = datetime.fromisoformat("2026-11-23T08:00:00-03:00")


class FakeTelegram:
    """Records Bot API calls and answers them like Telegram would."""

    def __init__(self, updates=None):
        self.calls = []
        self.updates = list(updates or [])

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        assert request.url.path.startswith("/botTEST-TOKEN/")
        params = json.loads(request.content or b"{}")
        self.calls.append((method, params))
        if method == "getUpdates":
            result, self.updates = self.updates, []
            return httpx2.Response(200, json={"ok": True, "result": result})
        return httpx2.Response(200, json={"ok": True, "result": True})

    def sent(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


class FakeAssistant:
    model = "claude-opus-5-5"

    def __init__(self, user):
        self.user = user
        self.questions = []

    async def ask(self, text, history=None):
        self.questions.append((text, list(history or [])))
        messages = list(history or []) + [
            {"role": "user", "content": text},
            {"role": "assistant", "content": [{"type": "text", "text": f"answer {text}"}]},
        ]
        usage = Usage(1000, 200, 500, 100, 2)
        return Reply(f"answer to: {text}", messages, "end_turn", usage, ["summarize_period"])


def make_bot(fake, users=None, now=THURSDAY_NIGHT, **kwargs):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handler))
    api = TelegramAPI("TEST-TOKEN", http=http)
    users = users or [PilotUser(CHAT, SAMPLES, "America/Sao_Paulo")]
    return Bot(api, users, assistant_factory=FakeAssistant, now=lambda: now, **kwargs)


def update(text, chat_id=CHAT, update_id=1):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


def run(coro):
    return asyncio.run(coro)


# --- commands --------------------------------------------------------------------------------


def test_week_command_answers_from_the_data_without_ai():
    fake = FakeTelegram()
    bot = make_bot(fake)
    run(bot.handle_update(update("/semana")))
    (text,) = fake.sent()
    assert "Semana 16/11 a 22/11 (America/Sao_Paulo)" in text
    assert "Garmin: 1 treino(s) · 8,42 km · 0:45:10 · 5:22/km" in text
    assert "Total: 2 treino(s) · 13,44 km · 1:13:55 · 5:30/km" in text
    assert "+2,84 km (+26,8%) · ritmo 8 s/km mais rápido" in text
    assert "NO RITMO (13,44 km / 20,00 km); faltam 6,56 km em 3 dia(s)" in text
    assert bot._assistants == {}  # no AI involved


def test_english_commands():
    fake = FakeTelegram()
    bot = make_bot(fake, users=[PilotUser(CHAT, SAMPLES, "America/Sao_Paulo", language="en")])
    run(bot.handle_update(update("/compare@OpenClockBot")))
    run(bot.handle_update(update("/goals")))
    compare, goals = fake.sent()
    assert "Vs. previous week: +2.84 km (+26.8%) · pace 8 s/km faster" in compare
    assert "Goals:" not in compare
    assert "ON TRACK (13.44 km / 20.00 km); 6.56 km to go in 3 day(s)" in goals


def test_help_privacy_and_unknown_commands():
    fake = FakeTelegram()
    bot = make_bot(fake)
    for text in ("/start", "/privacidade", "/xyz"):
        run(bot.handle_update(update(text)))
    help_text, privacy, unknown = fake.sent()
    assert "/semana" in help_text and unknown == help_text
    assert "API do Claude" in privacy and "profissional" in privacy


def test_chat_outside_the_pilot_gets_no_data():
    fake = FakeTelegram()
    bot = make_bot(fake)
    run(bot.handle_update(update("/semana", chat_id=999)))
    (text,) = fake.sent()
    assert "piloto privado" in text and "999" in text
    assert "km" not in text


def test_non_text_updates_are_ignored():
    fake = FakeTelegram()
    run(make_bot(fake).handle_update({"update_id": 5, "message": {"chat": {"id": CHAT}}}))
    assert fake.calls == []


# --- free-form questions ---------------------------------------------------------------------


def test_questions_go_to_the_assistant_with_history(tmp_path):
    fake = FakeTelegram()
    log = tmp_path / "usage.jsonl"
    bot = make_bot(fake, usage_log=log)
    run(bot.handle_update(update("quanto corri?")))
    run(bot.handle_update(update("e na semana passada?")))
    assert fake.sent() == ["answer to: quanto corri?", "answer to: e na semana passada?"]
    assert ("sendChatAction", {"chat_id": CHAT, "action": "typing"}) in fake.calls
    assistant = bot._assistants[CHAT]
    assert assistant.questions[0][1] == []
    assert len(assistant.questions[1][1]) == 2  # previous turn was passed back

    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(entries) == 2
    assert entries[0]["input_tokens"] == 1000 and entries[0]["tools"] == ["summarize_period"]
    assert str(CHAT) not in log.read_text()  # pseudonymous
    assert "quanto corri" not in log.read_text()  # never the message text


def test_new_command_resets_the_conversation():
    fake = FakeTelegram()
    bot = make_bot(fake)
    run(bot.handle_update(update("oi")))
    run(bot.handle_update(update("/novo")))
    run(bot.handle_update(update("de novo")))
    assert fake.sent()[1] == "Conversa reiniciada."
    assert bot._assistants[CHAT].questions[1][1] == []


def test_long_conversations_restart_instead_of_being_trimmed():
    fake = FakeTelegram()
    bot = make_bot(fake, max_turns=2)
    for text in ("a", "b", "c"):
        run(bot.handle_update(update(text)))
    assert fake.sent()[2].startswith("(A conversa anterior ficou longa e foi reiniciada.)")
    assert bot._assistants[CHAT].questions[2][1] == []


def test_assistant_failure_sends_an_apology():
    class Broken(FakeAssistant):
        async def ask(self, text, history=None):
            raise RuntimeError("API down")

    fake = FakeTelegram()
    bot = make_bot(fake)
    bot.assistant_factory = Broken
    run(bot.handle_update(update("oi")))
    assert fake.sent() == ["Não consegui responder agora. Tente de novo em instantes."]


# --- weekly push -----------------------------------------------------------------------------


def test_weekly_report_on_monday_covers_the_previous_week():
    fake = FakeTelegram()
    users = [
        PilotUser(CHAT, SAMPLES, "America/Sao_Paulo"),
        PilotUser(CHAT + 1, SAMPLES, "America/Sao_Paulo", weekly_report=False),
    ]
    bot = make_bot(fake, users=users, now=MONDAY_MORNING)
    assert run(bot.send_weekly_reports()) == 1
    (text,) = fake.sent()
    assert "Semana 16/11 a 22/11" in text
    assert "NÃO CUMPRIDA (13,44 km / 20,00 km)" in text  # the week is over


def test_polling_loop_processes_updates_once(monkeypatch):
    fake = FakeTelegram(updates=[update("/semana", update_id=41)])
    bot = make_bot(fake)
    calls = {"n": 0}
    original = bot.api.get_updates

    async def get_updates(offset, timeout=30):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return await original(offset, timeout)

    monkeypatch.setattr(bot.api, "get_updates", get_updates)
    with pytest.raises(KeyboardInterrupt):
        run(bot.run_forever(poll_timeout=0))
    offsets = [p.get("offset") for m, p in fake.calls if m == "getUpdates"]
    assert offsets == [None, 42]
    assert len(fake.sent()) == 1


def test_api_errors_do_not_leak_the_token():
    def handler(request):
        raise httpx2.ConnectError("boom", request=request)

    api = TelegramAPI("SECRET", http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    with pytest.raises(TelegramError) as exc:
        run(api.send_message(CHAT, "hi"))
    assert "SECRET" not in str(exc.value)


def test_missing_token():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        TelegramAPI("")


# --- helpers ---------------------------------------------------------------------------------


def test_split_message():
    assert split_message("short") == ["short"]
    chunks = split_message("line\n" * 1000, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(c + "\n" for c in chunks).count("line") == 1000
    assert split_message("x" * 250, limit=100) == ["x" * 100, "x" * 100, "x" * 50]


def test_load_config(tmp_path):
    (users,) = [load_config(SAMPLES / "telegram.example.toml")]
    (user,) = users
    assert (user.chat_id, user.timezone, user.language) == (100000001, "America/Sao_Paulo", "pt")
    assert user.data_dir == SAMPLES.resolve()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[[user]]\nchat_id = 1\ntimezone = "UTC"\n', "'data_dir' is required"),
        ('[[user]]\nchat_id = 1\ndata_dir = "."\ntimezone = "Mars/Base"\n', "Unknown time zone"),
        ('[[user]]\nchat_id=1\ndata_dir="."\ntimezone="UTC"\nlanguage="fr"\n', "language"),
        ('[[user]]\nchat_id=1\ndata_dir="."\ntimezone="UTC"\ntoken="x"\n', "secrets"),
        ('[[user]]\nchat_id=1\ndata_dir="."\ntimezone="UTC"\n' * 2, "only once"),
    ],
)
def test_config_errors(tmp_path, body, message):
    path = tmp_path / "telegram.toml"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_usage_summary_and_cost(tmp_path):
    log = tmp_path / "usage.jsonl"
    entry = {
        "chat": "abc",
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read_input_tokens": 1_000_000,
        "cache_creation_input_tokens": 0,
        "model_calls": 2,
    }
    log.write_text(json.dumps(entry) + "\n" + json.dumps(entry | {"chat": "def"}) + "\n")
    summary = summarize_usage(log, price_input=4, price_output=20)
    assert (summary["replies"], summary["chats"], summary["model_calls"]) == (2, 2, 4)
    # per entry: 1M x $4 + 1M cache reads x $0.40 + 0.1M x $20 = $6.40
    assert summary["estimated_cost_usd"] == 12.8
    assert summary["estimated_cost_per_reply_usd"] == 6.4


def test_preview_command(capsys):
    config = str(SAMPLES / "telegram.example.toml")
    assert main(["preview", "--config", config, "--as-of", "2026-11-20T00:00-03:00"]) == 0
    assert "13,44 km" in capsys.readouterr().out
