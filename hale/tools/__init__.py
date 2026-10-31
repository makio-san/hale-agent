"""Tool registry: Pydantic argument models mapped to handlers.

Each tool declares its arguments as a Pydantic model so that the JSON schema
sent to the model and the validation applied to its calls come from one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from hale.policy import PolicyError, RepoPolicy

Handler = Callable[[RepoPolicy, BaseModel], Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tools[name].schema() for name in self.names()]

    def call(self, policy: RepoPolicy, name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Run a tool and always return a JSON-serialisable envelope.

        Errors are returned as data, not raised, so the model can recover.
        """
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            args = tool.args.model_validate(raw_args)
        except ValidationError as exc:
            return {"ok": False, "error": "Invalid arguments", "details": exc.errors()}
        try:
            return {"ok": True, "result": tool.handler(policy, args)}
        except PolicyError as exc:
            return {"ok": False, "error": "Policy violation", "details": str(exc)}
        except FileNotFoundError as exc:
            return {"ok": False, "error": "Not found", "details": str(exc)}
        except Exception as exc:  # noqa: BLE001 - surfaced to the model as data
            return {"ok": False, "error": type(exc).__name__, "details": str(exc)}


def default_registry() -> ToolRegistry:
    from hale.tools import loop, research, scripts

    registry = ToolRegistry()
    for tool in (*research.TOOLS, *scripts.TOOLS, *loop.TOOLS):
        registry.register(tool)
    return registry
