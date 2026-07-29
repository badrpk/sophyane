"""Structured output parsers."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

class OutputParserError(ValueError):
    pass

@dataclass
class JsonOutputParser:
    schema_keys: list[str] | None = None

    def parse(self, text: str) -> dict[str, Any]:
        text = text.strip()
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise OutputParserError("No JSON object found")
        data = json.loads(m.group(0))
        if not isinstance(data, dict):
            raise OutputParserError("JSON root must be object")
        if self.schema_keys:
            missing = [k for k in self.schema_keys if k not in data]
            if missing:
                raise OutputParserError(f"Missing keys: {missing}")
        return data

@dataclass
class ListOutputParser:
    sep: str = "\n"

    def parse(self, text: str) -> list[str]:
        return [ln.strip("-• \t") for ln in text.split(self.sep) if ln.strip()]

@dataclass
class BooleanOutputParser:
    def parse(self, text: str) -> bool:
        t = text.strip().lower()
        if t.startswith(("y", "true", "yes", "1")):
            return True
        if t.startswith(("n", "false", "no", "0")):
            return False
        raise OutputParserError(f"Cannot parse boolean from: {text[:80]!r}")

def retry_parse(parser: Any, text: str, repair: Callable[[str, Exception], str], attempts: int = 3) -> Any:
    last: Exception | None = None
    cur = text
    for _ in range(attempts):
        try:
            return parser.parse(cur)
        except Exception as e:
            last = e
            cur = repair(cur, e)
    raise OutputParserError(str(last))
