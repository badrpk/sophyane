import os
import unittest
from unittest.mock import patch

from sophyane.local_inspection import inspect_local_request


class LocalInspectionTests(unittest.TestCase):
    @patch(
        "sophyane.local_inspection.shutil.which",
        return_value="/usr/bin/git",
    )
    def test_conversational_which(self, mocked_which):
        self.assertEqual(
            inspect_local_request("Which git is being used?"),
            "git: /usr/bin/git",
        )
        mocked_which.assert_called_once_with("git")

    @patch(
        "sophyane.local_inspection.shutil.which",
        return_value="/usr/bin/python3",
    )
    def test_which_python_returns_path_not_version(self, mocked_which):
        self.assertEqual(
            inspect_local_request("Which python?"),
            "python: /usr/bin/python3",
        )

    def test_python_version(self):
        result = inspect_local_request(
            "What version of Python is installed?"
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Python "))

    def test_show_path(self):
        with patch.dict(os.environ, {"PATH": "/one:/two"}):
            self.assertEqual(
                inspect_local_request("Show PATH."),
                "PATH=/one:/two",
            )

    def test_working_directory(self):
        result = inspect_local_request(
            "What is the current working directory?"
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("cwd: "))

    def test_shell(self):
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            self.assertEqual(
                inspect_local_request("What shell am I using?"),
                "Shell: /bin/bash",
            )

    def test_user(self):
        result = inspect_local_request("Who am I?")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("User: "))

    def test_operating_system(self):
        result = inspect_local_request(
            "What operating system is this?"
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Operating system: "))

    def test_architecture(self):
        result = inspect_local_request(
            "What architecture is this machine?"
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Architecture: "))

    def test_home_directory(self):
        result = inspect_local_request(
            "What is my home directory?"
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Home: "))

    def test_rejects_shell_injection(self):
        self.assertIsNone(
            inspect_local_request("Locate pytest; rm -rf /")
        )

    def test_general_question_not_intercepted(self):
        self.assertIsNone(
            inspect_local_request("What is Python?")
        )


if __name__ == "__main__":
    unittest.main()
