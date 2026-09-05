# Download Sophyane 27.0.1

This is the single download page for every supported device.

The universal installers use a **replace-the-runtime, preserve-the-user** upgrade
model:

- by default, the newest stable semantic release tag (`vX.Y.Z`) is resolved and
  downloaded into a fresh managed system;
- `SOPHYANE_REF` can explicitly select another branch, tag, or ref when needed;
- the previous managed Sophyane source/runtime and virtual environment are
  deleted only after the new installation validates successfully;
- configuration, API keys, memory, databases, learned state, user workspaces,
  generated projects, and other files outside the managed `system` and `venv`
  directories remain on the device;
- legacy root-clone installs are migrated safely: local source edits are saved
  as patches and untracked files are copied into `user-work` before tracked old
  source is retired;
- installer launchers are recreated so an older executable cannot shadow the
  newly installed release;
- the installed Python dependency graph is checked with `pip check`, and core
  runtime imports are validated before the new runtime is accepted.

Running the same command again is therefore the supported upgrade path. You do not need to uninstall Sophyane manually first.

## Linux, macOS, ChromeOS Linux, Android Termux, and UserLAnd

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

If `curl` is unavailable:

```bash
wget -qO- https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

Managed runtime:

```text
~/.local/share/sophyane/system
~/.local/share/sophyane/venv
```

Persistent Sophyane state remains under:

```text
~/.local/share/sophyane
```

The installer replaces only the managed runtime directories above; it does not
wipe the rest of the state root.

## Windows 10 and 11

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

The Windows installer follows the same stable-release selection,
managed-runtime replacement, dependency validation, and persistent-user-state
contract.

## Install a specific ref

To intentionally install a particular release or development ref, set
`SOPHYANE_REF` before running the installer.

POSIX example:

```bash
SOPHYANE_REF=v27.0.1 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh)"
```

PowerShell example:

```powershell
$env:SOPHYANE_REF = "v27.0.1"
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
```

## iPhone and iPad

Stock iOS does not support the local Python CLI. Install Sophyane on a Windows,
macOS, Linux, cloud, or Android Termux host and open its authenticated browser
interface from Safari.

## Verify or upgrade

```text
sophyane --version
sophyane --doctor
python -m pip check
```

Rerun the installer for your platform at any time. By default it installs the
newest stable `vX.Y.Z` release and removes the prior managed runtime only after
validation passes.

Current stable release: `v27.0.1`

Source repository: https://github.com/badrpk/sophyane
