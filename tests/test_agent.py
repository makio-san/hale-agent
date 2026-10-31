"""Agent loop tests with a scripted fake client; no network or API key."""

import json
from pathlib import Path
from types import SimpleNamespace

from hale.agent import Agent
from hale.config import Settings


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use(name, inputs, call_id="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=inputs, id=call_id)


def _response(content, stop_reason, tokens=(10, 5)):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


class ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _agent(repo: Path, client, **overrides) -> Agent:
    settings = Settings(target_repo=repo, **overrides)
    return Agent(settings, client=client)


def test_loop_runs_tools_and_returns_final_answer(repo: Path):
    client = ScriptedClient(
        [
            _response([_tool_use("list_experiments", {})], "tool_use"),
            _response([_text("Found demo v2 (config/demo-v2.json).")], "end_turn"),
        ]
    )
    result = _agent(repo, client).ask("What experiments exist?")

    assert result.answer == "Found demo v2 (config/demo-v2.json)."
    assert result.steps == 2
    assert result.stop_reason == "end_turn"
    assert result.input_tokens == 20 and result.output_tokens == 10

    tool_result_msg = client.calls[1]["messages"][2]
    payload = json.loads(tool_result_msg["content"][0]["content"])
    assert payload["ok"] and payload["result"]["experiments"][0]["id"] == "demo"
    assert result.trace[0]["tool_results"][0]["ok"] is True


def test_policy_violation_is_returned_to_model_not_raised(repo: Path):
    client = ScriptedClient(
        [
            _response([_tool_use("read_document", {"path": "data/secret.csv"})], "tool_use"),
            _response([_text("That file is outside my policy.")], "end_turn"),
        ]
    )
    result = _agent(repo, client).ask("Read the raw data.")
    payload = json.loads(client.calls[1]["messages"][2]["content"][0]["content"])
    assert payload == {
        "ok": False,
        "error": "Policy violation",
        "details": "Reading 'data/secret.csv' is not permitted by POLICY.md.",
    }
    assert result.trace[0]["tool_results"][0]["error"] == "Policy violation"


def test_step_limit_stops_runaway_loops(repo: Path):
    client = ScriptedClient([_response([_tool_use("list_experiments", {})], "tool_use")] * 3)
    result = _agent(repo, client, max_steps=3).ask("Loop forever.")
    assert result.steps == 3
    assert result.stop_reason == "max_steps"
    assert len(client.calls) == 3


def test_token_budget_forces_a_final_answer(repo: Path):
    client = ScriptedClient(
        [
            _response([_tool_use("list_experiments", {})], "tool_use", tokens=(80, 30)),
            _response([_text("Partial answer.")], "end_turn"),
        ]
    )
    result = _agent(repo, client, token_budget=100).ask("Expensive question.")
    assert result.stop_reason == "token_budget"
    assert result.answer == "Partial answer."
    assert "tools" not in client.calls[1]
    user_messages = [m for m in client.calls[1]["messages"] if m["role"] == "user"]
    assert "Token budget exhausted" in user_messages[-1]["content"]


def test_trace_is_written_when_configured(repo: Path, tmp_path: Path):
    client = ScriptedClient([_response([_text("Done.")], "end_turn")])
    trace_dir = tmp_path / "traces"
    _agent(repo, client, trace_dir=trace_dir).ask("Hello?")
    files = list(trace_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["question"] == "Hello?" and data["answer"] == "Done."
