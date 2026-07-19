# Sophyane — Local and Frontier Agentic AI Runtime

**Version 18.0.0** · Open source · [Download Sophyane](DOWNLOAD.md)

Sophyane is one deterministic autonomous coding runtime with two operating editions:

| Edition | Primary machine | LLMs | Primary role |
|---|---|---|---|
| **Sophyane Local** | Android phone with Termux | Local GGUF through `llama-server`, or Ollama | Private, offline, low-cost local inference and phone-side development |
| **Sophyane Frontier** | Chromebook Linux/Penguin | Gemini, OpenAI, Anthropic Claude, xAI Grok, Groq, OpenRouter, DeepSeek | Frontier-model development, repository maintenance, testing, and GitHub updates |

These are not separate incompatible projects. They share the same repository, runtime, file protocol, deterministic build pipeline, and release history. The configured provider determines which edition is active.

## Download

Open the edition-aware download page:

**https://github.com/badrpk/sophyane/blob/main/DOWNLOAD.md**

Universal installer for Linux, macOS, ChromeOS Linux/Penguin, Android Termux, and UserLAnd:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

## Sophyane Local

Sophyane Local runs inference on the device. It is the recommended edition for the Android phone and Termux environment.

```bash
pkg update && pkg install curl
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
sophyane /local
```

Inside the interactive CLI:

```text
/local
```

Typical local providers:

```text
local_gguf
ollama
```

The local GGUF path prefers an OpenAI-compatible `llama-server` endpoint and can use `llama-cli` as a bounded fallback where the platform supports it. On constrained devices, Sophyane keeps prompts and output bounded and displays progress heartbeats during long provider requests.

### Phone-managed updates

The Android phone is the primary maintenance environment for Sophyane Local behavior, Termux compatibility, GGUF model serving, and constrained-device performance.

```bash
cd "$HOME/sophyane"
git pull --ff-only
python -m pip install --upgrade .
sophyane --doctor
```

## Sophyane Frontier

Sophyane Frontier uses hosted frontier LLMs for stronger reasoning, larger coding tasks, repository work, and cloud-backed inference.

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
sophyane --setup
```

Supported frontier providers include:

```text
Google Gemini
OpenAI
Anthropic Claude
xAI Grok
Groq
OpenRouter
DeepSeek
```

Example:

```bash
export GEMINI_API_KEY="your_key"
sophyane
```

### Chromebook/Penguin-managed updates

The Chromebook Linux/Penguin checkout is the primary maintenance environment for Sophyane Frontier, frontier-provider integrations, automated tests, documentation, and GitHub updates.

```bash
cd "$HOME/sophyane"
git pull --ff-only
python -m pip install --upgrade .
python -m pytest
sophyane --doctor
```

## Deterministic autonomous coding architecture

The LLM does not own the shell, compiler, package manager, or build system. It generates project files; the Sophyane runtime performs deterministic execution and verification.

```text
LLM
 ↓
emit project files
 ↓
runtime extracts files
 ↓
write workspace
 ↓
detect language and build system
 ↓
runtime installs or selects toolchain
 ↓
runtime builds and tests
 ↓
runtime collects diagnostics
 ↓
LLM repairs files
```

The runtime owns command construction and execution for tools such as CMake, Ninja, Cargo, GCC/Clang, npm, and pip.

## Key capabilities

- Deterministic file extraction from Markdown and JSON-like model responses
- Automatic language and build-system detection
- Runtime-owned builds and verification
- Diagnostic-driven repair loops
- Workspace completeness checks before invoking build tools
- Local GGUF and Ollama support
- Frontier-provider fallback chains
- Persistent local memory
- Repository-aware file tools
- CLI and browser interfaces
- Mobile, Chromebook, desktop, cloud, and edge deployment profiles

## First run and provider selection

Run the setup wizard:

```bash
sophyane --setup
```

Inspect the active edition and provider:

```bash
sophyane --status
sophyane --providers
sophyane --doctor
```

Typical identity:

```text
Sophyane Local:    provider local_gguf or ollama
Sophyane Frontier: provider gemini, openai, anthropic, xai, groq, openrouter, or deepseek
```

Provider configuration is stored under the user's private Sophyane configuration directory. API keys are not committed to this repository.

## Interactive CLI

```bash
sophyane
```

Useful commands:

| Command | Action |
|---|---|
| `/help` | Show the command palette |
| `/status` | Show provider, model, and fallback state |
| `/model [name]` | Inspect or switch models |
| `/local` | Install or activate a hardware-fit local model |
| `/doctor` | Run diagnostics |
| `/repo` | Inspect repository context |
| `/files` | List relevant files |
| `/new` | Start a clean session |
| `/quit` | Exit |

## Browser interface

Start the local browser interface:

```bash
sophyane-web
```

Default address:

```text
http://127.0.0.1:8765
```

For access from another trusted device on the same network:

```bash
sophyane-web --host 0.0.0.0
```

Do not expose the built-in web server directly to the public internet without an authenticated reverse proxy or trusted VPN.

## Platform roles

| Platform | Recommended edition | Notes |
|---|---|---|
| Android Termux phone | Sophyane Local | Primary local-model and constrained-device maintenance environment |
| Chromebook Linux/Penguin | Sophyane Frontier | Primary frontier-provider, testing, documentation, and GitHub environment |
| Linux/macOS/Windows | Either | Choose local or hosted providers based on hardware and privacy requirements |
| iPhone/iPad | Browser client | Connect Safari to a Sophyane host |

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

## Updating

Installer-based installation:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

Repository checkout:

```bash
git pull --ff-only
python -m pip install --upgrade .
```

## Privacy and safety

- API keys are stored outside the repository
- Local-model inference can remain entirely on-device
- User memory is stored locally
- Destructive shell commands are blocked
- The runtime, not the LLM, owns command execution
- The browser interface binds to localhost by default
- Provider and build failures are retained as diagnostics

## Documentation

- [Download and edition selection](DOWNLOAD.md)
- [Agent capabilities](docs/AGENT_CAPABILITIES.md)
- [Portability](docs/PORTABILITY.md)
- [Hardware and software API](docs/HARDWARE_SOFTWARE_API.md)
- [Browser and self-improvement](docs/BROWSER_AND_SELF_IMPROVE.md)
- [Community and contribution guide](COMMUNITY.md)

## License

MIT License. See [LICENSE](LICENSE).
