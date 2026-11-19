"""WhatsApp adapter: Cloud API calls against a mock Graph server and the webhook in-process."""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path

import httpx2
import pytest
from test_telegram import FakeAssistant

from openclock.channels.core import PilotUser
from openclock.channels.whatsapp import (
    WhatsAppAPI,
    WhatsAppBot,
    WhatsAppError,
    WhatsAppSettings,
    create_app,
    load_config,
    main,
    verify_signature,
)

SAMPLES = Path(__file__).parent.parent / "samples"
WA_ID = "5511900000001"
SETTINGS = WhatsAppSettings(phone_number_id="100000000000001", graph_version="v23.0")
SECRET, VERIFY = "app-secret", "verify-me"
THURSDAY_NIGHT = datetime.fromisoformat("2026-11-20T00:00:00-03:00")
MONDAY_MORNING = datetime.fromisoformat("2026-11-23T08:00:00-03:00")


class FakeGraph:
    def __init__(self, fail=False):
        self.posts = []
        self.fail = fail

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v23.0/100000000000001/messages"
        assert request.headers["authorization"] == "Bearer TEST-TOKEN"
        self.posts.append(json.loads(request.content))
        if self.fail:
            return httpx2.Response(400, json={"error": {"message": "bad", "code": 131047}})
        return httpx2.Response(200, json={"messages": [{"id": "wamid.out"}]})

    def texts(self):
        return [p["text"]["body"] for p in self.posts if p["type"] == "text"]


def make_bot(graph, users=None, now=THURSDAY_NIGHT, **kwargs):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handler))
    api = WhatsAppAPI("TEST-TOKEN", SETTINGS, http=http)
    users = users or [PilotUser(WA_ID, SAMPLES, "America/Sao_Paulo")]
    return WhatsAppBot(
        api, SETTINGS, users, assistant_factory=FakeAssistant, now=lambda: now, **kwargs
    )


def payload(*messages):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "0",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": SETTINGS.phone_number_id},
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


def text(body, sender=WA_ID, message_id="wamid.1"):
    return {"from": sender, "id": message_id, "type": "text", "text": {"body": body}}


def run(coro):
    return asyncio.run(coro)


# --- messages --------------------------------------------------------------------------------


def test_plain_word_commands_answer_without_ai():
    graph = FakeGraph()
    bot = make_bot(graph)
    run(bot.handle_webhook(payload(text("semana"))))
    (body,) = graph.texts()
    assert "Total: 2 treino(s) · 13,44 km · 1:13:55 · 5:30/km" in body
    assert graph.posts[0]["to"] == WA_ID
    assert bot._assistants == {}


def test_help_lists_commands_without_slash():
    graph = FakeGraph()
    run(make_bot(graph).handle_webhook(payload(text("ajuda"))))
    (body,) = graph.texts()
    assert "\nsemana - resumo da semana" in body
    assert "/semana" not in body


def test_questions_go_to_the_assistant():
    graph = FakeGraph()
    bot = make_bot(graph)
    run(bot.handle_webhook(payload(text("quanto corri nesta semana?"))))
    assert graph.texts() == ["answer to: quanto corri nesta semana?"]


def test_repeated_deliveries_are_handled_once():
    graph = FakeGraph()
    bot = make_bot(graph)
    run(bot.handle_webhook(payload(text("semana"))))
    run(bot.handle_webhook(payload(text("semana"))))
    assert len(graph.texts()) == 1


def test_unknown_number_is_told_once_and_gets_no_data():
    graph = FakeGraph()
    bot = make_bot(graph)
    run(bot.handle_webhook(payload(text("semana", sender="5599000000000", message_id="a"))))
    run(bot.handle_webhook(payload(text("semana", sender="5599000000000", message_id="b"))))
    (body,) = graph.texts()
    assert "piloto privado" in body and "km" not in body


def test_non_text_messages():
    graph = FakeGraph()
    audio = {"from": WA_ID, "id": "wamid.a", "type": "audio", "audio": {"id": "1"}}
    run(make_bot(graph).handle_webhook(payload(audio)))
    assert graph.texts() == ["Por enquanto eu só entendo mensagens de texto."]


def test_status_updates_and_other_objects_are_ignored():
    graph = FakeGraph()
    bot = make_bot(graph)
    statuses = payload()
    statuses["entry"][0]["changes"][0]["value"]["statuses"] = [{"id": "x", "status": "read"}]
    run(bot.handle_webhook(statuses))
    run(bot.handle_webhook({"object": "page", "entry": []}))
    assert graph.posts == []


def test_long_replies_are_split():
    graph = FakeGraph()
    api = WhatsAppAPI(
        "TEST-TOKEN",
        SETTINGS,
        http=httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handler)),
    )
    run(api.send_text(WA_ID, "linha\n" * 2000))
    assert len(graph.posts) > 1
    assert all(len(p["text"]["body"]) <= 4096 for p in graph.posts)


def test_api_errors_do_not_leak_the_token():
    graph = FakeGraph(fail=True)
    api = WhatsAppAPI(
        "TEST-TOKEN",
        SETTINGS,
        http=httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handler)),
    )
    with pytest.raises(WhatsAppError) as exc:
        run(api.send_text(WA_ID, "oi"))
    assert "131047" in str(exc.value) and "TEST-TOKEN" not in str(exc.value)


# --- weekly template -------------------------------------------------------------------------


def test_weekly_report_is_a_template_with_short_parameters():
    graph = FakeGraph()
    users = [
        PilotUser(WA_ID, SAMPLES, "America/Sao_Paulo"),
        PilotUser("5511900000002", SAMPLES, "America/Sao_Paulo", language="en"),
        PilotUser("5511900000003", SAMPLES, "America/Sao_Paulo", weekly_report=False),
    ]
    bot = make_bot(graph, users=users, now=MONDAY_MORNING)
    assert run(bot.send_weekly_reports()) == 2
    pt, en = graph.posts
    assert pt["type"] == "template"
    assert pt["template"]["name"] == "openclock_weekly_report"
    assert pt["template"]["language"] == {"code": "pt_BR"}
    params = [p["text"] for p in pt["template"]["components"][0]["parameters"]]
    assert params == ["16/11 a 22/11", "13,44 km", "2", "5:30/km", "+2,84 km (+26,8%)"]
    en_params = [p["text"] for p in en["template"]["components"][0]["parameters"]]
    assert en["template"]["language"] == {"code": "en_US"}
    assert en_params == ["Nov 16 to Nov 22", "13.44 km", "2", "5:30/km", "+2.84 km (+26.8%)"]
    for value in params + en_params:
        assert "\n" not in value and "    " not in value


# --- webhook server --------------------------------------------------------------------------


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def call(app, method, path, **kwargs):
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(method, path, **kwargs)


def test_webhook_verification_handshake():
    app = create_app(make_bot(FakeGraph()), VERIFY, SECRET)
    ok = run(
        call(
            app,
            "GET",
            "/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"},
        )
    )
    assert (ok.status_code, ok.text) == (200, "12345")
    bad = run(
        call(
            app,
            "GET",
            "/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
        )
    )
    assert bad.status_code == 403


def test_signed_webhook_is_processed():
    graph = FakeGraph()
    app = create_app(make_bot(graph), VERIFY, SECRET)
    body = json.dumps(payload(text("metas"))).encode()
    response = run(
        call(
            app,
            "POST",
            "/webhook",
            content=body,
            headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"},
        )
    )
    assert response.status_code == 200
    (reply,) = graph.texts()
    assert "Metas:" in reply


@pytest.mark.parametrize("signature", [None, "sha256=deadbeef", "sha1=abc"])
def test_unsigned_or_forged_webhook_is_rejected(signature):
    graph = FakeGraph()
    app = create_app(make_bot(graph), VERIFY, SECRET)
    body = json.dumps(payload(text("semana"))).encode()
    headers = {"X-Hub-Signature-256": signature} if signature else {}
    response = run(call(app, "POST", "/webhook", content=body, headers=headers))
    assert response.status_code == 401
    assert graph.posts == []


def test_signature_with_another_secret_fails():
    body = b"{}"
    assert verify_signature(body, sign(body), SECRET)
    assert not verify_signature(body, sign(body, "other"), SECRET)


def test_app_requires_secrets():
    with pytest.raises(ValueError, match="WHATSAPP_VERIFY_TOKEN"):
        create_app(make_bot(FakeGraph()), "", SECRET)


# --- config and CLI --------------------------------------------------------------------------


def test_load_config():
    settings, (user,) = load_config(SAMPLES / "whatsapp.example.toml")
    assert settings.phone_number_id == "100000000000001"
    assert settings.template_language["pt"] == "pt_BR"
    assert (user.chat_id, user.timezone) == ("5511900000001", "America/Sao_Paulo")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[whatsapp]\ngraph_version = "v23.0"\n', "'phone_number_id' is required"),
        ('[whatsapp]\nphone_number_id = "1"\ngraph_version = "23"\n', "graph_version"),
        ('[whatsapp]\nphone_number_id="1"\ngraph_version="v23.0"\naccess_token="x"\n', "secrets"),
        (
            '[whatsapp]\nphone_number_id="1"\ngraph_version="v23.0"\n'
            '[[user]]\nwa_id="+55 11 9"\ndata_dir="."\ntimezone="UTC"\n',
            "digits only",
        ),
    ],
)
def test_config_errors(tmp_path, body, message):
    path = tmp_path / "whatsapp.toml"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_template_command(capsys):
    config = str(SAMPLES / "whatsapp.example.toml")
    assert main(["template", "--config", config, "--as-of", "2026-11-20T00:00-03:00"]) == 0
    out = capsys.readouterr().out
    assert "Seu resumo semanal do OpenClock ({{1}})" in out
    assert '"13,44 km"' in out
