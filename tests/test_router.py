import unittest

from sophyane.router import route


class RouterTests(unittest.TestCase):
    def test_plain_tools_alias(self):
        self.assertEqual(route("tools").kind, "tools")

    def test_plain_exit_alias(self):
        self.assertEqual(route("exit").kind, "exit")

    def test_system_intent(self):
        result = route(
            "Can you check my system configuration?"
        )
        self.assertEqual(result.kind, "system")

    def test_repository_src_intent(self):
        result = route(
            "Analyze the src/ directory and map imports"
        )
        self.assertEqual(result.kind, "repository")

    def test_repository_word_intent(self):
        result = route(
            "Inspect this repository and map dependencies"
        )
        self.assertEqual(result.kind, "repository")


if __name__ == "__main__":
    unittest.main()
