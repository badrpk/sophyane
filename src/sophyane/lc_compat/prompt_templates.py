"""LangChain-style prompt templates (local, no LC dependency)."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any

_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}|\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

@dataclass
class PromptTemplate:
    template: str
    input_variables: list[str] = field(default_factory=list)
    partial_variables: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        found = []
        for m in _VAR.finditer(self.template):
            found.append(m.group(1) or m.group(2))
        if not self.input_variables:
            self.input_variables = sorted(set(found) - set(self.partial_variables))

    def format(self, **kwargs: Any) -> str:
        data = {**self.partial_variables, **kwargs}
        missing = [v for v in self.input_variables if v not in data]
        if missing:
            raise KeyError(f"Missing prompt variables: {missing}")
        out = self.template
        for k, v in data.items():
            out = out.replace("{{" + k + "}}", str(v)).replace("{" + k + "}", str(v))
        return out

    def partial(self, **kwargs: Any) -> "PromptTemplate":
        return PromptTemplate(
            self.template,
            input_variables=[v for v in self.input_variables if v not in kwargs],
            partial_variables={**self.partial_variables, **kwargs},
        )

def chat_prompt(system: str, user: str) -> PromptTemplate:
    return PromptTemplate(
        "SYSTEM:\n{system}\n\nUSER:\n{user}\n",
        input_variables=["system", "user"],
    )
