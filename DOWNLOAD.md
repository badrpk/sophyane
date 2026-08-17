# Download Sophyane Harness 21.4.2

Sophyane Harness is the public five-mode launch experience for Sophyane:

1. **Sophyane Auto**
2. **Internet**
3. **Local LLM**
4. **Cloud LLM**
5. **Sophyane Learning**

The universal installers use a **replace-the-runtime, preserve-the-user** upgrade contract. By default, the installer resolves the newest stable semantic release tag (`vX.Y.Z`) and installs it into a fresh managed runtime. `SOPHYANE_REF` can explicitly select another branch, tag, or ref when needed. The new runtime is validated with dependency checks including `pip check` before the previous managed runtime is removed. User configuration, API keys, memory, databases, learned state, workspaces, generated projects, and other persistent data remain preserved outside the replaceable runtime directories. Running the installer again is the supported upgrade path; you do not need to uninstall Sophyane manually first.

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

If `raw.githubusercontent.com` is temporarily unavailable, clone the repository and run the installer directly:

```bash
TMP="$(mktemp -d)"
git clone --depth 1 https://github.com/badrpk/sophyane.git "$TMP/sophyane"
bash "$TMP/sophyane/install.sh"
rm -rf "$TMP"
```

## Windows 10 and 11

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
sophyane-harness
```

## Five launch modes

```bash
sophyane-harness auto
sophyane-harness internet
sophyane-harness local-llm
sophyane-harness cloud-llm
sophyane-harness learning
```

Browser UI with the same session policy:

```bash
sophyane-harness auto --web
sophyane-harness internet --web
sophyane-harness local-llm --web
sophyane-harness cloud-llm --web
sophyane-harness learning --web
```

### Sophyane Auto

Uses Sophyane's adaptive capability selection and cooperative race/orchestration policy.

### Internet

Runs SLI Graph + memory + internet acquisition without requiring a local or cloud LLM.

### Local LLM

Uses the configured llama.cpp / GGUF local model and disables cloud fallback for the session.

### Cloud LLM

Uses a configured cloud provider and model.

### Sophyane Learning

Runs continuous SLI topic acquisition + embedding until stopped with Ctrl+C.

## Comprehensive optional developer/browser toolchain

Sophyane is Python-native, and Python remains the authoritative runtime. On systems where it is useful and supported, the installer can also prepare a modern JavaScript tooling layer for web/developer workflows:

```text
Node.js 22+
npm
Corepack
pnpm 11.7.0
```

This mirrors the convenience of modern agent-harness setup flows without installing another project's unrelated workspace dependency graph. Sophyane only treats JavaScript tooling as a supporting layer for its own web/developer workflows.

Set `SOPHYANE_INSTALL_JS_TOOLCHAIN=0` before installation to skip the optional JavaScript tooling layer.

## Managed runtime

```text
~/.local/share/sophyane/system
~/.local/share/sophyane/venv
```

Persistent state remains under:

```text
~/.local/share/sophyane
```

Running the installer again is the supported upgrade path. By default, it resolves the newest stable semantic release tag (`vX.Y.Z`) and replaces only the managed runtime after successful validation.

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
node -v        # when optional Node toolchain is installed
pnpm --version # when optional pnpm toolchain is installed
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

Current stable release: `v21.4.2`
Current stable package version: `21.4.2`

Source repository: https://github.com/badrpk/sophyane
