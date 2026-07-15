# Sophyane Browser — Windows installer from GitHub
$ErrorActionPreference = "Stop"
Write-Host "=== Sophyane Browser (GitHub) ==="
Write-Host "Repo: https://github.com/badrpk/sophyane"
irm https://raw.githubusercontent.com/badrpk/sophyane/main/install.ps1 | iex
$bin = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$wrap = Join-Path $bin "sophyane-browser.cmd"
@"
@echo off
sophyane --browser %*
"@ | Set-Content -Path $wrap -Encoding ASCII
Write-Host "Installed. Run: sophyane-browser   or   sophyane --browser"
Write-Host "New-tab mode: set SOPHYANE_BROWSER_MODE=tab"
Write-Host "Releases: https://github.com/badrpk/sophyane/releases"
