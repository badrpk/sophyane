import unittest

from sophyane.adaptive_execution import (
    _command_stdout,
    _discovery_request_completed,
)


class DiscoveryCompletionTests(unittest.TestCase):
    def test_extracts_stdout(self):
        result = (
            "Command: which pytest\n"
            "Exit code: 0\n"
            "STDOUT:\n"
            "/home/user/.venv/bin/pytest\n\n"
            "STDERR:\n"
        )

        self.assertEqual(
            _command_stdout(result),
            "/home/user/.venv/bin/pytest",
        )

    def test_locate_request_completes_with_useful_stdout(self):
        result = (
            "Command: which pytest\n"
            "Exit code: 0\n"
            "STDOUT:\n"
            "/home/user/.venv/bin/pytest\n\n"
            "STDERR:\n"
        )

        self.assertTrue(
            _discovery_request_completed(
                "Locate pytest.",
                {
                    "type": "run_command",
                    "command": "which pytest",
                },
                True,
                result,
            )
        )

    def test_where_is_request_completes(self):
        result = (
            "Command: command -v python3\n"
            "Exit code: 0\n"
            "STDOUT:\n"
            "/usr/bin/python3\n\n"
            "STDERR:\n"
        )

        self.assertTrue(
            _discovery_request_completed(
                "Where is python3?",
                {
                    "type": "run_command",
                    "command": "command -v python3",
                },
                True,
                result,
            )
        )

    def test_empty_find_output_does_not_complete(self):
        result = (
            "Command: find . -name pytest\n"
            "Exit code: 0\n"
            "STDOUT:\n\n"
            "STDERR:\n"
        )

        self.assertFalse(
            _discovery_request_completed(
                "Find pytest in this project.",
                {
                    "type": "run_command",
                    "command": "find . -name pytest",
                },
                True,
                result,
            )
        )

    def test_failed_command_does_not_complete(self):
        result = (
            "Command: which pytest\n"
            "Exit code: 1\n"
            "STDOUT:\n\n"
            "STDERR:\nnot found\n"
        )

        self.assertFalse(
            _discovery_request_completed(
                "Locate pytest.",
                {
                    "type": "run_command",
                    "command": "which pytest",
                },
                False,
                result,
            )
        )

    def test_build_request_does_not_complete_from_stdout(self):
        result = (
            "Command: echo created\n"
            "Exit code: 0\n"
            "STDOUT:\ncreated\n"
            "STDERR:\n"
        )

        self.assertFalse(
            _discovery_request_completed(
                "Build a website.",
                {
                    "type": "run_command",
                    "command": "echo created",
                },
                True,
                result,
            )
        )

    def test_write_action_is_not_discovery_completion(self):
        self.assertFalse(
            _discovery_request_completed(
                "Find the configuration file.",
                {
                    "type": "write_file",
                    "path": "result.txt",
                },
                True,
                "File written successfully.",
            )
        )


if __name__ == "__main__":
    unittest.main()
