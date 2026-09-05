import runpy
import unittest
from unittest.mock import patch

from sophyane import execution_runtime


class ModuleEntryRuntimeSafetyTests(unittest.TestCase):
    def test_module_entry_installs_runtime_safety_before_main(self):
        original = execution_runtime.execute_action

        if hasattr(execution_runtime, "_safety_installed"):
            delattr(execution_runtime, "_safety_installed")

        with patch("sophyane.cli_entry.main", return_value=0):
            with self.assertRaises(SystemExit) as exit_context:
                runpy.run_module("sophyane.__main__", run_name="__main__")

        self.assertEqual(exit_context.exception.code, 0)
        self.assertTrue(
            getattr(execution_runtime, "_safety_installed", False)
        )
        self.assertIsNot(execution_runtime.execute_action, original)


if __name__ == "__main__":
    unittest.main()
