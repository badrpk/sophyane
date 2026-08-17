# Sophyane Harness 21.4.2

**A local-first AI software engineering harness with four clear execution modes: Deterministic, Internet, Local LLM, and Cloud LLM.**

Sophyane Harness is the public user experience for Sophyane. It keeps Sophyane's existing engineering runtime — planning, building, repairing, validating, executing, repository intelligence, browser verification, orchestration, MCP interoperability, COI agents, and durable state — behind a simple harness-style launch flow.

## Install

Linux, macOS, ChromeOS Linux, UserLAnd, and Android Termux:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

Then start the harness:

```bash
sophyane-harness
```

or start Sophyane directly:

```bash
sophyane
```

## Sophyane Harness modes

At launch, Sophyane Harness exposes exactly four public execution choices:

1. **Deterministic** — Sophyane execution/orchestration without cloud rescue.
2. **Internet** — SLI Graph + internet acquisition, with no local or cloud LLM required.
3. **Local LLM** — local llama.cpp / GGUF inference only; cloud fallback is disabled.
4. **Cloud LLM** — use a configured cloud provider.

You can select a mode explicitly:

```bash
sophyane-harness deterministic
sophyane-harness internet
sophyane-harness local-llm
sophyane-harness cloud-llm
```

Launch the browser interface with the same mode contract:

```bash
sophyane-harness deterministic --web
sophyane-harness internet --web
sophyane-harness local-llm --web
sophyane-harness cloud-llm --web
```

## Harness-style download experience

For a new user, the normal flow is intentionally short:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
sophyane-harness
```

Developer flow:

```bash
git clone https://github.com/badrpk/sophyane.git
cd sophyane
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
sophyane-harness
```

The goal is the same class of simple harness experience users expect from modern coding-agent harnesses: clone/install, build or install dependencies, then launch one clear command. Sophyane remains a Python-native project and does not copy another harness's internal implementation or dependency stack.

## Current verified status

Sophyane 21.4.2 is the current packaged release. The full official test suite has been validated on the current code line, including race orchestration, answer-completion gating, deterministic execution behavior, provider policy, repository intelligence, browser-oriented validation, and runtime safety.

The universal installer uses a replace-the-runtime / preserve-the-user model: it installs a fresh managed runtime, validates dependencies and core behavior, and only then retires the previous managed runtime. User configuration, state, workspaces, memory, credentials, and generated projects remain outside the replaceable runtime directories.

## Verify installation

```bash
sophyane --version
sophyane --providers
sophyane --doctor
python -m pip check
```

## What is inside Sophyane Harness

### Deterministic engineering runtime

- Semantic intent routing
- Durable execution graph
- Repository indexing and symbol discovery
- Sandboxed filesystem execution
- Validator-driven repair
- Deterministic capability routing and race arbitration
- Execution traces, checkpoints, and evidence

### Internet mode

Internet mode uses Sophyane's SLI Graph and acquisition pipeline. It is intended for memory + internet knowledge acquisition without requiring a local or cloud LLM.

### Local LLM mode

Local mode uses a configured llama.cpp / GGUF runtime. The local model is authoritative for that session and cloud rescue is disabled.

### Cloud LLM mode

Cloud mode uses a configured provider such as Gemini, OpenAI, Anthropic, xAI, Groq, OpenRouter, DeepSeek, or another installed Sophyane provider plugin.

### Browser and artifact verification

Sophyane can generate and validate software artifacts, serve browser products over HTTP, check structural and semantic conditions, and use browser-oriented evidence where the relevant runtime is available.

### COI and MCP

COI coordinates Sophyane's internal agents, tasks, artifacts, permissions, validation, and bounded execution. MCP connects Sophyane to external tools and resources.

## Core commands

```bash
sophyane-harness
sophyane-harness deterministic
sophyane-harness internet
sophyane-harness local-llm
sophyane-harness cloud-llm
sophyane
sophyane-web
sophyane-browser
sophyane-platform status
sophyane-coi status
sophyane-benchmark
```

Advanced/internal commands remain available for users who need SLI training, continuous learning, auditing, missions, MCP, release gates, or platform diagnostics. They are not part of the four-mode public harness surface.

## Runtime layout

```text
~/.local/share/sophyane/
├── system/            managed Sophyane source/runtime
├── venv/              managed Python environment
├── user-work/         preserved legacy/local work
├── artifacts/         validated outputs
├── logs/              execution logs
├── state/             durable runtime state
├── platform/          repository, agents, runs and knowledge
└── coi/               collaborative orchestration state
```

## Architecture

```text
User
  │
Sophyane Harness
  ├── Deterministic
  ├── Internet
  ├── Local LLM
  └── Cloud LLM
  │
Sophyane Supervisor / Race Orchestrator
  │
Semantic + durable execution graph
  │
Repository kernel + sandbox + validators
  │
Artifacts / browser verification / MCP / COI
```

The four modes select execution policy. They do not redefine ownership of lower-level capabilities. Sophyane remains the semantic planner/orchestrator; external or specialized components continue to own their own runtime boundaries.

## Capability boundaries

The four-mode harness does not imply that every machine has every optional dependency. Internet mode requires network access. Local LLM mode requires a configured local GGUF runtime. Cloud LLM mode requires provider credentials. Browser verification requires a compatible browser/runtime. Deterministic mode is the least externally dependent path.

## Documentation

- [Download and installation](DOWNLOAD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Benchmarking](docs/BENCHMARKS.md)
- [COI](docs/COI.md)
- [MCP](docs/MCP.md)
- [Prompt guide](docs/PROMPT_GUIDE.md)
- [Evaluation](docs/EVALUATION.md)
- [Platform kernel](docs/PLATFORM_KERNEL.md)
- [Changelog](CHANGELOG.md)

## License

Sophyane is open source under the MIT License.
