import unittest

from sophyane.tui_v2 import _simple_chat_reply


class SimpleChatFastPathTests(unittest.TestCase):
    def test_python_version_query(self):
        result = _simple_chat_reply(
            "what version of python is installed?"
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Python "))
        self.assertIn("python", result.lower())

    def test_general_python_question_not_captured(self):
        self.assertIsNone(
            _simple_chat_reply("What is Python?")
        )

    def test_pytest_location_fastpath(self):
        result = _simple_chat_reply("Locate pytest.")
        self.assertIsNotNone(result)
        self.assertTrue(
            result.startswith("pytest:") or "not found on PATH" in result
        )


if __name__ == "__main__":
    unittest.main()
