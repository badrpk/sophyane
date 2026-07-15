# Sophyane portability — intelligence across equipment classes

Sophyane is designed as a **portable agentic harness**: one Python codebase that
adapts its profile from **nano edge devices** to **phones, PCs, cloud VMs, and
industrial gateways**.

> Hardware drivers for PLCs/meters are **host integrations** (Modbus, MQTT, OPC-UA,
> vendor SDKs). Sophyane provides the **agent runtime, safety, memory, and model
> routing** that sits above those drivers.

## Supported OS families

| OS | Install | Notes |
|----|---------|--------|
| **Linux** | `curl -fsSL …/install.sh \| sh` | Primary; Debian/Ubuntu/Fedora/Arch/Crostini |
| **macOS** | same install.sh | Intel + Apple Silicon; Homebrew Python 3 |
| **Windows** | `install.ps1` | PowerShell; user-local venv under profile |
| **Android** | Termux + install.sh | Mobile profile; prefer small GGUF/Ollama |
| **iOS** | Companion | Use web UI or SSH to a paired Linux/Mac host; on-device Python is constrained |
| **Cloud** | Docker / systemd / install.sh | Server profile; full coding agent |
| **Edge / IoT gateway** | Linux ARM install | Edge/nano profile; short chat + tools |

## Equipment classes (auto-detected)

| Class | Typical RAM | Profile | Behavior |
|-------|-------------|---------|----------|
| `nano_edge` | < 512 MB | `nano` | Health + tiny chat; no coding planner |
| `edge` | < 1.5 GB | `edge` | Tiny GGUF or cloud API; bounded tools |
| `mobile` | phones | `mobile` | Termux/PWA; small models |
| `workstation` | laptops/desktops | `full` | Full CLI + coding agent |
| `server` / `cloud` | ≥ 16 GB or VM | `full` | Multi-agent + large models |

Probe:

```bash
sophyane --platform
# or
python -c "from sophyane.platform_probe import format_platform_report; print(format_platform_report())"
```

Edge health:

```bash
sophyane --edge-health
```

## Phone → PC → cloud → IoT path

```
┌─────────────┐    HTTPS/SSH     ┌──────────────┐
│ Phone       │ ───────────────► │ PC / Server  │
│ Termux/PWA  │                  │ full agent   │
└─────────────┘                  └──────┬───────┘
                                        │ MQTT/Modbus/OPC
                                        ▼
                                 ┌──────────────┐
                                 │ PLC / meter  │
                                 │ gateway host │
                                 └──────────────┘
```

1. **Phone** — lightweight chat / approve actions (mobile profile).  
2. **PC** — full coding agent, repo tools, multi-provider fallback.  
3. **Cloud** — always-on daemon queue (`sophyane-runtime.timer` / systemd).  
4. **IoT / PLC / meter** — edge host runs Sophyane Edge + device protocol adapters.

## Local models by class

| Class | Recommendation |
|-------|----------------|
| nano_edge | Cloud API only, or SmolLM2-class GGUF if ≥400 MB free |
| edge / mobile | Qwen2.5-0.5B / TinyLlama GGUF or Ollama |
| workstation | Ollama 1B–8B or frontier APIs with fallback |
| server/cloud | Larger open models or multi-provider routing |

Auto-rescue when cloud credits fail:

```bash
sophyane /local
```

## Safety on industrial equipment

- Guardrails block destructive shell patterns.  
- Edge prompt emphasizes **no invented sensor values**.  
- Dangerous tools require approval.  
- PLC write operations must go through **explicit, audited adapters** — never free-form shell to live controllers in production.

## Continuous verification

```bash
sophyane --doctor
sophyane --platform
python -m pytest tests/ -q
python benchmarks/harness_acceptance.py
```
