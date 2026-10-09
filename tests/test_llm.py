import json
from dataclasses import replace
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest

from app import llm
from app.prompts import Ping


@pytest.fixture
def real(settings):
    return replace(settings, dev_fake=False, ollama_num_ctx=8192, llm_timeout_s=5)


class FakeOllama:
    """An httpx.MockTransport handler that records requests."""

    def __init__(self, replies, tags=None):
        self.replies = list(replies)
        self.tags = tags or [
            {"name": "llama3.1:8b", "model": "llama3.1:8b", "capabilities": ["completion"]}
        ]
        self.chat_bodies = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": self.tags})
        assert request.url.path == "/api/chat"
        self.chat_bodies.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, httpx.Response):
            return reply
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply)


def ok_reply(content='{"ok": true}', done_reason="stop"):
    return {
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": 20,
        "eval_count": 5,
        "total_duration": 1_000_000,
    }


@pytest.fixture
def ollama(monkeypatch):
    def install(replies, tags=None):
        handler = FakeOllama(replies, tags)
        monkeypatch.setattr(llm, "http_transport", httpx.MockTransport(handler))
        return handler

    return install


def ping(real, provider="ollama", model="llama3.1:8b"):
    return llm.chat(provider, model, "Reply with JSON.", 'Set "ok" to true.', Ping, settings=real)


def test_ollama_request_body_matches_ar_7_2(real, ollama):
    handler = ollama([ok_reply()])
    assert ping(real).ok is True
    body = handler.chat_bodies[0]
    assert body == {
        "model": "llama3.1:8b",
        "messages": [
            {"role": "system", "content": "Reply with JSON."},
            {"role": "user", "content": 'Set "ok" to true.'},
        ],
        "stream": False,
        "format": Ping.model_json_schema(),
        "options": {"num_ctx": 8192, "temperature": 0, "num_predict": 3000},
    }


def test_creative_sets_temperature(real, ollama):
    handler = ollama([ok_reply()])
    llm.chat("ollama", "llama3.1:8b", "s", "u", Ping, settings=real, creative=True)
    assert handler.chat_bodies[0]["options"]["temperature"] == 0.8


def test_num_ctx_comes_from_settings(real, ollama):
    handler = ollama([ok_reply()])
    ping(replace(real, ollama_num_ctx=16384))
    assert handler.chat_bodies[0]["options"]["num_ctx"] == 16384


def test_think_only_for_thinking_models(real, ollama):
    tags = [
        {"name": "qwen3:8b", "capabilities": ["completion", "thinking"]},
        {"name": "llama3.1:8b", "capabilities": ["completion"]},
    ]
    handler = ollama([ok_reply(), ok_reply()], tags)
    ping(real, model="qwen3:8b")
    ping(real, model="llama3.1:8b")
    assert handler.chat_bodies[0]["think"] is False
    assert "think" not in handler.chat_bodies[1]


def test_length_done_reason_raises_output_error(real, ollama):
    ollama([ok_reply('{"ok": tr', done_reason="length")])
    with pytest.raises(llm.LLMOutputError):
        ping(real)


def test_invalid_json_twice_raises_after_two_calls(real, ollama):
    handler = ollama([ok_reply("not json"), ok_reply('{"wrong": 1}')])
    with pytest.raises(llm.LLMOutputError):
        ping(real)
    assert len(handler.chat_bodies) == 2


def test_invalid_once_then_valid_succeeds(real, ollama):
    handler = ollama([ok_reply("not json"), ok_reply()])
    assert ping(real).ok is True
    assert len(handler.chat_bodies) == 2


def test_check_rejection_is_retried(real, ollama):
    handler = ollama([ok_reply('{"ok": false}'), ok_reply('{"ok": false}')])

    def check(reply):
        if not reply.ok:
            raise llm.InvalidReply("not ok")
        return reply

    with pytest.raises(llm.LLMOutputError):
        llm.chat("ollama", "llama3.1:8b", "s", "u", Ping, settings=real, check=check)
    assert len(handler.chat_bodies) == 2


def test_refused_connection_raises_unavailable(real, ollama):
    ollama([httpx.ConnectError("refused")])
    with pytest.raises(llm.LLMUnavailable, match="not running"):
        ping(real)


def test_timeout_raises_unavailable(real, ollama):
    ollama([httpx.ReadTimeout("slow")])
    with pytest.raises(llm.LLMUnavailable, match="within"):
        ping(real)


def test_server_error_raises_unavailable(real, ollama):
    ollama([httpx.Response(500, json={"error": "boom"})])
    with pytest.raises(llm.LLMUnavailable):
        ping(real)


def test_unknown_model_raises_unavailable(real, ollama):
    ollama([httpx.Response(404, json={"error": "model not found"})])
    with pytest.raises(llm.LLMUnavailable, match="ollama pull"):
        ping(real)


def test_list_models_leaves_out_remote_entries(real, ollama):
    ollama(
        [],
        tags=[
            {"name": "llama3.1:8b", "model": "llama3.1:8b"},
            {
                "name": "gpt-oss:120b-cloud",
                "remote_host": "https://ollama.com:443",
                "remote_model": "x",
            },
        ],
    )
    options = llm.list_models(real)
    local = [o.model for o in options if o.is_local]
    assert local == ["llama3.1:8b"]
    assert [o.model for o in options if o.provider == "anthropic"] == list(llm.CLAUDE_MODELS)
    assert all("no API key" in o.label for o in options if o.provider == "anthropic")


def test_list_models_without_ollama_still_lists_claude(real, ollama, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm, "http_transport", httpx.MockTransport(refuse))
    options = llm.list_models(replace(real, anthropic_api_key="k"))
    assert [o.provider for o in options] == ["anthropic"] * 3
    assert all("no API key" not in o.label for o in options)


def test_fake_mode_lists_only_fake(settings):
    assert [o.provider for o in llm.list_models(settings)] == ["fake"]


# Claude, with a stub in place of anthropic.Anthropic


class StubAnthropic:
    calls: ClassVar[list] = []
    responses: ClassVar[list] = []

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        StubAnthropic.calls.append(kwargs)
        reply = StubAnthropic.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def claude(monkeypatch):
    StubAnthropic.calls = []

    def install(*responses):
        StubAnthropic.responses = list(responses)
        monkeypatch.setattr(llm.anthropic, "Anthropic", StubAnthropic)
        return StubAnthropic

    return install


def response(stop_reason="end_turn", parsed=None, ok=True):
    if parsed is None and ok:
        parsed = Ping(ok=True)
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=None)


def test_claude_call_shape(real, claude):
    stub = claude(response())
    assert ping(real, "anthropic", "claude-opus-5-5").ok is True
    call = stub.calls[0]
    for forbidden in ("temperature", "top_p", "top_k", "thinking"):
        assert forbidden not in call
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"
    assert call["output_format"] is Ping
    assert call["output_config"] == {"effort": "medium"}
    assert call["max_tokens"] == 16000
    assert call["model"] == "claude-opus-5-5"
    assert call["system"] == "Reply with JSON."


def test_claude_refusal_raises_refused(real, claude):
    claude(response(stop_reason="refusal", ok=False))
    with pytest.raises(llm.LLMRefused):
        ping(real, "anthropic", "claude-opus-5-5")


def test_claude_max_tokens_raises_output_error(real, claude):
    claude(response(stop_reason="max_tokens", ok=False))
    with pytest.raises(llm.LLMOutputError):
        ping(real, "anthropic", "claude-opus-5-5")


def test_claude_missing_output_is_retried_once(real, claude):
    stub = claude(response(ok=False), response(ok=False))
    with pytest.raises(llm.LLMOutputError):
        ping(real, "anthropic", "claude-opus-5-5")
    assert len(stub.calls) == 2


def test_claude_connection_error_raises_unavailable(real, claude):
    claude(llm.anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")))
    with pytest.raises(llm.LLMUnavailable):
        ping(real, "anthropic", "claude-opus-5-5")


def test_errors_carry_titles():
    assert llm.LLMUnavailable.title == "The model could not be reached"
    assert llm.LLMOutputError.title == "The model returned an unusable reply"
    assert llm.LLMRefused.title == "The cloud model declined this request"
    assert issubclass(llm.LLMRefused, llm.LLMError)


def test_fake_ping(settings):
    assert llm.chat("fake", "fake", "s", "u", Ping, settings=settings).ok is True


@pytest.mark.live
def test_live_ping():
    from app.config import load_settings

    s = load_settings()
    provider = s.default_provider
    model = s.ollama_model if provider == "ollama" else s.anthropic_model
    assert ping(s, provider, model).ok is True
