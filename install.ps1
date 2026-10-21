# Install / sync: copy this skill into <knowledge-base>/.agents/skills/
# Usage:
#   .\install.ps1                     # default target: ..\..\.agents\skills\gongkao-material-ingest
#   .\install.ps1 -Target "D:\path\to\skills\gongkao-material-ingest"
# Note: this file is ASCII-only on purpose, so Windows PowerShell 5.1 parses it safely.
param(
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Target)) {
    $Target = Join-Path $repo "..\..\.agents\skills\gongkao-material-ingest"
}
$Target = [System.IO.Path]::GetFullPath($Target)

if (-not (Test-Path (Join-Path $repo "SKILL.md"))) {
    throw "SKILL.md not found. Run this script from the repository root."
}

if (Test-Path $Target) {
    Get-ChildItem $Target -Force | Remove-Item -Recurse -Force
} else {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
}
New-Item -ItemType Directory -Path (Join-Path $Target "scripts") -Force | Out-Null

Copy-Item (Join-Path $repo "SKILL.md") $Target -Force
Copy-Item (Join-Path $repo "scripts\*.py") (Join-Path $Target "scripts") -Force

Write-Host "installed to: $Target"
Get-ChildItem $Target -Recurse -File | ForEach-Object { "  " + $_.FullName.Substring($Target.Length + 1) }
