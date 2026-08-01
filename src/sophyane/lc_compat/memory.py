"""Chat / summary / buffer memory (local)."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Message:
    role: str
    content: str
    ts: float = field(default_factory=time.time)

class BufferMemory:
    def __init__(self, max_messages: int = 50) -> None:
        self.max_messages = max_messages
        self.messages: list[Message] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append(Message(role, content))
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def as_text(self) -> str:
        return "\n".join(f"{m.role}: {m.content}" for m in self.messages)

    def clear(self) -> None:
        self.messages.clear()

class SummaryMemory(BufferMemory):
    def __init__(self, max_messages: int = 20, summary: str = "") -> None:
        super().__init__(max_messages=max_messages)
        self.summary = summary

    def as_text(self) -> str:
        head = f"Summary: {self.summary}\n" if self.summary else ""
        return head + super().as_text()

class PersistentMemory(BufferMemory):
    def __init__(self, path: Path, max_messages: int = 100) -> None:
        super().__init__(max_messages=max_messages)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self) -> None:
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.messages = [Message(**m) for m in data.get("messages", [])]

    def save(self) -> None:
        payload = {"messages": [m.__dict__ for m in self.messages]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add(self, role: str, content: str) -> None:
        super().add(role, content)
        self.save()
