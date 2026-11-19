"""The chat assistant, with a scripted fake Anthropic client (no network, no API key)."""

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from anthropic.types.beta import BetaMessage

from openclock.assistant import FALLBACK_BETA, Assistant

SAMPLES = Path(__file__).parent.parent / "samples"
TZ = "America/Sao_Paulo"


def message(content, stop_reason, usage=(100, 20)):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 10,
        },
    }


def tool_call(name, arguments, tool_id="tu_1"):
    return message(
        [
            {"type": "thinking", "thinking": "", "signature": "sig-1"},
            {"type": "tool_use", "id": tool_id, "name": name, "input": arguments},
        ],
        "tool_use",
    )


def answer(text):
    return message([{"type": "text", "text": text}], "end_turn")


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    async def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        return BetaMessage.model_validate(self.script.pop(0))


def fake_client(*script):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(script)))


def ask(assistant, text, history=None):
    return asyncio.run(assistant.ask(text, history))


WEEK_ARGS = {"timezone": TZ, "reference_date": "2026-11-18"}


def test_question_is_answered_with_the_mcp_tools():
    client = fake_client(tool_call("summarize_period", WEEK_ARGS), answer("13,44 km no total."))
    reply = ask(Assistant(SAMPLES, TZ, client=client), "Quanto corri nesta semana?")
    assert reply.text == "13,44 km no total."
    assert reply.tools_used == ["summarize_period"]
    assert reply.stop_reason == "end_turn"

    first, second = client.beta.messages.requests
    assert first["model"] == "claude-opus-5-5"
    assert first["output_config"] == {"effort": "medium"}
    assert first["betas"] == [FALLBACK_BETA] and first["fallbacks"] == "default"
    assert first["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in first  # always on for this model; never sent
    assert [t["name"] for t in first["tools"]] == [
        "compare_periods",
        "goal_progress",
        "list_workouts",
        "summarize_period",
    ]
    assert "Use these tools as the only source of numbers" in first["system"]
    assert "America/Sao_Paulo" in first["system"]

    # The tool result fed back to the model holds the real totals from samples/.
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "tu_1"
    data = json.loads(result["content"])
    assert data["combined"]["distance_km"] == 13.44
    # The thinking block is passed back unchanged.
    assert second["messages"][1]["content"][0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig-1",
    }


def test_usage_is_summed_over_the_tool_loop():
    client = fake_client(tool_call("summarize_period", WEEK_ARGS), answer("ok"))
    usage = ask(Assistant(SAMPLES, TZ, client=client), "?").usage
    assert (usage.model_calls, usage.input_tokens, usage.output_tokens) == (2, 200, 40)
    assert usage.cache_read_input_tokens == 100


def test_history_is_append_only_across_turns():
    client = fake_client(answer("Oi!"), answer("De nada."))
    assistant = Assistant(SAMPLES, TZ, client=client)
    first = ask(assistant, "Olá")
    second = ask(assistant, "Obrigado", first.messages)
    assert second.messages[: len(first.messages)] == first.messages
    assert [m["role"] for m in second.messages] == ["user", "assistant", "user", "assistant"]


def test_tool_error_is_returned_to_the_model_as_is_error():
    client = fake_client(
        tool_call("summarize_period", {"timezone": "Mars/Base"}), answer("Qual é o seu fuso?")
    )
    ask(Assistant(SAMPLES, TZ, client=client), "?")
    result = client.beta.messages.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "Unknown time zone" in result["content"]


def test_refusal_gives_a_safe_reply():
    client = fake_client(message([], "refusal"))
    reply = ask(Assistant(SAMPLES, TZ, client=client), "?")
    assert reply.stop_reason == "refusal"
    assert reply.text == "I can't help with that request."


def test_tool_loop_is_bounded():
    calls = [tool_call("list_workouts", WEEK_ARGS, f"tu_{i}") for i in range(3)]
    client = fake_client(*calls)
    reply = ask(Assistant(SAMPLES, TZ, client=client, max_tool_rounds=3), "?")
    assert reply.stop_reason == "max_tool_rounds"
    assert len(client.beta.messages.requests) == 3


def test_operator_can_choose_another_model(monkeypatch):
    monkeypatch.setenv("OPENCLOCK_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("OPENCLOCK_EFFORT", "low")
    client = fake_client(answer("ok"))
    ask(Assistant(SAMPLES, TZ, client=client), "?")
    request = client.beta.messages.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"] == {"effort": "low"}
    assert "fallbacks" not in request  # no server-side fallback for this model
