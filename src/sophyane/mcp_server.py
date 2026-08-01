"""MCP-compatible stdio server backed by Sophyane's tool catalog.

The server implements the core initialize, tools/list, tools/call and ping
JSON-RPC methods over newline-delimited stdio.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from sophyane.unified_execution_kernel import capability_catalog, execute_request
from sophyane.mcp_bridge import call_tool, list_tools
from sophyane.version import __version__

PROTOCOL_VERSION = "2025-03-26"


def _tool_catalog() -> list[dict[str, Any]]:
    existing = list_tools().get("tools", [])

    tools = list(existing)
    tools.extend(
        [
            {
                "name": "sophyane_execute",
                "description": (
                    "Execute a grounded deterministic Sophyane capability."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string"},
                        "workspace": {"type": "string"},
                    },
                    "required": ["request"],
                },
            },
            {
                "name": "sophyane_capabilities",
                "description": "List unified Sophyane capabilities.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]
    )

    return tools


def _text_content(value: Any) -> list[dict[str, str]]:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )

    return [{"type": "text", "text": rendered}]


def dispatch(message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    }
                },
                "serverInfo": {
                    "name": "sophyane",
                    "version": __version__,
                },
            },
        }

    if method == "ping":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {},
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": _tool_catalog(),
            },
        }

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}

        if name == "sophyane_capabilities":
            payload = {
                "ok": True,
                "capabilities": capability_catalog(),
            }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": _text_content(payload),
                    "isError": False,
                },
            }

        if name == "sophyane_execute":
            request = str(arguments.get("request") or "")
            workspace = arguments.get("workspace")
            execution = execute_request(
                request,
                workspace=workspace,
            )

            if execution is None:
                payload = {
                    "ok": False,
                    "error": "no_matching_capability",
                }
                is_error = True
            else:
                payload = execution.to_dict()
                is_error = not execution.ok

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": _text_content(payload),
                    "isError": is_error,
                },
            }

        result = call_tool(name, arguments)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": _text_content(result),
                "isError": not bool(result.get("ok")),
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}",
        },
    }


def main() -> int:
    for raw in sys.stdin:
        line = raw.strip()

        if not line:
            continue

        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object.")

            response = dispatch(message)

            if response is not None:
                print(
                    json.dumps(
                        response,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
        except Exception as error:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32603,
                            "message": (
                                f"{type(error).__name__}: {error}"
                            ),
                        },
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
