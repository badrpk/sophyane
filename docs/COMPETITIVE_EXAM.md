# Sophyane competitive & portability exam

Updated: 2026-07-15

## Live functional exam (this host)
- Functional checks: **52/52 PASS**
- Doctor: ALL CORE CHECKS PASSED (when run on Penguin exam host)
- Harness / multi-agent / execution evidence: PASS

## Competitors scored (14 ecosystems)

Original 4: LangGraph, CrewAI, Cursor, Replit

**+10 more:** AutoGen, Semantic Kernel, LlamaIndex, Haystack, Aider, Continue.dev, OpenHands, MetaGPT, OpenAI Swarm, Dify

### Averages (0–10, higher better)

- **Sophyane**: 7.59
- **Dify**: 5.59
- **SemanticKernel**: 5.45
- **LangGraph**: 5.32
- **Haystack**: 4.91
- **LlamaIndex**: 4.86
- **CrewAI**: 4.77
- **AutoGen**: 4.77
- **OpenHands**: 4.68
- **Cursor**: 4.41
- **Aider**: 4.23
- **Continue.dev**: 4.14
- **Replit**: 4.05
- **MetaGPT**: 4.00
- **OpenAI_Swarm**: 3.41

### Dimension wins

- **Sophyane**: 14
- **LangGraph**: 2
- **Cursor**: 2
- **Replit**: 2
- **SemanticKernel**: 2
- **Aider**: 2
- **CrewAI**: 1
- **LlamaIndex**: 1
- **Continue.dev**: 1
- **AutoGen**: 0
- **Haystack**: 0
- **OpenHands**: 0
- **MetaGPT**: 0
- **OpenAI_Swarm**: 0
- **Dify**: 0

## Portability claim (honest scope)

| Layer | Status |
|-------|--------|
| Linux / Crostini | **Measured live** |
| Windows / macOS install scripts | **Shipped** (`install.ps1`, `install.sh`) |
| Android Termux | **Supported path** (mobile profile) |
| iOS on-device | **Companion mode** (web/SSH host) — not full native IDE |
| Cloud VM / container | **Supported** (server/cloud equipment class) |
| PLC / meter / IoT chip | **Edge profile + host adapters** — agent runtime portable; device protocols are integrations |

Sophyane does **not** replace vendor PLC firmware. It runs on any host that can run Python 3.10+ and adapts model size, tools, and planner weight by equipment class.

## Reproduce
```bash
sophyane --doctor && sophyane --platform && sophyane --edge-health
python -m pytest tests/ -q
python benchmarks/competitive_matrix.py
python benchmarks/harness_acceptance.py
```
