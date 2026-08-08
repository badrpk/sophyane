# Download Sophyane 21.1.2

This is the single download page for every supported device.

The universal installers use a **replace-the-runtime, preserve-the-user** upgrade
model:

- the current GitHub `main` branch is downloaded into a fresh managed system;
- the previous managed Sophyane source/runtime and virtual environment are
  deleted only after the new installation validates successfully;
- configuration, API keys, memory, databases, learned state, user workspaces,
  generated projects, and other files outside the managed `system` and `venv`
  directories remain on the device;
- legacy root-clone installs are migrated safely: local source edits are saved
  as patches and untracked files are copied into `user-work` before tracked old
  source is retired;
- installer launchers are recreated so an older executable cannot shadow the
  newly installed release.

Running the same command again is therefore the supported upgrade path. You do
not need to uninstall Sophyane manually first.

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

The Windows installer follows the same managed-runtime replacement and
persistent-user-state contract.

## iPhone and iPad

Stock iOS does not support the local Python CLI. Install Sophyane on a Windows,
macOS, Linux, cloud, or Android Termux host and open its authenticated browser
interface from Safari.

## Verify or upgrade

```text
sophyane --version
sophyane --doctor
```

Rerun the installer for your platform at any time. It always installs the
current GitHub `main` revision and removes the prior managed runtime only after
validation passes.

Source repository: https://github.com/badrpk/sophyane
