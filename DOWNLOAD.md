# Download Sophyane 18

Sophyane is distributed from one open-source repository in two operating editions:

- **Sophyane Local** — local GGUF/Ollama models, designed for Android Termux and other private or offline devices.
- **Sophyane Frontier** — top hosted frontier LLMs, designed for ChromeOS Linux/Penguin, Linux, macOS, and Windows development machines.

Both editions share the same deterministic runtime, but they use separate installation and maintenance paths.

## Sophyane Local — Android Termux

Use this edition when inference should run on the phone through `llama-server`, GGUF, or Ollama. It does not require a cloud API key.

```bash
pkg update && pkg install -y curl git python
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/fix/local-llm-termux-reliability/install-local.sh | bash
sophyane
```

The first run shows the complete **supported Sophyane Local catalog**. For every selectable model it displays:

- Hugging Face source repository
- approximate GGUF download size
- minimum RAM requirement
- whether the model fits the detected phone
- whether it is recommended or already installed

After selection, Sophyane downloads the GGUF from Hugging Face, installs `llama.cpp` from GitHub releases, starts `llama-server` when possible, and configures `provider=local_gguf`. No API key is requested.

Local installation paths:

```text
CLI:     ~/.local/bin/sophyane-local
Alias:   ~/.local/bin/sophyane
Code:    ~/.local/share/sophyane-local/source
Models:  ~/.local/share/sophyane/models/gguf
Logs:    ${TMPDIR:-~/.cache/sophyane-local}/logs
```

Update Sophyane Local from Termux by rerunning the same installer:

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/fix/local-llm-termux-reliability/install-local.sh | bash
```

## Sophyane Frontier — Chromebook Penguin

Use this edition when Sophyane should call frontier providers such as Google Gemini, OpenAI, Anthropic Claude, xAI Grok, Groq, OpenRouter, or DeepSeek.

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
sophyane --setup
```

Set the desired provider credentials during setup or through environment variables. For example:

```bash
export GEMINI_API_KEY="your_key"
sophyane
```

Recommended ownership and update path:

```bash
# Run from the Linux/Penguin terminal on the Chromebook
cd "$HOME/sophyane"
git pull --ff-only
python -m pip install --upgrade .
python -m pytest
sophyane --doctor
```

The Chromebook/Penguin checkout is the primary environment for frontier-provider development and GitHub updates.

## Other supported platforms

### Linux, macOS, ChromeOS Linux, and UserLAnd

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

### Windows 10 and 11

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

### iPhone and iPad

Stock iOS does not support the local Python CLI. Install Sophyane Local or Frontier on a supported host and open Sophyane's authenticated browser interface from Safari.

## Verify the active edition

```bash
sophyane --version
sophyane --status
sophyane --providers
sophyane --doctor
```

Typical provider identity:

```text
Sophyane Local:    provider local_gguf or ollama
Sophyane Frontier: provider gemini, openai, anthropic, xai, groq, openrouter, or deepseek
```

Source repository: https://github.com/badrpk/sophyane
