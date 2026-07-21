# Sophyane

**Local-first AI software engineering platform with repository intelligence, coded sandboxes, validator-driven execution, multi-provider orchestration, MCP interoperability, and native COI sub-agents.**

Sophyane runs on Linux, macOS, Windows, ChromeOS Linux, Android Termux, UserLAnd, VPS hosts, and lightweight edge systems. It can use local GGUF or Ollama models, cloud providers such as Gemini, OpenAI, Anthropic, xAI, Groq, OpenRouter and DeepSeek, or a local-first chain where cloud models rescue repeated validator failures.

## Install

Linux, macOS, ChromeOS Linux, UserLAnd, and Termux:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

Start:

```bash
sophyane
```

## What Sophyane includes

### Interactive engineering agent

- Conversational and coding modes
- Persistent projects across follow-up edits
- Explicit build, fix, run, test, browser and repository workflows
- Live provider, validator and execution progress
- Local-first inference with sticky cloud rescue
- Provider-neutral artifact extraction and truncation recovery

### Repository kernel

```bash
sophyane-platform index .
sophyane-platform checkpoint .
sophyane-platform eval .
sophyane-platform compact ~/.sophyane
```

The kernel provides repository indexing, lightweight symbol discovery, snapshots, rollback-ready checkpoints, deterministic evaluation, local tracing and bounded compaction.

### Coded sandbox and filesystem

Sophyane prepares an isolated task workspace before execution. Generated commands remain inside the workspace unless the user explicitly authorizes broader access.

```text
~/.sophyane/
├── workspaces/        task repositories and generated files
├── sandboxes/         sandbox manifests and policies
├── artifacts/         validated outputs
├── logs/              execution logs
├── state/             durable runtime state
├── platform/          repository, agents, runs and knowledge
└── coi/               collaborative orchestration state
```

Each COI workspace can contain:

```text
agents/  tasks/  runs/  events/  artifacts/  queues/
knowledge/  contracts/  permissions/  metrics/
```

### COI — Collaborative Orchestration Interface

COI is Sophyane's internal coordination protocol. It manages agents, parent/child tasks, permissions, shared artifacts, event traces, validation and bounded execution.

```bash
sophyane-coi status
sophyane-coi task "Build and validate a responsive snake game" --workspace ./snake
sophyane-coi agent-manifest browser --role validator --skill accessibility --tool browser
```

A task contract contains a goal, owner, workspace, repository, permissions, dependencies, expected outputs, validators and timeout. Agent manifests declare roles, skills, tools, permissions, provider policy and maximum steps.

COI is deliberately separate from MCP:

- **COI** coordinates Sophyane's internal agents, tasks, memory, artifacts and evaluation.
- **MCP** connects Sophyane to external tools, resources and services.

See [docs/COI.md](docs/COI.md).

### MCP interoperability

Sophyane includes a dependency-free MCP-style tool bridge and catalog:

```bash
sophyane --mcp-list
sophyane --mcp-call platform
sophyane --mcp-call rag_query --mcp-args '{"q":"provider dispatcher"}'
```

Built-in tools include local RAG, skills, budget status, sandboxed Python, platform probing and public web fetch. The catalog can be wrapped by full MCP stdio or HTTP servers without changing COI agent contracts.

See [docs/MCP.md](docs/MCP.md).

### Native sub-agents

Sophyane supports bounded, provider-neutral agents such as:

- Supervisor and planner
- Repository and symbol agent
- Coding and repair agent
- Browser and accessibility validator
- Test and evaluation agent
- Documentation agent
- Learning and trace-analysis agent

Sub-agents use the existing provider dispatcher instead of capturing a provider directly. Each agent receives a constrained task contract and shared context, and writes structured events and results locally.

### Evaluation and tracing

Evaluation is deterministic where possible and model-assisted only when appropriate. Reports may cover:

- Correctness and acceptance criteria
- Build and tests
- Browser behavior and accessibility
- Security and permission boundaries
- Performance and responsiveness
- Documentation and reproducibility

Local JSONL traces record task transitions, providers, timing, files, validators and outcomes without requiring LangSmith.

### Prompt guidance

Use this compact pattern:

```text
Goal:
Constraints:
Context/files:
Acceptance criteria:
Tests:
```

```bash
sophyane-platform advise "Create a responsive snake game with keyboard and touch controls"
```

See [docs/PROMPT_GUIDE.md](docs/PROMPT_GUIDE.md) and [docs/EVALUATION.md](docs/EVALUATION.md).

## Architecture

```text
User / Application
        │
Sophyane Supervisor
        │
COI Orchestrator ─────────────── Local trace and evaluation
        │
Provider Dispatcher
   ┌────┴─────────┐
Local models   Cloud providers
        │
Repository Kernel + Coded Sandbox
        │
MCP Bridge ───── External tools and services
```

Only the provider dispatcher chooses the active model. COI chooses the agent and task. MCP exposes tools. Validators decide whether execution is complete.

## Common commands

```bash
sophyane --version
sophyane --setup
sophyane --status
sophyane --providers
sophyane --doctor
sophyane --capabilities
sophyane-platform status
sophyane-coi status
sophyane-web
sophyane-browser
```

Inside the interactive CLI:

```text
/help       command help
/status     provider and runtime state
/new        start a fresh project
/inspect    inspect plan and generated files
/quit       exit
```

## Provider modes

At startup Sophyane can run:

1. **Local first** — local model handles normal work; a configured cloud model takes ownership after repeated deterministic validator failures.
2. **Cloud** — use the selected cloud provider directly.
3. **Current configuration** — retain the existing provider chain.

Provider configuration is stored under `~/.config/sophyane/`. Secrets remain in private user configuration and are never committed to the repository.

## Supported surfaces

| Surface | CLI | Browser UI | Local model |
|---|---:|---:|---:|
| Linux | Yes | Yes | Yes |
| macOS | Yes | Yes | Yes |
| Windows | Yes | Yes | Yes |
| ChromeOS Linux | Yes | Yes | Yes |
| Android Termux | Yes | Yes | Yes |
| Android UserLAnd | Yes | Yes | Yes |
| iPhone/iPad | Remote browser | Yes | Host-dependent |
| VPS / edge Linux | Yes | Yes | Hardware-dependent |

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [COI](docs/COI.md)
- [MCP](docs/MCP.md)
- [Prompt guide](docs/PROMPT_GUIDE.md)
- [Evaluation](docs/EVALUATION.md)
- [Platform kernel](docs/PLATFORM_KERNEL.md)
- [Download and installation](DOWNLOAD.md)
- [Contributing](CONTRIBUTING.md)

## Capability status

Sophyane documentation uses three labels:

- **Implemented** — available in the current release.
- **Experimental** — usable but interfaces may change.
- **Planned** — roadmap only and not presented as available.

COI task contracts, local event tracing, agent manifests, the MCP-lite catalog, repository tools, sandbox preparation, evaluation and compaction are implemented. Distributed cross-device scheduling, a public agent marketplace and full remote MCP transport management remain planned or experimental depending on the adapter.

## License

Sophyane is open source under the MIT License.
