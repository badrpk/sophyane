"""Persistent SQLite memory with safe schema migration."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sophyane.config import DATA_DIR, ensure_directories


DATABASE_FILE = DATA_DIR / "memory.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokenize(text: str) -> set[str]:
    ignored = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "what",
        "your",
        "you",
        "are",
        "was",
        "were",
        "have",
        "has",
        "main",
    }

    return {
        word
        for word in re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())
        if word not in ignored
    }


class MemoryStore:
    def __init__(self, path: Path = DATABASE_FILE) -> None:
        ensure_directories()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=15,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    @staticmethod
    def _columns(
        connection: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        rows = connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()

        return {str(row["name"]) for row in rows}

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    content TEXT NOT NULL UNIQUE,
                    importance INTEGER NOT NULL DEFAULT 5
                )
                """
            )

            columns = self._columns(connection, "memories")

            if "updated_at" not in columns:
                connection.execute(
                    "ALTER TABLE memories ADD COLUMN updated_at TEXT"
                )

            if "source" not in columns:
                connection.execute(
                    """
                    ALTER TABLE memories
                    ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy'
                    """
                )

            connection.execute(
                """
                UPDATE memories
                SET updated_at = COALESCE(
                    NULLIF(updated_at, ''),
                    created_at,
                    ?
                )
                WHERE updated_at IS NULL OR updated_at = ''
                """,
                (utc_now(),),
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_importance
                ON memories(importance DESC)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_updated
                ON memories(updated_at DESC)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_created
                ON conversations(created_at)
                """
            )

            connection.commit()

    def remember(
        self,
        content: str,
        importance: int = 5,
        source: str = "user",
    ) -> str:
        content = content.strip()

        if not content:
            return "Nothing supplied to remember."

        importance = max(1, min(10, int(importance)))
        timestamp = utc_now()

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO memories(
                    created_at,
                    updated_at,
                    content,
                    importance,
                    source
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(content) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    importance = MAX(
                        memories.importance,
                        excluded.importance
                    ),
                    source = excluded.source
                """,
                (
                    timestamp,
                    timestamp,
                    content,
                    importance,
                    source,
                ),
            )
            connection.commit()

        return f"Remembered: {content}"

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    created_at,
                    updated_at,
                    content,
                    importance,
                    source
                FROM memories
                ORDER BY importance DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

            return [dict(row) for row in rows]

    def relevant(
        self,
        query: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query_tokens = tokenize(query)
        scored: list[tuple[float, dict[str, Any]]] = []

        for memory in self.list(limit=200):
            content = str(memory["content"])
            memory_tokens = tokenize(content)
            overlap = len(query_tokens & memory_tokens)

            score = (
                overlap * 5
                + float(memory["importance"])
                + (
                    3
                    if query.lower() in content.lower()
                    else 0
                )
            )

            if overlap > 0 or int(memory["importance"]) >= 8:
                scored.append((score, memory))

        scored.sort(
            key=lambda item: (
                item[0],
                str(item[1]["updated_at"]),
            ),
            reverse=True,
        )

        return [
            memory
            for _, memory in scored[
                : max(1, min(int(limit), 20))
            ]
        ]

    def forget(self, memory_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE id = ?",
                (int(memory_id),),
            )
            connection.commit()
            return bool(cursor.rowcount)

    def record_message(self, role: str, content: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    created_at,
                    role,
                    content
                )
                VALUES (?, ?, ?)
                """,
                (
                    utc_now(),
                    role,
                    content[:100_000],
                ),
            )
            connection.commit()

    def recent_messages(
        self,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 50))

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, role, content
                FROM conversations
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

            return [
                dict(row)
                for row in reversed(rows)
            ]

    def count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM memories"
            ).fetchone()

            return int(row["total"])

    def auto_capture(self, message: str) -> list[str]:
        patterns = [
            (
                r"\bmy main project is\s+(.+?)(?:[.!?]|$)",
                "Main project: {}",
                10,
            ),
            (
                r"\bmy project is\s+(.+?)(?:[.!?]|$)",
                "Project: {}",
                9,
            ),
            (
                r"\bmy name is\s+(.+?)(?:[.!?]|$)",
                "User name: {}",
                9,
            ),
            (
                r"\bi am using\s+(.+?)(?:[.!?]|$)",
                "User uses: {}",
                7,
            ),
            (
                r"\bremember(?: that)?\s+(.+?)(?:[.!?]|$)",
                "{}",
                8,
            ),
        ]

        captured: list[str] = []

        for pattern, template, importance in patterns:
            match = re.search(
                pattern,
                message,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            value = match.group(1).strip()

            if not value:
                continue

            content = template.format(value)

            self.remember(
                content,
                importance=importance,
                source="automatic",
            )
            captured.append(content)

        return captured

    def format_relevant(self, query: str) -> str:
        memories = self.relevant(query)

        if not memories:
            return ""

        return "\n".join(
            [
                "Relevant persistent memories:",
                *[
                    f"- {memory['content']}"
                    for memory in memories
                ],
            ]
        )

    def format_all(self) -> str:
        memories = self.list()

        if not memories:
            return "No memories stored."

        return "\n".join(
            [
                "Stored memories:",
                *[
                    (
                        f"[{memory['id']}] "
                        f"(importance {memory['importance']}) "
                        f"{memory['content']}"
                    )
                    for memory in memories
                ],
            ]
        )
