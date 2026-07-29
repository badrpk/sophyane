"""Unified tool abstraction (bridges CapabilityRegistry + callables)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: dict[str, Any] = field(default_factory=dict)  # JSON-schema-ish

    def invoke(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

def tool(name: str | None = None, description: str = ""):
    def deco(fn: Callable[..., Any]) -> Tool:
        return Tool(name=name or fn.__name__, description=description or (fn.__doc__ or ""), func=fn)
    return deco
