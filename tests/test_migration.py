import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sophyane.memory import MemoryStore


class MigrationTests(unittest.TestCase):
    def test_legacy_memory_database_is_migrated(self):
        with TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "memory.db"

            connection = sqlite3.connect(database_path)
            connection.execute(
                """
                CREATE TABLE memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT,
                    content TEXT UNIQUE,
                    importance INTEGER DEFAULT 8
                )
                """
            )
            connection.execute(
                """
                INSERT INTO memories(
                    created_at,
                    content,
                    importance
                )
                VALUES (?, ?, ?)
                """,
                (
                    "2026-07-13T00:00:00",
                    "Legacy fact",
                    8,
                ),
            )
            connection.commit()
            connection.close()

            store = MemoryStore(database_path)
            memories = store.list()

            self.assertEqual(len(memories), 1)
            self.assertEqual(
                memories[0]["content"],
                "Legacy fact",
            )
            self.assertTrue(memories[0]["updated_at"])
            self.assertEqual(
                memories[0]["source"],
                "legacy",
            )

            store.remember(
                "Main project: SHMRY",
                importance=10,
            )

            self.assertEqual(store.count(), 2)


if __name__ == "__main__":
    unittest.main()
