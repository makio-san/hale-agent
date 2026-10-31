"""Local Ollama chat client with the same call shape as the Anthropic Messages API.

The agent loop speaks in Anthropic content blocks. This module translates those
blocks to Ollama's `/api/chat` tool protocol and back, so the loop stays one
implementation and the model can run on the machine with no API key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, Callable

Post = Callable[[str, dict[str, Any]], dict[str, Any]]


class OllamaError(RuntimeError):
    """Raised when the local Ollama server cannot be reached or rejects a call."""


def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise OllamaError(
            "Cannot reach Ollama. Install it from https://ollama.com, then run "
            "`ollama serve` and `ollama pull qwen2.5:7b`."
        ) from exc


class OllamaClient:
    def __init__(self, host: str = "http://127.0.0.1:11434", post: Post | None = None) -> None:
        self.host = host.rstrip("/")
        self._post = post or _post
        self._ids = 0

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> SimpleNamespace:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *_to_ollama_messages(messages)],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [_tool(schema) for schema in tools]
        data = self._post(f"{self.host}/api/chat", payload)
        return self._response(data)

    def _response(self, data: dict[str, Any]) -> SimpleNamespace:
        message = data.get("message") or {}
        blocks: list[SimpleNamespace] = []
        text = message.get("content") or ""
        if text:
            blocks.append(SimpleNamespace(type="text", text=text))
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            self._ids += 1
            blocks.append(
                SimpleNamespace(
                    type="tool_use",
                    id=f"toolu_{self._ids}",
                    name=function.get("name") or "",
                    input=_arguments(function.get("arguments")),
                )
            )
        stop = "tool_use" if message.get("tool_calls") else "end_turn"
        usage = SimpleNamespace(
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )
        return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


def _tool(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "parameters": schema.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _to_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names: dict[str, str] = {}
    converted: list[dict[str, Any]] = []
    for message in messages:
        content = message["content"]
        if message["role"] == "assistant":
            text, calls = _split_assistant(content)
            for call in calls:
                names[call.id] = call.name
            item: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                item["tool_calls"] = [
                    {"function": {"name": call.name, "arguments": dict(call.input)}} for call in calls
                ]
            converted.append(item)
            continue
        if isinstance(content, list):
            for block in content:
                converted.append(
                    {
                        "role": "tool",
                        "tool_name": names.get(block.get("tool_use_id", ""), ""),
                        "content": block.get("content", ""),
                    }
                )
            continue
        converted.append({"role": "user", "content": content})
    return converted


def _split_assistant(content: Any) -> tuple[str, list[Any]]:
    if isinstance(content, str):
        return content, []
    texts: list[str] = []
    calls: list[Any] = []
    for block in content:
        kind = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if kind == "tool_use":
            calls.append(block)
        else:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts), calls
