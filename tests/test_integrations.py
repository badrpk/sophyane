from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sophyane.integrations import (
    INTEGRATIONS,
    AsyncInvokeAdapter,
    InvokeAdapter,
    callable_tool,
    probe_integrations,
)


@dataclass
class Message:
    content: str


class Runnable:
    def invoke(self, payload):
        return Message(content=f"handled:{payload!r}")


class AsyncRunnable:
    async def ainvoke(self, payload):
        return Message(content=f"async:{payload!r}")


def test_matrix_contains_thirty_unique_targets() -> None:
    assert len(INTEGRATIONS) == 30
    assert len({item.key for item in INTEGRATIONS}) == 30
    assert sum(item.tier == "base" for item in INTEGRATIONS) == 10
    assert sum(item.tier == "extended" for item in INTEGRATIONS) == 20


def test_runnable_adapter_supports_invoke_objects() -> None:
    adapter = InvokeAdapter(Runnable())
    result = adapter.generate("hello", "system")
    assert result.startswith("handled:")
    assert "hello" in result
    assert "system" in result


def test_runnable_adapter_supports_plain_callables() -> None:
    adapter = InvokeAdapter(lambda payload: f"callable:{payload}")
    assert adapter.generate("hello", "") == "callable:hello"


def test_async_adapter_supports_ainvoke_objects() -> None:
    adapter = AsyncInvokeAdapter(AsyncRunnable())
    result = asyncio.run(adapter.generate("hello", "system"))
    assert result.startswith("async:")
    assert "hello" in result


def test_callable_tool_validation() -> None:
    tool = callable_tool(lambda left, right: left + right)
    assert tool(20, 22) == 42


def test_probe_returns_one_row_per_target() -> None:
    rows = probe_integrations()
    assert len(rows) == 30
    assert {row["key"] for row in rows} == {item.key for item in INTEGRATIONS}


def test_tier_filtering() -> None:
    assert len(probe_integrations("base")) == 10
    assert len(probe_integrations("extended")) == 20
