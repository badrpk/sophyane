# Download Sophyane Harness 21.4.2

Sophyane Harness is the public four-mode launch experience for Sophyane:

1. **Deterministic**
2. **Internet**
3. **Local LLM**
4. **Cloud LLM**

The installer keeps Sophyane's existing replace-the-runtime / preserve-the-user upgrade contract. A new managed runtime is installed and validated before the old managed runtime is removed. User configuration, API keys, memory, databases, learned state, workspaces, generated projects, and other persistent data remain preserved outside the replaceable runtime directories.

## Linux, macOS, ChromeOS Linux, Android Termux, and UserLAnd

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
sophyane-harness
```

If `curl` is unavailable:

```bash
wget -qO- https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
sophyane-harness
```

## Windows 10 and 11

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
sophyane-harness
```

## Four explicit launch modes

```bash
sophyane-harness deterministic
sophyane-harness internet
sophyane-harness local-llm
sophyane-harness cloud-llm
```

Browser UI with the same policy:

```bash
sophyane-harness deterministic --web
sophyane-harness internet --web
sophyane-harness local-llm --web
sophyane-harness cloud-llm --web
```

### Deterministic

Runs Sophyane's deterministic execution/orchestration path without cloud rescue.

### Internet

Runs the SLI Graph + internet acquisition path without requiring a local or cloud LLM.

### Local LLM

Uses the configured llama.cpp / GGUF local model and disables cloud fallback for the session.

### Cloud LLM

Uses a configured cloud provider and model.

## Managed runtime

```text
~/.local/share/sophyane/system
~/.local/share/sophyane/venv
```

Persistent state remains under:

```text
~/.local/share/sophyane
```

Running the installer again is the supported upgrade path. By default, it resolves the newest stable semantic release tag and replaces only the managed runtime after successful validation.

## Install a specific ref

POSIX:

```bash
SOPHYANE_REF=v21.4.2 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh)"
```

PowerShell:

```powershell
$env:SOPHYANE_REF = "v21.4.2"
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

## Verify

```bash
sophyane --version
sophyane --doctor
sophyane-harness --help
python -m pip check
```

## Developer clone flow

```bash
git clone https://github.com/badrpk/sophyane.git
cd sophyane
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
sophyane-harness
```

## iPhone and iPad

Stock iOS does not run the local Python CLI directly. Install Sophyane Harness on a Windows, macOS, Linux, cloud, or Android Termux host and use its browser interface remotely.

Current stable package version: `21.4.2`

Source repository: https://github.com/badrpk/sophyane
