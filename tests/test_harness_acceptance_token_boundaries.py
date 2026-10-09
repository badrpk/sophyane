import unittest

from sophyane.harness_acceptance import criteria


class HarnessAcceptanceTokenBoundaryTests(unittest.TestCase):
    def test_program_substring_does_not_activate_ram(self):
        selected = criteria("Build a Python program")
        self.assertNotIn("RAM use is measured where supported.", selected)

    def test_explicit_ram_activates_ram_criterion(self):
        selected = criteria("Measure RAM use for the application")
        self.assertIn("RAM use is measured where supported.", selected)

    def test_phrase_markers_remain_supported(self):
        selected = criteria(
            "github actions, performance bottleneck, startup time, and technical debt"
        )
        self.assertIn("GitHub Actions workflow exists.", selected)
        self.assertIn("Performance bottlenecks are supported by evidence.", selected)
        self.assertIn("Startup time is measured.", selected)
        self.assertIn("Technical debt is prioritized.", selected)


if __name__ == "__main__":
    unittest.main()
