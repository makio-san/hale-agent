"""Ollama translation tests. No server and no model download."""

import json

from hale.agent import Agent
from hale.config import Settings
from hale.ollama import OllamaClient


def test_tool_round_trip_uses_local_chat_api(repo):
    seen = []

    def post(url, payload):
        seen.append((url, payload))
        if len(seen) == 1:
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "list_experiments", "arguments": {}}}],
                },
                "prompt_eval_count": 40,
                "eval_count": 8,
            }
        return {
            "message": {"role": "assistant", "content": "Found demo (config/demo-v2.json)."},
            "prompt_eval_count": 70,
            "eval_count": 12,
        }

    client = OllamaClient("http://127.0.0.1:11434", post=post)
    settings = Settings(target_repo=repo, provider="ollama", model="qwen2.5:7b")
    result = Agent(settings, client=client).ask("What experiments exist?")

    assert result.answer == "Found demo (config/demo-v2.json)."
    assert result.input_tokens == 110
    assert result.output_tokens == 20
    assert seen[0][0] == "http://127.0.0.1:11434/api/chat"
    assert seen[0][1]["model"] == "qwen2.5:7b"
    assert any(tool["function"]["name"] == "list_experiments" for tool in seen[0][1]["tools"])
    tool_message = seen[1][1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_name"] == "list_experiments"
    assert json.loads(tool_message["content"])["ok"] is True


def test_string_arguments_are_parsed():
    client = OllamaClient(post=lambda url, payload: {})
    response = client._response(
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "search_reports", "arguments": '{"query": "recall"}'}}],
            }
        }
    )
    call = response.content[0]
    assert call.type == "tool_use"
    assert call.input == {"query": "recall"}
    assert response.stop_reason == "tool_use"


def test_unreachable_server_explains_how_to_start(monkeypatch):
    import urllib.error
    import urllib.request

    from hale.ollama import OllamaError

    def boom(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    client = OllamaClient()
    try:
        client.create(model="qwen2.5:7b", max_tokens=8, system="s", messages=[{"role": "user", "content": "hi"}])
    except OllamaError as exc:
        assert "ollama pull qwen2.5:7b" in str(exc)
    else:
        raise AssertionError("expected OllamaError")
