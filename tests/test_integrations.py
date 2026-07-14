from __future__ import annotations

from dataclasses import dataclass

from sophyane.integrations import INTEGRATIONS, InvokeAdapter, callable_tool, probe_integrations


@dataclass
class Message:
    content: str


class Runnable:
    def invoke(self, payload):
        return Message(content=f"handled:{payload!r}")


def test_matrix_contains_ten_unique_targets() -> None:
    assert len(INTEGRATIONS) == 10
    assert len({item.key for item in INTEGRATIONS}) == 10


def test_runnable_adapter_supports_invoke_objects() -> None:
    adapter = InvokeAdapter(Runnable())
    result = adapter.generate("hello", "system")
    assert result.startswith("handled:")
    assert "hello" in result
    assert "system" in result


def test_runnable_adapter_supports_plain_callables() -> None:
    adapter = InvokeAdapter(lambda payload: f"callable:{payload}")
    assert adapter.generate("hello", "") == "callable:hello"


def test_callable_tool_validation() -> None:
    tool = callable_tool(lambda left, right: left + right)
    assert tool(20, 22) == 42


def test_probe_returns_one_row_per_target() -> None:
    rows = probe_integrations()
    assert len(rows) == 10
    assert {row["key"] for row in rows} == {item.key for item in INTEGRATIONS}
