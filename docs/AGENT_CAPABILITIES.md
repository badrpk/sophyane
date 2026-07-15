# Sophyane — Full modern agent capability map

Sophyane is built to cover what users expect from an agent **now and for the
foreseeable future**: reason, act, remember, learn, connect, schedule, observe,
and stay safe.

## Public install (always latest)

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
sophyane --capabilities
sophyane --audit
```

## Capability groups

| Group | Features |
|-------|----------|
| **Cognition** | Multi-provider + local GGUF, harness loop, structured JSON, expert pack |
| **Act** | Safe tools, coding agent, sandboxed Python REPL, skills |
| **Remember** | SQLite memory, local RAG, checkpoints, web intel |
| **Multi-agent** | Supervisor/workers, graph runtime, daemon, scheduler |
| **Safety** | Guardrails, HITL approvals, budgets, permission profiles |
| **Connect** | Mesh, MCP-lite tools, Hardware API (Py/C++/JS), ERP, browser |
| **Learn** | Self-improve ledger, federated PEFT (C++), continual rounds |
| **UX/Ops** | Grok TUI, traces, notifications, doctor/audit, appliance boot |
| **Multimodal** | Image describe hooks, voice STT/TTS detection |

Honest partials (need external binaries/hardware): full GUI computer-use,
realtime duplex voice, external A2A protocol mapping.

## CLI map

```bash
sophyane --capabilities
sophyane --skills
sophyane --skill code-review --skill-prompt "review auth.py"
sophyane --rag-add ./README.md && sophyane --rag-query "install"
sophyane --schedule nightly --schedule-prompt "summarize git status" --schedule-every 86400
sophyane --schedule-run
sophyane --budget-status
sophyane --hitl-request "deploy prod" && sophyane --hitl-list
sophyane --repl 'print(sum(range(10)))'
sophyane --mcp-list && sophyane --mcp-call platform --mcp-args '{}'
sophyane --permissions workspace
sophyane --checkpoint-list
sophyane --voice-status
sophyane --notify-test
sophyane --trace-list
```

## Design principles

1. **Stdlib-first** — installs cleanly; optional heavy stacks stay optional  
2. **Opt-in power** — training, mesh tokens, HITL  
3. **Honest coverage** — `--capabilities` marks ready vs partial  
4. **Composable** — skills + MCP-lite + mesh + kernel modules  
