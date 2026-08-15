# Sophyane 21.4.2

**Local-first AI software engineering platform for planning, building, repairing, validating, executing, and delivering real software artifacts.**

Sophyane combines a persistent engineering agent, semantic intent routing, durable graph execution, repository intelligence, coded sandboxes, validator-driven recovery, browser verification, multi-provider orchestration, MCP interoperability, and native COI sub-agents.

It runs on Linux, macOS, Windows, ChromeOS Linux, Android Termux, UserLAnd, VPS hosts, and lightweight edge systems. It can use local GGUF models served by llama.cpp, cloud providers such as Gemini, OpenAI, Anthropic, xAI, Groq, OpenRouter and DeepSeek, or a local-first chain in which a cloud model rescues repeated validator failures.

## Current verified status

Sophyane 21.4.2 is the current packaged release. The release wheel and source distribution have been validated from a clean build, and a fresh virtual-environment installation has been verified to install the declared runtime dependencies automatically.

The v21.4.2 package includes the Sophyane Python runtime, browser assets, code-memory modules, provider integrations, service-fabric components, observability modules, and packaged continual-training C++ sources.

## Install

### Recommended installer

Linux, macOS, ChromeOS Linux, UserLAnd, and Termux:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

### Install directly from the GitHub release

Download the `sophyane-21.4.2-py3-none-any.whl` asset from the v21.4.2 GitHub Release, then install it normally with pip:

```bash
python -m pip install ./sophyane-21.4.2-py3-none-any.whl
```

`pip` reads the wheel metadata and installs required runtime dependencies automatically, including `numpy>=1.26` and `pexpect>=4.9` (plus transitive dependencies such as `ptyprocess`). Third-party dependencies are resolved by pip rather than being duplicated inside the Sophyane wheel.

You can also install the tagged source directly from GitHub:

```bash
python -m pip install "git+https://github.com/badrpk/sophyane.git@v21.4.2"
```

Start:

```bash
sophyane
```

Verify the installation:

```bash
sophyane --version
sophyane --providers
python -m pip check
```

Developer installation:

```bash
git clone https://github.com/badrpk/sophyane.git
cd sophyane
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
```

## What Sophyane includes

### Interactive engineering agent

- Conversational and coding modes
- Persistent projects across follow-up edits
- Explicit build, fix, run, test, browser and repository workflows
- Live provider, validator and execution progress
- Local-first inference with sticky cloud rescue
- Provider-neutral artifact extraction and bounded recovery
- Cloud-aware response timeouts for slower complete artifacts
- Human steering without forcing every request to stop for approval

### Verified browser-product pipeline

For browser applications and games, Sophyane can:

1. Request one complete self-contained HTML artifact.
2. Preserve raw provider evidence for diagnosis.
3. Distinguish structural truncation from semantic defects.
4. Continue only structurally incomplete documents.
5. Request a full-document rewrite for semantic failures.
6. Validate game controls and runtime invariants.
7. Write the accepted artifact into the isolated workspace.
8. Serve and verify that exact page over HTTP.
9. Open the verified URL in a new browser tab.

Recent reliability work prevents complete Snake games with semantic control defects from being incorrectly treated as truncated byte streams. Semantic repair remains the final prompt authority in the live TUI wrapper chain.

### Repository kernel

```bash
sophyane-platform status
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

### COI — Collaborative Orchestration Interface

COI is Sophyane's internal coordination protocol. It manages agents, parent/child tasks, permissions, shared artifacts, event traces, validation and bounded execution.

```bash
sophyane-coi status
sophyane-coi task "Build and validate a responsive snake game" --workspace ./snake
sophyane-coi agent-manifest browser --role validator --skill accessibility --tool browser
```

A task contract contains a goal, owner, workspace, repository, permissions, dependencies, expected outputs, validators and timeout. Agent manifests declare roles, skills, tools, permissions, provider policy and maximum steps.

- **COI** coordinates Sophyane's internal agents, tasks, memory, artifacts and evaluation.
- **MCP** connects Sophyane to external tools, resources and services.

See [COI](docs/COI.md).

### MCP interoperability

```bash
sophyane --mcp-list
sophyane --mcp-call platform
sophyane --mcp-call rag_query --mcp-args '{"q":"provider dispatcher"}'
```

Built-in tools include local RAG, skills, budget status, sandboxed Python, platform probing and public web fetch. The catalog can be wrapped by full MCP stdio or HTTP servers without changing COI task contracts.

See [MCP](docs/MCP.md).

### Native sub-agents

Sophyane supports bounded, provider-neutral agents such as:

- Supervisor and planner
- Repository and symbol agent
- Coding and repair agent
- Browser and accessibility validator
- Test and evaluation agent
- Documentation agent
- Learning and trace-analysis agent

Sub-agents use the provider dispatcher rather than capturing a provider directly. Each receives a constrained task contract and shared context, then writes structured events and results locally.

## Architecture

```text
User / Application
        │
Semantic intent + SLI profile
        │
Sophyane Supervisor
        │
Durable execution graph ───────── Checkpoints / interrupts / traces
        │
COI Orchestrator ──────────────── Contracts / permissions / sub-agents
        │
Provider Dispatcher
   ┌────┴─────────┐
Local models   Cloud providers
        │
Repository Kernel + Coded Sandbox
        │
Validators + repair policy
        │
Verified artifact delivery
        │
MCP Bridge ───────────────────── External tools and services
```

Only the provider dispatcher chooses the active model. COI chooses the agent and task. MCP exposes tools. Validators determine whether execution is complete. Delivery occurs only after the relevant artifact checks pass.

## Evaluation and benchmarking

Run the deterministic product benchmark:

```bash
sophyane-benchmark
```

Write a JSON report:

```bash
sophyane-benchmark --output ~/sophyane-tests/sophyane-baseline.json
```

Include a configured live provider:

```bash
sophyane-benchmark --live
```

The suite covers responsive frontend artifacts, Python/Node/C++ execution where available, repository indexing, requested edits, rollback, verification, COI collaboration, permission boundaries, SLI defect detection, provider escalation, MCP tools and interruption persistence.

Sophyane should be compared with orchestration frameworks such as LangGraph using the same model, prompts, timeouts, isolated workspaces and acceptance tests. Raw graph latency and complete software-delivery capability are separate measurements; Sophyane's benchmark claims apply only to the tasks actually executed.

See [Benchmarking](docs/BENCHMARKS.md) and [Evaluation](docs/EVALUATION.md).

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
sophyane-benchmark
sophyane-web
sophyane-browser
```

Inside the interactive CLI:

```text
/help       command help
/status     provider and runtime state
/new        start a fresh project
/inspect    inspect the current prompt, plan and files
/trace      show or hide raw provider responses
/quit       exit
```

## Prompt guidance

Use this compact pattern for important work:

```text
Goal:
Constraints:
Context/files:
Acceptance criteria:
Tests:
```

Example:

```text
Create one polished self-contained browser game in index.html.
Include keyboard and touch controls, visible state feedback, restart behavior,
mobile support at 320 px width, and verify the final page over HTTP.
```

See [Prompt guide](docs/PROMPT_GUIDE.md).

## Provider modes

At startup Sophyane can run:

1. **Local first** — a local model handles normal work; a configured cloud model can take ownership after repeated deterministic validator failures.
2. **Cloud** — use the selected cloud provider directly.
3. **Current configuration** — retain the existing provider chain.

Cloud-provider calls use a longer default response window than local-model calls so complete engineering artifacts are not discarded at the old universal 60-second boundary. Explicit timeout values remain authoritative.

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
- [Benchmarking](docs/BENCHMARKS.md)
- [COI](docs/COI.md)
- [MCP](docs/MCP.md)
- [Prompt guide](docs/PROMPT_GUIDE.md)
- [Evaluation](docs/EVALUATION.md)
- [Platform kernel](docs/PLATFORM_KERNEL.md)
- [Download and installation](DOWNLOAD.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## Capability labels

- **Implemented** — available in the current release.
- **Experimental** — usable but interfaces may change.
- **Planned** — roadmap only and not presented as available.

COI task contracts, local event tracing, agent manifests, the MCP-lite catalog, repository tools, sandbox preparation, evaluation, compaction, semantic HTML repair, HTTP artifact verification and browser preview are implemented. Distributed cross-device scheduling, a public agent marketplace and full remote MCP transport management remain planned or experimental depending on the adapter.

## License

Sophyane is open source under the MIT License.
