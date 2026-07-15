"""Lightweight MCP-style tool bridge (JSON catalog + HTTP/stdio friendly).

Full MCP stdio servers can wrap this catalog; Sophyane exposes the same tools
over Hardware API and a local JSON registry without mandatory deps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from sophyane.version import __version__

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

_TOOLS: dict[str, dict[str, Any]] = {}


def _register_builtins() -> None:
    if _TOOLS:
        return

    def rag_query(params: dict[str, Any]) -> dict[str, Any]:
        from sophyane.rag import query

        return query(str(params.get("q") or params.get("query") or ""), top_k=int(params.get("top_k") or 5))

    def skill_list(_: dict[str, Any]) -> dict[str, Any]:
        from sophyane.skills import list_skills

        return {"ok": True, "skills": list_skills()}

    def budget_status(_: dict[str, Any]) -> dict[str, Any]:
        from sophyane.budget import status

        return status()

    def repl(params: dict[str, Any]) -> dict[str, Any]:
        from sophyane.interpreter import run_python

        return run_python(str(params.get("code") or ""))

    def platform(_: dict[str, Any]) -> dict[str, Any]:
        from sophyane.platform_probe import probe_platform

        return probe_platform().to_dict()

    def web_fetch(params: dict[str, Any]) -> dict[str, Any]:
        from sophyane.web_intel import fetch_url

        url = str(params.get("url") or "")
        res = fetch_url(url, timeout=float(params.get("timeout") or 20))
        return res.to_dict() if hasattr(res, "to_dict") else {"ok": bool(getattr(res, "ok", False)), "title": getattr(res, "title", ""), "text": getattr(res, "text", "")[:4000]}

    catalog = {
        "rag_query": {"description": "Query local RAG index", "handler": rag_query},
        "list_skills": {"description": "List agent skills", "handler": skill_list},
        "budget_status": {"description": "Token/cost budget status", "handler": budget_status},
        "python_repl": {"description": "Sandboxed Python interpreter", "handler": repl},
        "platform": {"description": "Host platform probe", "handler": platform},
        "web_fetch": {"description": "Fetch a public URL", "handler": web_fetch},
    }
    for name, meta in catalog.items():
        _TOOLS[name] = meta


def list_tools() -> dict[str, Any]:
    _register_builtins()
    return {
        "ok": True,
        "protocol": "sophyane-mcp-lite/1",
        "version": __version__,
        "tools": [
            {"name": n, "description": m["description"], "inputSchema": {"type": "object"}}
            for n, m in sorted(_TOOLS.items())
        ],
    }


def call_tool(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    _register_builtins()
    meta = _TOOLS.get(name)
    if not meta:
        return {"ok": False, "error": f"unknown tool: {name}", "available": sorted(_TOOLS)}
    try:
        return {"ok": True, "tool": name, "result": meta["handler"](params or {})}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "tool": name, "error": str(error)}


def export_catalog(path: Path | None = None) -> Path:
    path = path or (Path.home() / ".local/state/sophyane/mcp_tools.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list_tools(), indent=2) + "\n", encoding="utf-8")
    return path
