import unittest

from sophyane.tui_v2 import _execution_requested


class ExecutionRoutingTests(unittest.TestCase):
    def test_locate_pytest_routes_to_execution(self):
        self.assertTrue(
            _execution_requested("Locate pytest.")
        )

    def test_where_is_python_routes_to_execution(self):
        self.assertTrue(
            _execution_requested("Where is python3?")
        )

    def test_which_git_routes_to_execution(self):
        self.assertTrue(
            _execution_requested("Which git is being used?")
        )

    def test_find_pip_executable_routes_to_execution(self):
        self.assertTrue(
            _execution_requested("Find the pip executable.")
        )

    def test_general_python_question_remains_chat(self):
        self.assertFalse(
            _execution_requested("What is Python?")
        )

    def test_explain_pytest_remains_chat(self):
        self.assertFalse(
            _execution_requested("Explain pytest.")
        )

    def test_unrelated_find_request_remains_chat(self):
        self.assertFalse(
            _execution_requested(
                "Find the meaning of intelligence."
            )
        )


if __name__ == "__main__":
    unittest.main()


def test_mode6_repository_program_creation_is_execution():
    """
    A repository mutation request must enter execution even when its wording
    describes a missing capability. Provider prose must not be allowed to
    satisfy this request without filesystem/execution evidence.
    """
    from sophyane.tui_v2 import _execution_requested

    request = """Work in ~/mode6_rsi_capability_test.

Read README.md and telemetry.sphy.

I need this repository to support SPHY-Telemetry files, but there is
currently no parser or implementation for that capability.

Create a reusable Python program named sphy_telemetry.py that reads a
SPHY-Telemetry file and writes CSV records to stdout in this exact form:

name,temp,load,status

Follow the classification rules in README.md.

Then run it against telemetry.sphy and verify that its output exactly
matches EXPECTED.txt.

Do not merely describe the solution. Complete the repository operation
and verify the result."""

    assert _execution_requested(request) is True
