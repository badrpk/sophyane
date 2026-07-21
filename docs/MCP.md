# MCP interoperability

**Status: MCP-lite catalog implemented; full remote transport lifecycle is experimental.**

Sophyane exposes a dependency-free MCP-style tool catalog through `sophyane.mcp_bridge`. The bridge gives COI agents and CLI workflows a stable way to list and invoke tools without coupling orchestration to one provider.

## CLI

```bash
sophyane --mcp-list
sophyane --mcp-call platform
sophyane --mcp-call rag_query --mcp-args '{"q":"sandbox policy","top_k":5}'
```

## Built-in tools

- `rag_query` — query the local retrieval index
- `list_skills` — list Sophyane skills
- `budget_status` — inspect token and cost budgets
- `python_repl` — run the sandboxed interpreter
- `platform` — inspect host capabilities
- `web_fetch` — fetch a public URL

## Python API

```python
from sophyane.mcp_bridge import list_tools, call_tool, export_catalog

catalog = list_tools()
result = call_tool("platform", {})
path = export_catalog()
```

## Relationship to COI

MCP is the external interoperability layer. COI is the internal orchestration layer.

```text
COI task and permissions
        │
COI agent
        │
MCP bridge
        │
External tool or service
```

A COI agent may declare `mcp:web_fetch` or another MCP capability in its manifest. The COI permission contract and Sophyane sandbox remain authoritative.

## Security principles

- Tool discovery does not imply permission to execute.
- Filesystem writes remain workspace-bound unless explicitly authorized.
- Secrets remain in private user configuration.
- Remote transports should authenticate, restrict origins and log calls.
- Tool outputs are treated as untrusted input until validated.

## Transport roadmap

Implemented now: local JSON catalog, direct invocation, exportable registry, HTTP/stdio-friendly contracts.

Experimental or planned: managed remote MCP server connections, streaming sessions, resource and prompt discovery, per-server authentication profiles and health supervision.
