from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = (
    ROOT / "src" / "sophyane" / "runtime_provider_context_patch.py"
)
AGENT = ROOT / "src" / "sophyane" / "agent.py"


class ProviderSteeringSafetyTests(unittest.TestCase):
    def test_initial_steering_grace_is_installed(self):
        source = CONTEXT.read_text(encoding="utf-8")

        self.assertIn(
            "steering_ready_at = time.monotonic() + 1.0",
            source,
        )
        self.assertIn(
            "and now < steering_ready_at",
            source,
        )

    def test_ctrl_c_is_checked_before_grace_guard(self):
        source = CONTEXT.read_text(encoding="utf-8")

        ctrl_c = source.index('if char == "\\x03":')
        grace = source.index("and now < steering_ready_at")

        self.assertLess(ctrl_c, grace)

    def test_expected_provider_cancellation_is_quiet(self):
        source = AGENT.read_text(encoding="utf-8")

        self.assertIn(
            '"provider generation cancelled" in message',
            source,
        )
        self.assertIn(
            '"local generation cancelled" in message',
            source,
        )
        self.assertIn(
            'return AgentResponse("")',
            source,
        )

    def test_broad_cancel_substring_match_is_not_used(self):
        source = AGENT.read_text(encoding="utf-8")

        self.assertNotIn(
            'if "cancel" in message:',
            source,
        )

    def test_real_provider_failures_still_log_traceback(self):
        source = AGENT.read_text(encoding="utf-8")

        self.assertIn(
            'self.logger.exception("Provider generation failed")',
            source,
        )


if __name__ == "__main__":
    unittest.main()
