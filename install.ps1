# install.ps1 — install or update claude-code-usage on Windows
# Usage:
#   .\install.ps1              install latest release
#   .\install.ps1 -Update      update to latest release
#   .\install.ps1 -Uninstall   remove everything
#
# Run with:  powershell -ExecutionPolicy Bypass -File install.ps1
[CmdletBinding()]
param(
    [switch]$Update,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"

$Repo       = "michaelpeeters/claude-code-usage"
$InstallDir = Join-Path $env:LOCALAPPDATA "claude-usage"
$ExePath    = Join-Path $InstallDir "claude-usage.exe"
$VersionFile= Join-Path $InstallDir ".version"
$ShortcutDst= Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Claude Usage.lnk"

function Write-Green($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Bold($msg)  { Write-Host $msg -ForegroundColor White }
function Write-Red($msg)   { Write-Host $msg -ForegroundColor Red }

# ── uninstall ──────────────────────────────────────────────────────────────

if ($Uninstall) {
    Write-Bold "Uninstalling claude-code-usage..."
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    if (Test-Path $ShortcutDst) { Remove-Item $ShortcutDst -Force }
    Write-Green "Done."
    exit 0
}

# ── fetch latest release ───────────────────────────────────────────────────

Write-Bold "Fetching latest release from github.com/$Repo..."

try {
    $Release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
} catch {
    Write-Red "Failed to reach GitHub API: $_"
    exit 1
}

$LatestTag = $Release.tag_name
if (-not $LatestTag) { Write-Red "No release found."; exit 1 }

$CurrentTag = ""
if (Test-Path $VersionFile) { $CurrentTag = Get-Content $VersionFile -Raw | ForEach-Object { $_.Trim() } }

if ($Update -and $CurrentTag -eq $LatestTag) {
    Write-Green "Already up to date ($LatestTag)."
    exit 0
}

Write-Host "  Latest release : $LatestTag"
if ($CurrentTag) { Write-Host "  Installed       : $CurrentTag" }

# ── find exe asset ────────────────────────────────────────────────────────

$Asset = $Release.assets | Where-Object { $_.name -match "claude-usage.*\.exe" } | Select-Object -First 1
if (-not $Asset) { Write-Red "No .exe found in release $LatestTag."; exit 1 }

# ── download ───────────────────────────────────────────────────────────────

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$TmpFile = Join-Path $env:TEMP "claude-usage-$LatestTag.exe"

Write-Bold "Downloading $($Asset.browser_download_url)..."
Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $TmpFile -UseBasicParsing

Move-Item -Force $TmpFile $ExePath

# ── Start Menu shortcut ────────────────────────────────────────────────────

$ShortcutDir = Split-Path $ShortcutDst
New-Item -ItemType Directory -Force -Path $ShortcutDir | Out-Null

$Shell    = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutDst)
$Shortcut.TargetPath       = $ExePath
$Shortcut.Description      = "Claude Usage — token monitor (unofficial, not by Anthropic)"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Save()

# ── record version ─────────────────────────────────────────────────────────

$LatestTag | Out-File -FilePath $VersionFile -Encoding UTF8 -NoNewline

# ── done ───────────────────────────────────────────────────────────────────

Write-Green "`nInstalled $LatestTag!"
Write-Host "  Run    : $ExePath"
Write-Host "  Menu   : Start → Claude Usage"
Write-Host "  Update : .\install.ps1 -Update"
Write-Host "  Remove : .\install.ps1 -Uninstall`n"
