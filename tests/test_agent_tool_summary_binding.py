from sophyane.agent import SophyaneAgent
from sophyane.agent import _bounded_tool_context


def test_tool_summarizer_is_bound_to_agent_class():
    assert hasattr(SophyaneAgent, "_summarize_tool")
    assert callable(SophyaneAgent._summarize_tool)


def test_tool_context_is_bounded():
    result = _bounded_tool_context("x" * 30000)

    assert len(result) < 30000
    assert "SOPHYANE TOOL OUTPUT TRUNCATED" in result
