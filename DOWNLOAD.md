# Download Sophyane 18

This is the single download page for every supported device. Sophyane uses an
isolated Python environment and keeps configuration, API keys, memory, and user
workspaces outside the installed release source.

## Linux, macOS, ChromeOS Linux, Android Termux, and UserLAnd

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

If `curl` is unavailable:

```bash
wget -qO- https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
```

## Windows 10 and 11

Open PowerShell and run:

```powershell
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
```

Rerun the installer for your platform to upgrade to the current stable release.

Source repository: https://github.com/badrpk/sophyane
