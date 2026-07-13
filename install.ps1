$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/badrpk/sophyane.git"
$InstallDir = if ($env:SOPHYANE_HOME) { $env:SOPHYANE_HOME } else { Join-Path $env:LOCALAPPDATA "Sophyane" }
$BinDir = Join-Path $InstallDir "bin"

Write-Host "Sophyane Windows installer" -ForegroundColor Cyan
Write-Host "Install directory: $InstallDir"

function Find-Python {
    foreach ($candidate in @("py", "python", "python3")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) { return $candidate }
    }
    throw "Python 3.10+ was not found. Install Python from python.org and enable 'Add Python to PATH'."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found. Install Git for Windows, then rerun this script."
}

$Python = Find-Python
if ($Python -eq "py") {
    $PythonArgs = @("-3")
} else {
    $PythonArgs = @()
}

& $Python @PythonArgs -c "import sys; assert sys.version_info >= (3,10), 'Sophyane requires Python 3.10+'; print('Python', sys.version.split()[0], 'detected')"

if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Host "Updating existing installation..."
    git -C $InstallDir pull --ff-only
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
    git clone $RepoUrl $InstallDir
}

$VenvDir = Join-Path $InstallDir ".venv"
if (-not (Test-Path $VenvDir)) {
    & $Python @PythonArgs -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install --upgrade $InstallDir

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

@"
@echo off
"$VenvDir\Scripts\sophyane.exe" %*
"@ | Set-Content -Encoding Ascii (Join-Path $BinDir "sophyane.cmd")

@"
@echo off
"$VenvDir\Scripts\sophyane-web.exe" %*
"@ | Set-Content -Encoding Ascii (Join-Path $BinDir "sophyane-web.cmd")

@"
@echo off
"$VenvDir\Scripts\sophyane-doctor.exe" %*
"@ | Set-Content -Encoding Ascii (Join-Path $BinDir "sophyane-doctor.cmd")

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ";") -notcontains $BinDir) {
    $NewPath = if ($UserPath) { "$UserPath;$BinDir" } else { $BinDir }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    $env:Path = "$env:Path;$BinDir"
    Write-Host "Added $BinDir to your user PATH."
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host "Open a new terminal, then run: sophyane"
Write-Host "Browser interface: sophyane-web"
Write-Host "Diagnostics: sophyane-doctor"
