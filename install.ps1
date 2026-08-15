$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/badrpk/sophyane.git"
$RawUrl = "https://raw.githubusercontent.com/badrpk/sophyane/main"
$Base = if ($env:SOPHYANE_HOME) { $env:SOPHYANE_HOME } else { Join-Path $env:LOCALAPPDATA "Sophyane" }
$SystemDir = Join-Path $Base "system"
$VenvDir = Join-Path $Base "venv"
$BinDir = Join-Path $Base "bin"
$UserWork = Join-Path $Base "user-work"
$ManagedLaunchers = Join-Path $Base "managed-launchers.txt"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sophyane-install-" + [guid]::NewGuid().ToString("N"))
$SourceDir = Join-Path $TempRoot "source"
$OldSystem = Join-Path $Base (".old-system-" + $PID)
$OldVenv = Join-Path $Base (".old-venv-" + $PID)
$Swapped = $false

Write-Host "=== Sophyane universal Windows installer/updater ===" -ForegroundColor Cyan
Write-Host "State root: $Base"

function Find-Python {
    foreach ($candidate in @("py", "python", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
    }
    throw "Python 3.10+ was not found."
}

function Invoke-Python([string]$Python, [string[]]$Args) {
    if ($Python -eq "py") { & $Python -3 @Args } else { & $Python @Args }
    if ($LASTEXITCODE -ne 0) { throw "Python command failed." }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git was not found." }
$Python = Find-Python
Invoke-Python $Python @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.version.split()[0])")

New-Item -ItemType Directory -Force -Path $Base, $BinDir, $UserWork | Out-Null

# Migrate legacy Windows installs that cloned the Sophyane repository directly
# into the persistent state root. Preserve edits/untracked work, then retire the
# old tracked source so it cannot shadow the fresh managed installation.
$LegacyGit = Join-Path $Base ".git"
if (Test-Path $LegacyGit) {
    $Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $LegacyBackup = Join-Path $UserWork ("legacy-source-" + $Stamp)
    New-Item -ItemType Directory -Force -Path $LegacyBackup | Out-Null
    git -C $Base diff --binary | Set-Content -Encoding UTF8 (Join-Path $LegacyBackup "working-tree.patch")
    git -C $Base diff --cached --binary | Set-Content -Encoding UTF8 (Join-Path $LegacyBackup "index.patch")
    git -C $Base rev-parse HEAD | Set-Content -Encoding ASCII (Join-Path $LegacyBackup "original-commit")

    $UntrackedRoot = Join-Path $LegacyBackup "untracked"
    New-Item -ItemType Directory -Force -Path $UntrackedRoot | Out-Null
    $Untracked = git -C $Base ls-files --others --exclude-standard
    foreach ($Rel in $Untracked) {
        if (-not $Rel) { continue }
        $Src = Join-Path $Base $Rel
        $Dst = Join-Path $UntrackedRoot $Rel
        if (Test-Path $Src) {
            New-Item -ItemType Directory -Force -Path (Split-Path $Dst) | Out-Null
            Copy-Item -Recurse -Force $Src $Dst
        }
    }

    $Tracked = git -C $Base ls-files
    foreach ($Rel in $Tracked) {
        if ($Rel -like "system/*" -or $Rel -like "venv/*" -or $Rel -like "user-work/*") { continue }
        $Path = Join-Path $Base $Rel
        if (Test-Path $Path) { Remove-Item -Force $Path }
    }
    Remove-Item -Recurse -Force $LegacyGit
    $LegacyVenv = Join-Path $Base ".venv"
    if (Test-Path $LegacyVenv) { Remove-Item -Recurse -Force $LegacyVenv }
    Write-Host "Legacy source edits preserved at $LegacyBackup"
}

try {
    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null

    $InstallRef = $env:SOPHYANE_REF

    if (-not $InstallRef) {
        $Candidates = @()

        foreach ($Line in (git ls-remote --tags --refs $RepoUrl "refs/tags/v*")) {
            if ($Line -match "refs/tags/v(\d+\.\d+\.\d+)$") {
                $Candidates += [pscustomobject]@{
                    Tag = "v$($Matches[1])"
                    Version = [version]$Matches[1]
                }
            }
        }

        if (-not $Candidates) {
            throw "No stable Sophyane release tags found."
        }

        $InstallRef = (
            $Candidates |
            Sort-Object Version -Descending |
            Select-Object -First 1
        ).Tag
    }

    Write-Host "Installing Sophyane ref: $InstallRef"

    git clone --quiet --depth 1 --single-branch --branch $InstallRef $RepoUrl $SourceDir
    if ($LASTEXITCODE -ne 0) { throw "Git clone failed." }

    $Commit = (git -C $SourceDir rev-parse HEAD).Trim()
    $Pyproject = Get-Content -Raw (Join-Path $SourceDir "pyproject.toml")
    $VersionMatch = [regex]::Match($Pyproject, '(?m)^version\s*=\s*"([^"]+)"')
    $Version = if ($VersionMatch.Success) { $VersionMatch.Groups[1].Value } else { "unknown" }

    if (Test-Path $OldSystem) { Remove-Item -Recurse -Force $OldSystem }
    if (Test-Path $OldVenv) { Remove-Item -Recurse -Force $OldVenv }
    if (Test-Path $SystemDir) { Move-Item $SystemDir $OldSystem }
    if (Test-Path $VenvDir) { Move-Item $VenvDir $OldVenv }
    $Swapped = $true

    Copy-Item -Recurse -Force $SourceDir $SystemDir
    $SystemGit = Join-Path $SystemDir ".git"
    if (Test-Path $SystemGit) { Remove-Item -Recurse -Force $SystemGit }

    Invoke-Python $Python @("-m", "venv", $VenvDir)
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    & $VenvPython -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip setuptools wheel | Out-Null
    & $VenvPython -m pip install --disable-pip-version-check --no-cache-dir --force-reinstall $SystemDir | Out-Null

    & $VenvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency graph is broken."
    }

    & $VenvPython -c "import numpy, pexpect, sophyane; print('numpy =', numpy.__version__); print('pexpect =', pexpect.__version__); print('sophyane =', sophyane.__file__)"
    if ($LASTEXITCODE -ne 0) {
        throw "Required Sophyane runtime imports failed."
    }

    $Launchers = @(
        "sophyane", "sophyane-web", "sophyane-doctor", "sophyane-browser",
        "sophyane-sli", "sophyane-sli-train", "sophyane-sli-migrate", "sophyane-vela",
        "sophyane-platform", "sophyane-memory", "sophyane-task", "sophyane-execute",
        "sophyane-coi", "sophyane-release", "sophyane-audit", "sophyane-benchmark",
        "sophyane-mcp", "sophyane-mission"
    )

    if (Test-Path $ManagedLaunchers) {
        foreach ($Name in Get-Content $ManagedLaunchers) {
            if ($Name -match '^sophyane(?:-|$)') {
                $OldLauncher = Join-Path $BinDir ($Name + ".cmd")
                if (Test-Path $OldLauncher) { Remove-Item -Force $OldLauncher }
            }
        }
    }

    foreach ($Name in $Launchers) {
        $Exe = Join-Path $VenvDir ("Scripts\" + $Name + ".exe")
        if (-not (Test-Path $Exe)) { throw "$Name entry point was not installed" }
        $Wrapper = Join-Path $BinDir ($Name + ".cmd")
        "@echo off`r`n`"$Exe`" %*`r`n" | Set-Content -Encoding ASCII $Wrapper
    }
    $Launchers | Set-Content -Encoding ASCII $ManagedLaunchers

    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($UserPath -split ";") -notcontains $BinDir) {
        $NewPath = if ($UserPath) { "$UserPath;$BinDir" } else { $BinDir }
        [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
        $env:Path = "$env:Path;$BinDir"
    }

    & (Join-Path $BinDir "sophyane.cmd") --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Sophyane validation failed." }

    $Commit | Set-Content -Encoding ASCII (Join-Path $Base "installed-commit")
    $Version | Set-Content -Encoding ASCII (Join-Path $Base "installed-version")
    @"
VERSION=$Version
COMMIT=$Commit
SOURCE=$InstallRef
UPDATED_AT=$((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))
INSTALL_URL=$RawUrl/install.ps1
MANAGED_SYSTEM=$SystemDir
MANAGED_VENV=$VenvDir
USER_STATE_ROOT=$Base
"@ | Set-Content -Encoding UTF8 (Join-Path $Base "install-info")

    $Swapped = $false
    if (Test-Path $OldSystem) { Remove-Item -Recurse -Force $OldSystem }
    if (Test-Path $OldVenv) { Remove-Item -Recurse -Force $OldVenv }

    Write-Host ""
    Write-Host "Sophyane $Version is installed and current." -ForegroundColor Green
    Write-Host "Commit: $($Commit.Substring(0,12))"
    Write-Host "Previous managed version: removed after validation"
    Write-Host "User state/work preserved under: $Base"
    Write-Host "Start: sophyane"
}
catch {
    if ($Swapped) {
        if (Test-Path $SystemDir) { Remove-Item -Recurse -Force $SystemDir }
        if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
        if (Test-Path $OldSystem) { Move-Item $OldSystem $SystemDir }
        if (Test-Path $OldVenv) { Move-Item $OldVenv $VenvDir }
        Write-Warning "Previous Sophyane managed installation restored."
    }
    throw
}
finally {
    if (Test-Path $TempRoot) { Remove-Item -Recurse -Force $TempRoot }
}
