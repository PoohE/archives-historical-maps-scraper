# Launch the UIAD collector as a DETACHED process.
#
# Why detached: background tasks of a Claude session are killed by the system when RAM runs
# low (the 2026-10-04 run died at 3040 records exactly this way). A separate process survives
# both that and the end of the session.
#
# Paths are derived from $PSScriptRoot on purpose: the project path contains Cyrillic, and
# PowerShell reads .ps1 files as ANSI, which corrupts literal Cyrillic paths.
#
# Usage:
#   powershell -NoProfile -File scripts_rosarchive\run_uiad_detached.ps1 -Funds "418,419,420"
param(
    [Parameter(Mandatory = $true)][string]$Funds,
    [int]$MaxPages = 0
)

$root   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'collect_uiad_rgvia_maps.py'
$outDir = Join-Path $root 'output\uiad_rgvia_maps_20261004'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$log   = Join-Path $outDir "run_$stamp.log"
$err   = Join-Path $outDir "run_$stamp.err"

# the project path contains spaces: pass one quoted argument string, not an array
$argString = '-B "{0}" --funds {1}' -f $script, $Funds
if ($MaxPages -gt 0) { $argString += " --max-pages $MaxPages" }

$env:PYTHONUTF8 = '1'
$p = Start-Process -FilePath 'python' -ArgumentList $argString -WorkingDirectory $root `
    -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru

"PID $($p.Id)"
"log $log"
