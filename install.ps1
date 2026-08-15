$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/badrpk/sophyane.git"
$RawUrl = "https://raw.githubusercontent.com/badrpk/sophyane/main"
$Base = if ($env:SOPHYANE_HOME) { $env:SOPHYANE_HOME } else { Join-Path $env:LOCALAPPDATA "Sophyane" }
$SystemDir = Join-Path $Base "system"
$VenvDir = Join-Path $Base "venv"
$BinDir = Join-Path $Base "bin"
$UserWork = Join-Path $Base "user-work"
$ManagedLaunchers = Join-Path $Base "managed-launchers.txt"
$LogDir = Join-Path $Base "install-logs"
$LockDir = Join-Path $Base ".install-lock"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sophyane-install-" + [guid]::NewGuid().ToString("N"))
$SourceDir = Join-Path $TempRoot "source"
$SnapshotZip = Join-Path $TempRoot "release.zip"
$OldSystem = Join-Path $Base (".old-system-" + $PID)
$OldVenv = Join-Path $Base (".old-venv-" + $PID)
$Swapped = $false
$Locked = $false
$CurrentStep = "startup"

Write-Host "=== Sophyane universal Windows installer/updater ===" -ForegroundColor Cyan
Write-Host "State root: $Base"

function Write-Step([string]$Name) {
    $script:CurrentStep = $Name
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
}

function Find-Python {
    foreach ($candidate in @("python", "python3", "py")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            if ($candidate -eq "py") { return "py" }
            return $command.Source
        }
    }
    throw "Python 3.10+ was not found. Install Python 3.10 or newer and rerun the installer."
}

function Invoke-Python([string]$Python, [string[]]$Args) {
    if ($Python -eq "py") { & $Python -3 @Args } else { & $Python @Args }
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE." }
}

function Invoke-LoggedNative([string]$Label, [scriptblock]$Command) {
    Write-Step $Label
    & $Command 2>&1 | Tee-Object -FilePath $script:InstallLog -Append
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Retry([string]$Label, [scriptblock]$Command, [int]$Attempts = 3) {
    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        & $Command
        if ($LASTEXITCODE -eq 0) { return }
        if ($Attempt -eq $Attempts) {
            throw "$Label failed after $Attempts attempts (exit $LASTEXITCODE)."
        }
        Write-Warning "$Label attempt $Attempt/$Attempts failed; retrying..."
        Start-Sleep -Seconds 2
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git was not found." }
$Python = Find-Python

New-Item -ItemType Directory -Force -Path $Base, $BinDir, $UserWork, $LogDir | Out-Null
if (Test-Path $LockDir) {
    throw "Another Sophyane installer appears to be running ($LockDir exists)."
}
New-Item -ItemType Directory -Path $LockDir | Out-Null
$Locked = $true

$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$InstallLog = Join-Path $LogDir ("install-" + $Stamp + ".log")
New-Item -ItemType File -Force -Path $InstallLog | Out-Null
Write-Host "Install log: $InstallLog"

try {
    Write-Step "Checking Python"
    Invoke-Python $Python @("-c", "import sys; assert sys.version_info >= (3,10), f'Sophyane requires Python 3.10+; found {sys.version.split()[0]}'; print('Python', sys.version.split()[0])")

    $LegacyGit = Join-Path $Base ".git"
    if (Test-Path $LegacyGit) {
        Write-Step "Preserving legacy source changes"
        $LegacyStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
        $LegacyBackup = Join-Path $UserWork ("legacy-source-" + $LegacyStamp)
        New-Item -ItemType Directory -Force -Path $LegacyBackup | Out-Null
        git -C $Base diff --binary | Set-Content -Encoding UTF8 (Join-Path $LegacyBackup "working-tree.patch")
        git -C $Base diff --cached --binary | Set-Content -Encoding UTF8 (Join-Path $LegacyBackup "index.patch")
        git -C $Base rev-parse HEAD | Set-Content -Encoding ASCII (Join-Path $LegacyBackup "original-commit")

        $UntrackedRoot = Join-Path $LegacyBackup "untracked"
        New-Item -ItemType Directory -Force -Path $UntrackedRoot | Out-Null
        foreach ($Rel in (git -C $Base ls-files --others --exclude-standard)) {
            if (-not $Rel) { continue }
            $Src = Join-Path $Base $Rel
            $Dst = Join-Path $UntrackedRoot $Rel
            if (Test-Path $Src) {
                New-Item -ItemType Directory -Force -Path (Split-Path $Dst) | Out-Null
                Copy-Item -Recurse -Force $Src $Dst
            }
        }

        foreach ($Rel in (git -C $Base ls-files)) {
            if ($Rel -like "system/*" -or $Rel -like "venv/*" -or $Rel -like "user-work/*") { continue }
            $Path = Join-Path $Base $Rel
            if (Test-Path $Path) { Remove-Item -Force $Path }
        }
        Remove-Item -Recurse -Force $LegacyGit
        $LegacyVenv = Join-Path $Base ".venv"
        if (Test-Path $LegacyVenv) { Remove-Item -Recurse -Force $LegacyVenv }
        Write-Host "Legacy source edits preserved at $LegacyBackup"
    }

    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    $InstallRef = $env:SOPHYANE_REF

    if (-not $InstallRef) {
        Write-Step "Resolving latest stable release"
        $RemoteLines = @()
        Invoke-Retry "Stable release lookup" { $script:RemoteLines = @(git ls-remote --tags --refs $RepoUrl "refs/tags/v*") }
        $Candidates = @()
        foreach ($Line in $RemoteLines) {
            if ($Line -match "refs/tags/v(\d+\.\d+\.\d+)$") {
                $Candidates += [pscustomobject]@{ Tag = "v$($Matches[1])"; Version = [version]$Matches[1] }
            }
        }
        if (-not $Candidates) { throw "No stable Sophyane release tags found." }
        $InstallRef = ($Candidates | Sort-Object Version -Descending | Select-Object -First 1).Tag
    }

    Write-Host "Installing Sophyane ref: $InstallRef"
    Write-Step "Downloading release source"
    Invoke-Retry "Git clone" { git clone --depth 1 --single-branch --branch $InstallRef $RepoUrl $SourceDir }

    $Commit = (git -C $SourceDir rev-parse HEAD).Trim()
    $Pyproject = Get-Content -Raw (Join-Path $SourceDir "pyproject.toml")
    $VersionMatch = [regex]::Match($Pyproject, '(?m)^version\s*=\s*"([^"]+)"')
    $Version = if ($VersionMatch.Success) { $VersionMatch.Groups[1].Value } else { "unknown" }
    Write-Host "Resolved version: $Version"
    Write-Host "Resolved commit: $Commit"

    Write-Step "Preparing transactional upgrade"
    if (Test-Path $OldSystem) { Remove-Item -Recurse -Force $OldSystem }
    if (Test-Path $OldVenv) { Remove-Item -Recurse -Force $OldVenv }
    if (Test-Path $SystemDir) { Move-Item $SystemDir $OldSystem }
    if (Test-Path $VenvDir) { Move-Item $VenvDir $OldVenv }
    $Swapped = $true

    & git -C $SourceDir archive --format=zip --output=$SnapshotZip HEAD
    if ($LASTEXITCODE -ne 0) { throw "Failed to create release snapshot." }
    New-Item -ItemType Directory -Force -Path $SystemDir | Out-Null
    Expand-Archive -LiteralPath $SnapshotZip -DestinationPath $SystemDir -Force

    Write-Step "Creating isolated Python environment"
    Invoke-Python $Python @("-m", "venv", $VenvDir)
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Virtual environment creation did not produce $VenvPython."
    }
    & $VenvPython --version
    if ($LASTEXITCODE -ne 0) { throw "Managed virtual environment Python is not executable." }

    $env:PYTHONNOUSERSITE = "1"
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    if (-not $env:PIP_DEFAULT_TIMEOUT) { $env:PIP_DEFAULT_TIMEOUT = "120" }

    Invoke-LoggedNative "Updating Python packaging tools" {
        & $VenvPython -m pip install --disable-pip-version-check --no-cache-dir --retries 3 --upgrade pip setuptools wheel
    }
    Invoke-LoggedNative "Installing Sophyane and runtime dependencies" {
        & $VenvPython -m pip install --disable-pip-version-check --no-cache-dir --retries 3 --force-reinstall $SystemDir
    }
    Invoke-LoggedNative "Checking Python dependency integrity" {
        & $VenvPython -m pip check
    }

    Write-Step "Checking required runtime imports"
    & $VenvPython -c "import numpy, pexpect, sophyane; print('numpy =', numpy.__version__); print('pexpect =', pexpect.__version__); print('sophyane =', sophyane.__file__)"
    if ($LASTEXITCODE -ne 0) { throw "Required Sophyane runtime imports failed." }

    $Launchers = @(
        "sophyane", "sophyane-web", "sophyane-doctor", "sophyane-browser",
        "sophyane-sli", "sophyane-sli-train", "sophyane-sli-migrate", "sophyane-vela",
        "sophyane-platform", "sophyane-memory", "sophyane-task", "sophyane-execute",
        "sophyane-coi", "sophyane-release", "sophyane-audit", "sophyane-benchmark",
        "sophyane-mcp", "sophyane-mission"
    )

    Write-Step "Installing command launchers"
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

    Write-Step "Validating Sophyane commands"
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
INSTALL_LOG=$InstallLog
"@ | Set-Content -Encoding UTF8 (Join-Path $Base "install-info")

    Write-Step "Finalizing upgrade"
    $Swapped = $false
    if (Test-Path $OldSystem) { Remove-Item -Recurse -Force $OldSystem }
    if (Test-Path $OldVenv) { Remove-Item -Recurse -Force $OldVenv }

    Write-Host ""
    Write-Host "Sophyane $Version is installed and current." -ForegroundColor Green
    Write-Host "Commit: $($Commit.Substring(0,12))"
    Write-Host "Previous managed version: removed after validation"
    Write-Host "User state/work preserved under: $Base"
    Write-Host "Install log: $InstallLog"
    Write-Host "Start: sophyane"
}
catch {
    Write-Host "Installation failed during: $CurrentStep" -ForegroundColor Red
    Write-Warning "Install log: $InstallLog"
    if ($Swapped) {
        Write-Warning "Restoring previous Sophyane managed runtime..."
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
    if ($Locked -and (Test-Path $LockDir)) { Remove-Item -Recurse -Force $LockDir }
}
