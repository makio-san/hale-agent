"""Bounded tool-use loop.

The default model is a local Ollama server. An Anthropic client can be selected
with HALE_PROVIDER=anthropic. Both speak the same `create` shape.

The loop is deliberately plain: call the model, run any requested tools
through the registry (which applies policy), append results, repeat. It stops
on a final answer, the step limit or the token budget, and records a trace of
every step so runs can be audited later.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from hale.config import Settings
from hale.policy import RepoPolicy
from hale.tools import ToolRegistry, default_registry

SYSTEM_PROMPT = """You are Hale, the research agent of the Helio24 solar flare forecasting project.

Stage 2: you may read protocols, reports and frozen summaries, and you may run allowlisted
check/run/audit scripts into a brand new artifacts/ directory. You cannot edit frozen files,
docs, or config versions in place, and you cannot open reserved test rows.

Rules:
- Ground every factual statement in a tool result and cite the repository path (and line or key)
  it came from, e.g. (docs/third-experiment.md:42) or (artifacts/x/report.json: metrics.recall).
- If the evidence is not in the repository, say so plainly. Do not fill gaps from general knowledge
  about solar physics or machine learning.
- Development results are not test results. Never describe a development or validation number as
  an independent test result. Window counts are not event counts.
- Reserved test sections are redacted by policy. Do not speculate about their contents or suggest
  ways to access them.
- Call list_scripts before run_script. Prefer family=check. Set confirm=true for family=run or
  family=audit only when the user explicitly asked to execute that named script.
- output must be a new path of the form artifacts/<name>. Never reuse or overwrite a directory.
- Prefer search_reports then read_document over reading whole files. Stop calling tools once you
  have enough evidence.
- Answer in the language of the question. Keep numeric values exactly as they appear in sources."""


class MessagesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


@dataclass
class RunResult:
    answer: str
    steps: int
    input_tokens: int
    output_tokens: int
    stop_reason: str
    trace: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        settings: Settings,
        client: MessagesClient | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.policy = RepoPolicy(
            settings.target_repo,
            allow_test_role=settings.allow_test_role,
            python=settings.python,
        )
        self.registry = registry or default_registry()
        self.client = client or build_client(settings)

    def ask(self, question: str) -> RunResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        trace: list[dict[str, Any]] = []
        used_in = used_out = 0
        stop_reason = "max_steps"

        for step in range(1, self.settings.max_steps + 1):
            response = self.client.create(
                model=self.settings.model,
                max_tokens=self.settings.max_output_tokens,
                system=SYSTEM_PROMPT,
                tools=self.registry.schemas(),
                messages=messages,
            )
            used_in += response.usage.input_tokens
            used_out += response.usage.output_tokens
            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            trace.append(
                {
                    "step": step,
                    "stop_reason": response.stop_reason,
                    "text": _text_of(response.content),
                    "tool_calls": [{"name": b.name, "input": b.input} for b in tool_uses],
                    "usage": {"input": response.usage.input_tokens, "output": response.usage.output_tokens},
                }
            )

            if response.stop_reason != "tool_use" or not tool_uses:
                stop_reason = response.stop_reason
                break

            results = []
            for block in tool_uses:
                started = time.perf_counter()
                outcome = self.registry.call(self.policy, block.name, dict(block.input))
                trace[-1].setdefault("tool_results", []).append(
                    {
                        "name": block.name,
                        "ok": outcome.get("ok"),
                        "error": outcome.get("error"),
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(outcome, ensure_ascii=False, default=str),
                    }
                )
            messages.append({"role": "user", "content": results})

            if used_in + used_out > self.settings.token_budget:
                stop_reason = "token_budget"
                messages.append(
                    {
                        "role": "user",
                        "content": "Token budget exhausted. Answer now with the evidence you have and list what is missing.",
                    }
                )
                response = self.client.create(
                    model=self.settings.model,
                    max_tokens=self.settings.max_output_tokens,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                )
                used_in += response.usage.input_tokens
                used_out += response.usage.output_tokens
                messages.append({"role": "assistant", "content": response.content})
                break

        answer = _text_of(messages[-1]["content"]) if messages[-1]["role"] == "assistant" else ""
        result = RunResult(answer, len(trace), used_in, used_out, stop_reason, trace)
        self._write_trace(question, result)
        return result

    def _write_trace(self, question: str, result: RunResult) -> None:
        if not self.settings.trace_dir:
            return
        self.settings.trace_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.trace_dir / f"{time.strftime('%Y%m%dT%H%M%S')}.json"
        path.write_text(
            json.dumps(
                {
                    "question": question,
                    "model": self.settings.model,
                    "target_repo": str(self.settings.target_repo),
                    "stop_reason": result.stop_reason,
                    "usage": {"input": result.input_tokens, "output": result.output_tokens},
                    "trace": result.trace,
                    "answer": result.answer,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )


def build_client(settings: Settings):
    """Return the model client selected by settings.provider."""
    if settings.provider == "ollama":
        from hale.ollama import OllamaClient

        return OllamaClient(settings.ollama_host)
    if settings.provider == "anthropic":
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The Anthropic extra is not installed. Run: pip install 'hale-agent[anthropic]'"
            ) from exc
        return anthropic.Anthropic().messages
    raise RuntimeError(f"Unknown provider: {settings.provider}")


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


__all__ = ["Agent", "RunResult", "SYSTEM_PROMPT"]
