"""Regression tests for explicit Gemini response-mode selection."""

from __future__ import annotations

import inspect
import unittest

from sophyane.providers import gemini


def response_mode_owner() -> type:
    """Find the Gemini provider class without depending on its exact class name."""
    matches = [
        value
        for value in vars(gemini).values()
        if inspect.isclass(value)
        and value.__module__ == gemini.__name__
        and callable(getattr(value, "_response_mode", None))
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one Gemini response-mode class, found {len(matches)}"
        )
    return matches[0]


class GeminiResponseModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider_class = response_mode_owner()

    def mode(self, prompt: str, system: str = "") -> str:
        return self.provider_class._response_mode(prompt, system)

    def test_explicit_chat_mode_is_plain_text(self) -> None:
        self.assertEqual(
            self.mode(
                "What is semantic intelligence?",
                "SOPHYANE_RESPONSE_MODE: CHAT",
            ),
            "chat",
        )

    def test_direct_chat_marker_overrides_generic_planning_default(self) -> None:
        self.assertEqual(
            self.mode(
                "Answer the user normally.",
                "SOPHYANE_RESPONSE_MODE: CHAT "
                "You are an agentic software harness.",
            ),
            "chat",
        )

    def test_action_request_remains_action_mode(self) -> None:
        self.assertEqual(
            self.mode(
                "Return one compact JSON object with a write_file action."
            ),
            "action",
        )

    def test_raw_html_request_remains_raw_mode(self) -> None:
        self.assertEqual(
            self.mode("Output raw HTML only, ending </html>."),
            "raw",
        )

    def test_unmarked_structured_request_keeps_plan_default(self) -> None:
        self.assertEqual(
            self.mode("Plan a multi-step implementation."),
            "plan",
        )

    def test_agent_marks_normal_cloud_chat_explicitly(self) -> None:
        from pathlib import Path

        source = Path("src/sophyane/agent.py").read_text(encoding="utf-8")
        marker = "SOPHYANE_RESPONSE_MODE: CHAT"

        self.assertIn(marker, source)
        self.assertIn("Do not return planner JSON", source)


if __name__ == "__main__":
    unittest.main()
