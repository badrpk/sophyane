from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sophyane.memory import MemoryStore


class MemoryTests(unittest.TestCase):
    def test_remember_and_retrieve(self):
        with TemporaryDirectory() as temporary:
            store = MemoryStore(
                Path(temporary) / "memory.db"
            )

            store.remember(
                "Main project: SHMRY",
                importance=10,
            )

            results = store.relevant(
                "What is my main project?"
            )

            self.assertTrue(results)
            self.assertIn(
                "SHMRY",
                results[0]["content"],
            )

    def test_auto_capture(self):
        with TemporaryDirectory() as temporary:
            store = MemoryStore(
                Path(temporary) / "memory.db"
            )

            captured = store.auto_capture(
                "My main project is SHMRY."
            )

            self.assertTrue(captured)
            self.assertEqual(store.count(), 1)


if __name__ == "__main__":
    unittest.main()
