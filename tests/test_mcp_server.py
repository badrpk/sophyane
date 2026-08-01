from __future__ import annotations

from pathlib import Path

from sophyane.mcp_server import dispatch


def test_initialize() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    )

    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "sophyane"
    assert "tools" in response["result"]["capabilities"]


def test_tools_list() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
    )

    assert response is not None
    names = {
        tool["name"]
        for tool in response["result"]["tools"]
    }
    assert "sophyane_execute" in names
    assert "sophyane_capabilities" in names


def test_tools_call_execution(tmp_path: Path) -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "sophyane_execute",
                "arguments": {
                    "request": (
                        'create mcp.py and run it printing "mcp ok"'
                    ),
                    "workspace": str(tmp_path),
                },
            },
        }
    )

    assert response is not None
    assert response["result"]["isError"] is False
    assert (tmp_path / "mcp.py").is_file()
