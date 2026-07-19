# Download Sophyane 18

Sophyane is distributed from one open-source repository in two operating editions:

- **Sophyane Local** — local GGUF/Ollama models, designed for Android Termux and other private or offline devices.
- **Sophyane Frontier** — top hosted frontier LLMs, designed for ChromeOS Linux/Penguin, Linux, macOS, and Windows development machines.

Both editions use the same Sophyane runtime and installer. The selected provider configuration determines which edition is active.

## Sophyane Local — Android Termux

Use this edition when inference should run on your phone through `llama-server`, GGUF, or Ollama.

```bash
pkg update && pkg install curl
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
sophyane /local
```

Inside the interactive CLI, you can also run:

```text
/local
```

Recommended ownership and update path:

```bash
# Run from Termux on the Android phone
cd "$HOME/sophyane"
git pull --ff-only
python -m pip install --upgrade .
sophyane --doctor
```

Local configuration, models, memory, and workspaces remain on the device. Long local inference requests display progress heartbeats, and constrained GGUF generation is bounded to avoid apparent hangs.

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

If `curl` is unavailable:

```bash
wget -qO- https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
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

Rerun the installer or update the repository checkout to upgrade to the current stable release.

Source repository: https://github.com/badrpk/sophyane
