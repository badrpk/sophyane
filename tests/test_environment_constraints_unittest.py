from pathlib import Path
import tempfile
import unittest

from sophyane.environment_constraints import (
    clear_environment_constraints,
    command_capability_key,
    constraint_for_command,
    learn_constraints_from_result,
    verification_result_is_meaningful,
)


class EnvironmentConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        clear_environment_constraints()

    def tearDown(self) -> None:
        clear_environment_constraints()
        self.temp.cleanup()

    def test_pytest_module_commands_share_capability(self) -> None:
        commands = (
            "python3 -m pytest -q",
            "python3 -m pytest tests/test_x.py -v",
            "python -m pytest --collect-only",
        )

        keys = {command_capability_key(command) for command in commands}
        self.assertEqual(keys, {"python-module:pytest"})

    def test_missing_pytest_module_blocks_later_variant(self) -> None:
        first = "python3 -m pytest --collect-only -q"
        result = (
            "Command: python3 -m pytest --collect-only -q\n"
            "Exit code: 1\n"
            "STDOUT:\n\n"
            "STDERR:\n"
            "/usr/bin/python3: No module named pytest"
        )

        learned = learn_constraints_from_result(
            self.workspace,
            first,
            result,
        )

        self.assertEqual(learned, "python-module:pytest")

        message = constraint_for_command(
            self.workspace,
            "python3 -m pytest tests/test_x.py -v",
        )

        self.assertIn("pytest", message)
        self.assertIn("unavailable", message)
        self.assertIn("Do not retry", message)

    def test_constraint_is_isolated_by_workspace(self) -> None:
        learn_constraints_from_result(
            self.workspace,
            "python3 -m pytest -q",
            "Exit code: 1\nSTDERR:\nNo module named pytest",
        )

        other = self.workspace / "other"
        other.mkdir()

        self.assertEqual(
            constraint_for_command(
                other,
                "python3 -m pytest -q",
            ),
            "",
        )

    def test_no_tests_ran_is_not_verification(self) -> None:
        result = (
            "Command: python3 -m unittest tests.test_example\n"
            "Exit code: 0\n"
            "STDOUT:\n\n"
            "STDERR:\n"
            "Ran 0 tests\n\nOK"
        )

        self.assertFalse(
            verification_result_is_meaningful(
                "python3 -m unittest tests.test_example",
                result,
            )
        )

    def test_silent_test_script_is_not_verification(self) -> None:
        result = (
            "Command: python3 tests/test_example.py\n"
            "Exit code: 0\n"
            "STDOUT:\n\n"
            "STDERR:\n"
        )

        self.assertFalse(
            verification_result_is_meaningful(
                "python3 tests/test_example.py",
                result,
            )
        )

    def test_executed_unittest_is_verification(self) -> None:
        result = (
            "Command: python3 -m unittest discover -s tests\n"
            "Exit code: 0\n"
            "STDOUT:\n\n"
            "STDERR:\n"
            "......\n"
            "----------------------------------------------------------------------\n"
            "Ran 6 tests in 0.020s\n\n"
            "OK"
        )

        self.assertTrue(
            verification_result_is_meaningful(
                "python3 -m unittest discover -s tests",
                result,
            )
        )

class ImportConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        clear_environment_constraints()

    def tearDown(self) -> None:
        clear_environment_constraints()
        self.temp.cleanup()

    def test_import_failure_blocks_broad_unittest_discovery(self) -> None:
        result = (
            "Command: python3 -m unittest discover -s tests\n"
            "Exit code: 1\n"
            "STDOUT:\n\n"
            "STDERR:\n"
            "ERROR: test_example "
            "(unittest.loader._FailedTest.test_example)\n"
            "ImportError: Failed to import test module: test_example\n"
            "Traceback (most recent call last):\n"
            "  File \"/workspace/tests/test_example.py\", line 3, "
            "in <module>\n"
            "    import pytest\n"
            "ModuleNotFoundError: No module named 'pytest'\n"
        )

        learn_constraints_from_result(
            self.workspace,
            "python3 -m unittest discover -s tests",
            result,
        )

        message = constraint_for_command(
            self.workspace,
            "python3 -m unittest discover -s tests -p 'test_*.py'",
        )

        self.assertIn("broad unittest discovery", message)
        self.assertIn("pytest", message)
        self.assertIn("focused test subset", message)

    def test_direct_module_failure_does_not_block_unittest(self) -> None:
        learn_constraints_from_result(
            self.workspace,
            "python3 -m pytest",
            (
                "Command: python3 -m pytest\n"
                "Exit code: 1\n"
                "STDOUT:\n\n"
                "STDERR:\n"
                "/usr/bin/python3: No module named pytest\n"
            ),
        )

        message = constraint_for_command(
            self.workspace,
            "python3 -m unittest discover -s tests",
        )

        self.assertEqual(message, "")

    def test_import_constraint_allows_focused_unittest(self) -> None:
        learn_constraints_from_result(
            self.workspace,
            "python3 -m unittest discover -s tests",
            (
                "Exit code: 1\n"
                "ImportError: Failed to import test module: test_example\n"
                "ModuleNotFoundError: No module named 'pytest'\n"
            ),
        )

        message = constraint_for_command(
            self.workspace,
            (
                "python3 -m unittest "
                "tests.test_environment_constraints_unittest"
            ),
        )

        self.assertEqual(message, "")


class PackageInstallConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        clear_environment_constraints()

    def tearDown(self) -> None:
        clear_environment_constraints()
        self.temp.cleanup()

    def test_pep668_failure_blocks_later_pip_install(self) -> None:
        learn_constraints_from_result(
            self.workspace,
            "python3 -m pip install pytest",
            (
                "Command: python3 -m pip install pytest\n"
                "Exit code: 1\n"
                "STDERR:\n"
                "error: externally-managed-environment\n"
                "This environment is externally managed\n"
            ),
        )

        message = constraint_for_command(
            self.workspace,
            "python3 -m pip install requests",
        )

        self.assertIn("system pip installation is blocked", message)
        self.assertIn("PEP 668", message)
        self.assertIn("Do not retry", message)

    def test_pep668_constraint_blocks_pip3_variant(self) -> None:
        learn_constraints_from_result(
            self.workspace,
            "python3 -m pip install pytest",
            (
                "Exit code: 1\n"
                "error: externally-managed-environment\n"
            ),
        )

        message = constraint_for_command(
            self.workspace,
            "pip3 install pytest",
        )

        self.assertIn("system pip installation is blocked", message)

    def test_pep668_constraint_does_not_block_venv_creation(self) -> None:
        learn_constraints_from_result(
            self.workspace,
            "python3 -m pip install pytest",
            (
                "Exit code: 1\n"
                "error: externally-managed-environment\n"
            ),
        )

        message = constraint_for_command(
            self.workspace,
            "python3 -m venv .venv",
        )

        self.assertEqual(message, "")

if __name__ == "__main__":
    unittest.main()
