# Sophyane Harness 21.4.2

**A local-first AI software engineering harness with five original execution modes: Sophyane Auto, Internet, Local LLM, Cloud LLM, and Sophyane Learning.**

Sophyane Harness is the public user experience for Sophyane. It keeps Sophyane's engineering runtime — planning, building, repairing, validating, executing, repository intelligence, browser verification, orchestration, MCP interoperability, COI agents, and durable state — behind one harness-style launch flow.

## Install

Linux, macOS, ChromeOS Linux, UserLAnd, and Android Termux:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

Then start:

```bash
sophyane-harness
```

The traditional advanced CLI remains available:

```bash
sophyane
```

## Sophyane Harness modes

At launch, Sophyane Harness exposes the five original Sophyane session choices:

1. **Sophyane Auto** — intelligently decide between available deterministic, internet, local-model, and cloud capabilities using Sophyane's adaptive orchestration/race policy.
2. **Internet** — SLI Graph + memory + internet acquisition, with no local or cloud LLM required.
3. **Local LLM** — local llama.cpp / GGUF inference only; cloud fallback is disabled.
4. **Cloud LLM** — use a configured cloud provider directly.
5. **Sophyane Learning** — continuous SLI topic acquisition + embedding until stopped with Ctrl+C.

Select a mode explicitly:

```bash
sophyane-harness auto
sophyane-harness internet
sophyane-harness local-llm
sophyane-harness cloud-llm
sophyane-harness learning
```

Launch the browser interface under the same mode contract:

```bash
sophyane-harness auto --web
sophyane-harness internet --web
sophyane-harness local-llm --web
sophyane-harness cloud-llm --web
sophyane-harness learning --web
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

Sophyane remains Python-native. The installer may also provision an optional modern JavaScript toolchain for the browser/developer harness experience: Node.js 22+, npm, Corepack, and pnpm 11.7.0. Those tools are support dependencies, not replacements for the Sophyane Python runtime.

## Optional comprehensive toolchain

Where supported by the universal installer, Sophyane Harness can prepare:

- Python 3.10+ and a managed virtual environment
- `numpy`, `pexpect`, and Sophyane's declared Python dependencies
- Node.js 22+ for modern browser/developer tooling
- npm
- Corepack
- pnpm 11.7.0
- Git
- browser/runtime tools already used by Sophyane when available

The goal is a comprehensive install-and-launch experience without pretending Sophyane needs another project's entire dependency graph. Large third-party packages such as unrelated agent SDKs, vendor-specific CLIs, or workspace-only build tools are not installed unless Sophyane itself actually requires them.

## Current verified status

Sophyane 21.4.2 is the current packaged release. The full official test suite has been validated on the current code line, including race orchestration, answer-completion gating, deterministic execution behavior, provider policy, repository intelligence, browser-oriented validation, and runtime safety.

The universal installer uses a replace-the-runtime / preserve-the-user model: it installs a fresh managed runtime, validates dependencies and core behavior, and only then retires the previous managed runtime. User configuration, state, workspaces, memory, credentials, and generated projects remain outside the replaceable runtime directories.

## Verify installation

```bash
sophyane --version
sophyane --providers
sophyane --doctor
sophyane-harness --help
python -m pip check
node -v        # when optional Node toolchain is installed
pnpm --version # when optional pnpm toolchain is installed
```

## What is inside Sophyane Harness

### Sophyane Auto

Sophyane owns the execution policy. It can choose deterministic capabilities and race eligible workers rather than forcing one provider at startup.

### Internet mode

Internet mode uses Sophyane's SLI Graph and acquisition pipeline. It is intended for memory + internet knowledge acquisition without requiring a local or cloud LLM.

### Local LLM mode

Local mode uses a configured llama.cpp / GGUF runtime. The local model is authoritative for that session and cloud rescue is disabled.

### Cloud LLM mode

Cloud mode uses a configured provider such as Gemini, OpenAI, Anthropic, xAI, Groq, OpenRouter, DeepSeek, or another installed Sophyane provider plugin.

### Sophyane Learning

Learning mode continuously acquires topic material and updates Sophyane's local learning/vector state until the user stops it.

### Deterministic engineering runtime

- Semantic intent routing
- Durable execution graph
- Repository indexing and symbol discovery
- Sandboxed filesystem execution
- Validator-driven repair
- Deterministic capability routing and race arbitration
- Execution traces, checkpoints, and evidence

### Browser and artifact verification

Sophyane can generate and validate software artifacts, serve browser products over HTTP, check structural and semantic conditions, and use browser-oriented evidence where the relevant runtime is available.

### COI and MCP

COI coordinates Sophyane's internal agents, tasks, artifacts, permissions, validation, and bounded execution. MCP connects Sophyane to external tools and resources.

## Core commands

```bash
sophyane-harness
sophyane-harness auto
sophyane-harness internet
sophyane-harness local-llm
sophyane-harness cloud-llm
sophyane-harness learning
sophyane
sophyane-web
sophyane-browser
sophyane-platform status
sophyane-coi status
sophyane-benchmark
```

Advanced/internal commands remain available for users who need SLI training, auditing, missions, MCP, release gates, or platform diagnostics.

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
  ├── Sophyane Auto
  ├── Internet
  ├── Local LLM
  ├── Cloud LLM
  └── Sophyane Learning
  │
Sophyane Supervisor / Race Orchestrator
  │
Semantic + durable execution graph
  │
Repository kernel + sandbox + validators
  │
Artifacts / browser verification / MCP / COI
```

The five modes select session policy. They do not redefine ownership of lower-level capabilities.

## Capability boundaries

The five-mode harness does not imply that every machine has every optional dependency. Internet mode requires network access. Local LLM mode requires a configured local GGUF runtime. Cloud LLM mode requires provider credentials. Browser verification requires a compatible browser/runtime. Learning mode requires local writable state and may use internet acquisition depending on the task.

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
