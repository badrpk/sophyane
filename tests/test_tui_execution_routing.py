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
