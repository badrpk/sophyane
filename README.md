# Sophyane — Cross-Platform Local Agentic AI Harness

Sophyane is a lightweight, multi-provider AI harness with persistent memory, safe local tools, repository awareness, provider plugins, diagnostics, and a mobile-friendly browser interface.

## Why Sophyane

- **Grok-style CLI** — banner, slash commands (`/help`, `/model`, `/status`, `/doctor`, `/new`, `/quit`, …), spinner, session scrollback
- **Automatic open-model rescue** — if frontier API keys hit quota/credit/auth failures, Sophyane profiles your hardware, installs Ollama when needed, pulls a RAM-fit open model, starts serving, and continues the session
- Works with Google Gemini, OpenAI, Claude, Groq, xAI Grok, DeepSeek, OpenRouter, and local Ollama
- Multi-provider fallback chain driven by `~/.config/sophyane/llm.json`
- First-run provider wizard securely asks for the API key
- Persistent SQLite memory
- Safe local system and repository tools + sandboxed harness execution
- Plugin-based provider architecture
- CLI plus browser interface
- Zero mandatory third-party runtime dependencies
- Tested on Windows, macOS, and Linux through GitHub Actions

## Grok-style interactive CLI

```bash
sophyane
```

```
  ◆ Sophyane 16.1.0
  Terminal agentic harness  ·  Grok-style CLI
  provider openai  model gpt-5-mini  hw nano/2700MB
  Type a message · /help for commands · /local for open models · /quit to exit

❯ refactor the auth module
```

Useful slash commands:

| Command | Action |
|---------|--------|
| `/help` | Command palette |
| `/status` | Provider, model, fallback chain |
| `/model [name]` | Show recommendations or switch model |
| `/local` | Force hardware-fit open model install + serve |
| `/doctor` | Diagnostics |
| `/new` | Clear session scrollback |
| `/session-info` | Hardware + session stats |
| `/quit` | Exit |

## Appliance boot (SoC / chip / gateway)

Install Sophyane on Linux-capable processors and boot like an appliance:

```bash
sophyane --boot                          # ethernet + kernel + mesh + API
sophyane --boot --wifi-ssid MYWIFI --wifi-psk 'secret'
sophyane --install-chip && sophyane --install-appliance-unit
sophyane --audit                         # verify every major feature

# Continual federated training (C++ core, existing GGUF weights, user-device compute)
sophyane --train-opt-in
sophyane --train-step                    # local C++ PEFT step
sophyane --train-round                   # step + mesh + FedAvg
sophyane --train-status
```

See [docs/APPLIANCE_BOOT.md](docs/APPLIANCE_BOOT.md).

## Sophyane Browser + daily self-improvement

```bash
sophyane-browser                 # Chromium profile + home UI
sophyane --fetch https://...     # scrape web
sophyane --learn https://...     # scrape → hash-chain improvement
sophyane --improve-export        # daily epoch to improvements/
```

See [docs/BROWSER_AND_SELF_IMPROVE.md](docs/BROWSER_AND_SELF_IMPROVE.md).

## Mesh (USB · WiFi · shared compute/storage)

Connect devices that run Sophyane — or install a clone — then share control,
compute, and storage:

```bash
sophyane --mesh-serve              # peer API on :8777
sophyane --mesh-discover           # WiFi/LAN + USB/ADB
sophyane --mesh-install HOST --yes # clone Sophyane onto peer
sophyane --mesh-compute "hello"    # use another device's compute
```

See [docs/MESH.md](docs/MESH.md).

## AI Kernel (intelligence control plane)

Sophyane includes a **userspace AI Kernel** that coordinates hardware adapters,
open-source stacks (CUDA/llama.cpp/…), app factories, and ERP connectors:

```bash
sophyane --kernel
sophyane --create-app web --app-name "My Site"
sophyane --create-app android --app-name "FieldApp"
sophyane --erp oracle   # set ORACLE_ERP_BASE_URL + token
```

See [docs/AI_KERNEL.md](docs/AI_KERNEL.md).

## Hardware & multi-language API

Sophyane integrates with major chip ecosystems **at the host/gateway layer** and
exposes one API for **Python, C++, and JavaScript**:

```bash
sophyane --hardware           # vendor + open-source compatibility report
sophyane --hardware-json
sophyane --hardware-api       # HTTP API on :8770 for C++/JS/Python clients
```

See [docs/HARDWARE_SOFTWARE_API.md](docs/HARDWARE_SOFTWARE_API.md) and `sdk/`.

## Portability (PC · phone · cloud · IoT)

Sophyane adapts by **equipment class** — from constrained edge gateways to full workstations:

| Surface | How |
|---------|-----|
| Linux / macOS | `install.sh` |
| Windows | `install.ps1` |
| Android | Termux + `install.sh` (mobile profile) |
| iOS | Web UI or SSH companion host |
| Cloud VM | install + systemd daemon timer |
| PLC / meter gateway | Linux edge host + edge profile |

```bash
sophyane --platform      # OS, RAM, equipment class, recommended profile
sophyane --edge-health   # JSON health for edge/IoT deployments
```

See [docs/PORTABILITY.md](docs/PORTABILITY.md) for phone→PC→cloud→IoT architecture and industrial safety notes.

## Competitive exams

```bash
python benchmarks/competitive_matrix.py
python benchmarks/harness_acceptance.py
cat docs/COMPETITIVE_EXAM.md
```

## Automatic local open models

When every configured cloud provider fails with quota, billing, or auth errors, Sophyane:

1. Profiles CPU / RAM / free disk (tiers: `nano`, `micro`, `small`, `standard`)
2. **Tries Ollama** — install into `~/.local/bin`, `ollama serve`, pull a tier-fit model
3. **If Ollama fails** (download too large, no space, binary broken) → **Hugging Face GGUF**
   - Picks a hardware-fit GGUF (e.g. Qwen2.5-0.5B / TinyLlama / SmolLM2 on thin Chromebooks)
   - Downloads from Hugging Face (`huggingface.co/.../resolve/main/*.gguf`)
   - Optional GitHub release mirrors when configured
4. Installs **llama.cpp** `llama-server` + `llama-cli` from GitHub releases (`ggml-org/llama.cpp`)
5. Starts a local OpenAI-compatible server on `127.0.0.1:8765`
6. Switches config to `provider=local_gguf` (or `ollama`) and retries the request

Force it any time:

```bash
sophyane /local
# or inside the TUI:
/local
```

## Fastest installation

### Linux, macOS, ChromeOS Linux, UserLAnd, and Termux

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
```

Then open a new terminal and run:

```bash
sophyane
```

Termux users may first install curl:

```bash
pkg update && pkg install curl
```

### Windows PowerShell

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

Then open a new terminal:

```powershell
sophyane
```

### Manual installation

```bash
git clone https://github.com/badrpk/sophyane.git
cd sophyane
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
sophyane
```

Windows activation:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install .
sophyane
```

Do not install into Debian's system Python. Sophyane's installer automatically creates an isolated virtual environment and avoids PEP 668 errors.

## Browser and mobile interface

Start the private local browser interface:

```bash
sophyane-web
```

It opens at:

```text
http://127.0.0.1:8765
```

To access it from an Android phone, iPhone, iPad, or another computer on the same trusted network:

```bash
sophyane-web --host 0.0.0.0
```

Then open the host computer's LAN address, for example:

```text
http://192.168.1.25:8765
```

Do not expose the built-in web server directly to the public internet. Use a trusted VPN or an authenticated reverse proxy for remote access.

### Platform notes

| Platform | Local CLI | Browser UI |
|---|---:|---:|
| Windows 10/11 | Yes | Yes |
| macOS | Yes | Yes |
| Linux | Yes | Yes |
| ChromeOS Linux/Penguin | Yes | Yes |
| Android Termux | Yes | Yes |
| Android UserLAnd | Yes | Yes |
| iPhone/iPad | Not natively | Yes, through Safari connected to a Sophyane host |

Apple does not allow a normal always-on Python CLI installation on stock iOS. The supported iPhone/iPad experience is the responsive browser interface served by Windows, macOS, Linux, Android Termux, a VPS, or a home server.

## First run

Sophyane displays a provider menu:

```text
1. Anthropic Claude
2. DeepSeek
3. Google Gemini
4. Groq
5. Ollama (local)
6. OpenAI
7. OpenRouter
8. xAI Grok
```

Choose a provider, accept or change the model, and enter its API key. The key is stored in the user's private configuration directory, not in the repository.

## Common commands

```bash
sophyane --version
sophyane --providers
sophyane --status
sophyane --setup
sophyane --doctor
sophyane-web
```

Interactive commands:

```text
tools
status
memory
/remember My main project is SHMRY.
/system
/repo
/files
/read path/to/file
/shell uname -a
/doctor
/exit
```

## Examples

```bash
sophyane "What is my main project?"
sophyane "Check my system configuration"
sophyane "Analyze the src/ directory and map internal imports"
sophyane "/remember My preferred language is Python."
```

## Updating

Installer-based installations can be updated by running the same installer again.

Linux/macOS/Termux/UserLAnd:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
```

Windows:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

Repository installations:

```bash
git pull --ff-only
python -m pip install --upgrade .
```

## Development

```bash
git clone https://github.com/badrpk/sophyane.git
cd sophyane
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
sophyane --doctor
```

Every push and pull request is tested across Windows, macOS, and Linux with Python 3.10 through 3.13.

## Privacy and safety

- API keys are never committed to Git
- Memory is stored locally in SQLite
- Destructive shell commands are blocked
- Approved shell commands require confirmation
- The web interface binds to localhost by default
- Sophyane logs failures for diagnostics

## Community

Contributions are welcome:

1. Fork the repository
2. Create a feature branch
3. Add tests
4. Submit a pull request

Please use GitHub Issues for bug reports, platform compatibility problems, feature requests, and provider requests.

## License

MIT License. See `LICENSE`.
