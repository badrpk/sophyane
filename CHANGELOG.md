# Changelog

## 17.5.0 — 2026-07-15

### Highlights
- Multi-rail payments: Stripe, Monero, JazzCash/EasyPaisa/UPaisa, exchange hooks
- Multi-channel messaging: Telegram @sophyanebot, Email, WhatsApp
- Product knowledge for instant payment/channel answers
- Community docs: CONTRIBUTING.md, COMMUNITY.md



## 17.2.0 — 2026-07-15

### Added
- **Sophyane Browser** Perplexity-style ask/sources UI (home app)
- GitHub download package under `browser/` + `dist/sophyane-browser-*.tar.gz`
- `browser/install.sh` / `install.ps1` install from GitHub
- Start/cloud pages link to GitHub Releases; new-tab open remains
- Workflow: `.github/workflows/sophyane-browser-release.yml`


## 17.1.0 — 2026-07-15

### Added
- **Sophyane Cloud portal**: investor website + public API token system
- Ultra-low pricing (free / $1 builder / hybrid edge free device compute)
- Namecheap API client: list domains, longest expiry, set A/AAAA to static IP
- CLI: `--cloud-serve`, `--namecheap-domains`, `--namecheap-longest`, `--namecheap-setup-site`
- Docs: `docs/CLOUD_PORTAL.md`, `website/`


## 17.0.0 — 2026-07-15

### Added — future-complete agent surface
- **Capability matrix** (`--capabilities`) covering modern agent features
- **Skills** packs (`--skills`, `--skill`)
- **Local RAG** (`--rag-add`, `--rag-query`)
- **Scheduler** cron-like jobs (`--schedule`, `--schedule-run`)
- **Budgets** token/cost (`--budget-status`)
- **HITL** approvals (`--hitl-request`, `--approve`, `--deny`)
- **Observability** traces (`--trace-list`)
- **Sandboxed Python REPL** (`--repl`)
- **MCP-lite** tool bridge (`--mcp-list`, `--mcp-call`)
- **Permissions** profiles (`--permissions`)
- **Checkpoints** (`--checkpoint-list`)
- **Notifications** (`--notify-test`)
- **Multimodal hooks** (`--image`, `--voice-status`)
- Docs: `docs/AGENT_CAPABILITIES.md`
- Hardened `install.sh` always picks latest release/tag + deps/venv/C++ core

### Also includes (16.9 work)
- Tough-100 harness exam + expert hybrid answers


## 16.8.0 — 2026-07-15

### Added
- **Continual federated training** over existing local LLM (GGUF) weights
- Pure **C++17** train core: `sophyane-train-core` (local PEFT step + FedAvg)
- Opt-in multi-device contribution via mesh (`/v1/mesh/train/*`)
- CLI: `--train-status`, `--train-opt-in`, `--train-step`, `--train-round`, `--train-build-core`
- Docs: `docs/CONTINUAL_FEDERATED.md`

### Design
- Base GGUF stays on device; only small adapter deltas are federated
- Training hot path is C++ only for hardware efficiency on edge chips
- Privacy: digests by default; contribution requires explicit opt-in

## 16.7.0 — 2026-07-15

### Added
- **Appliance boot** for Linux-capable chips/SoCs (`--boot`, Ethernet + Wi‑Fi bring-up)
- Chip install helper + systemd user unit (`--install-chip`, `--install-appliance-unit`)
- Integrated **feature audit** (`--audit`) covering all major subsystems
- Network capability report (cable Ethernet + Wi‑Fi tool/path detection)
- Docs: `docs/APPLIANCE_BOOT.md`

### Fixed
- Idempotent boot: mesh `:8777` and Hardware API `:8770` reuse existing listeners (no EADDRINUSE fail)
- Mesh hello probe accepts wrapped `{"ok":true,"result":{...}}` responses

### Verified
- Feature audit **28/28 (100%)** — kernel, mesh, browser, web intel, improve, ERP, apps, hardware, appliance boot
- Live boot: ethernet up, internet online, kernel/mesh/API healthy
- Pytest suite green for appliance, mesh, hardware, kernel, browser

## 16.6.0 — 2026-07-15

### Added
- **Sophyane Browser** (Chromium profile + local home UI; `sophyane-browser`)
- Web intel: fetch/scrape internet pages for agent learning
- Blockchain-style self-improvement ledger + daily epoch export
- GitHub Action: daily improvement catalog commit
- Install opens browser on graphical sessions; docs/BROWSER_AND_SELF_IMPROVE.md

## 16.5.0 — 2026-07-15

### Added
- **Sophyane Mesh**: WiFi/LAN discovery, USB serial + ADB inventory
- Peer clone install over SSH/ADB (`--mesh-install --yes`)
- Shared compute offload (`--mesh-compute`) and mesh storage share
- Mesh peer server (`--mesh-serve` on port 8777)
- Docs: `docs/MESH.md`

## 16.4.0 — 2026-07-15

### Added
- **Sophyane AI Kernel** (userspace control plane): bus, modules, hardware/software services
- App factory: web, Android, HarmonyOS, iOS, desktop Python, API scaffolds
- ERP connectors: Oracle, SAP, Odoo, Dynamics, NetSuite, ERPNext
- CLI: `--kernel`, `--kernel-status`, `--create-app`, `--erp`
- API: `/v1/kernel`, `/v1/apps/create`, `/v1/erp`, `/v1/erp/query`
- Docs: `docs/AI_KERNEL.md`

## 16.3.0 — 2026-07-15

### Added
- Hardware vendor registry (20+ chip makers: NVIDIA, Intel, AMD, Qualcomm, Micron, …)
- Open-source/freeware integration probe (llama.cpp, ONNX Runtime, MQTT, Modbus, …)
- Unified Hardware API for Python / C++ / JavaScript (`sophyane --hardware-api`)
- CLI: `--hardware`, `--hardware-json`, `--hardware-api`
- SDK: `sdk/cpp`, `sdk/js`, `sdk/python` examples
- Docs: `docs/HARDWARE_SOFTWARE_API.md`

## 16.2.0 — 2026-07-15

### Added
- Cross-platform `platform_probe` (Windows/macOS/Linux/Android/iOS/edge/cloud)
- Edge/IoT agent profile for constrained chips (PLC gateways, meters, phones)
- CLI: `--platform`, `--edge-health`
- Portability guide `docs/PORTABILITY.md`
- Competitive matrix vs 14 agent/harness ecosystems (`benchmarks/competitive_matrix.py`)
- Full capability exam report for GitHub consumers

### Changed
- Version 16.2.0; equipment-class adaptive profiles


## 16.1.1 — 2026-07-15

### Added

- Hugging Face GGUF open-model path when Ollama cannot install or run
- GitHub `llama.cpp` runtime install with shared libraries + PATH wrappers
- `local_gguf` provider (llama-server on `:8766`, llama-cli fallback)
- Hardware-tier GGUF catalog (SmolLM2 / Qwen2.5 0.5B / TinyLlama / larger tiers)

### Fixed

- Port clash with `sophyane-web` on 8765 — model server defaults to **8766**
- Thin binary-only llama install missing `libllama-*-impl.so`
- Disk reclaim of failed Ollama extracts before HF bootstrap

### Verified

- Freeing `ollama-extract` recovered ~1.6GB on constrained Crostini
- Qwen2.5-0.5B GGUF served via llama-server; smoke generate succeeded

## 16.1.0 — 2026-07-15

### Added

- Grok-style interactive CLI (`tui.py`): banner, slash palette, spinner, scrollback, `/model`, `/local`, `/session-info`, `/export`, multiline drafts
- Hardware-aware local open-model bootstrap (`local_runtime.py`): profile RAM/disk, install Ollama, pull tier-fit model, warm-up, auto-switch config
- Automatic rescue inside `FallbackProvider` when frontier APIs fail with quota/credit/auth errors
- Sandboxed harness runner, expanded guardrails, `/daemon-tick` local queue processor (from 16.0.8 line)

### Changed

- Interactive entry now uses the Grok-style TUI instead of a bare `sophyane>` REPL
- Runtime identity banner aligned with Grok CLI conventions
- `llm.json` fallback order prefers recovered Ollama after auto-promotion

### Verified

- Unit tests for harness, fallback, daemon, local runtime, and TUI slash palette
- Harness acceptance benchmark PASS
- Systemd `sophyane-runtime.timer` daemon-tick idle SUCCESS without cloud LLM

## 11.0.0 — 2026-07-14

### Added

- Stateful autonomous software-build graph
- Plan, build, test, repair, verify, and report nodes
- Bounded retry loop and graph safety limit
- Inventory REST API reference workflow using Python and SQLite
- Repository and HTTP automated tests for generated projects
- Machine-readable build evidence in `benchmark_report.json`
- Acceptance-criteria and evidence-backed completion contract

### Changed

- Supported autonomous requests execute before conversational LLM routing
- Backend requests are no longer satisfied by browser-only `index.html` generation
- Completion claims now require commands, exit codes, test results, and verification
- Package description and metadata now reflect autonomous stateful execution

### Verified

The reference workflow was independently tested on Android 15 Termux/aarch64. It created the expected files, ran four automated tests successfully, recorded exit code `0`, produced no `index.html`, and passed every verification check.
