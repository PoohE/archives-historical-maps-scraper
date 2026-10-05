# Universal detached launcher for long archive runs.
#
# Why: runs started from a Claude session die with it (all three runs stopped at 19:30 on
# 2026-10-04 when the session ended, and twice before that the OS killed them on low memory).
# Start-Process detaches the child, so it survives both.
#
# Paths are derived from $PSScriptRoot: the project path contains Cyrillic and spaces, and
# PowerShell reads .ps1 as ANSI, which corrupts literal Cyrillic paths.
#
# Usage:
#   powershell -NoProfile -File scripts_rosarchive\run_detached.ps1 -Task fund380
#   powershell -NoProfile -File scripts_rosarchive\run_detached.ps1 -Task uiad -Funds 846
param(
    [Parameter(Mandatory = $true)][ValidateSet('fund380', 'uiad', 'prlib')][string]$Task,
    [string]$Funds = ''
)

$root  = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'

if ($Task -eq 'fund380') {
    $outDir = Join-Path $root 'output\rgia_fund380_20261003_v3_1'
    $loop   = 'output/rgia_fund380_handoff_20261003_v3_1/run_loop.sh'
    $bash   = 'C:\Program Files\Git\bin\bash.exe'
    $log    = Join-Path $outDir "detached_$stamp.log"
    $err    = Join-Path $outDir "detached_$stamp.err"
    $p = Start-Process -FilePath $bash -ArgumentList $loop -WorkingDirectory $root `
        -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru
}
elseif ($Task -eq 'prlib') {
    $outDir = Join-Path $root 'output\prlib_catalog_full_20261004_v7_1'
    $loop   = 'output/prlib_catalog_full_handoff_20261004_v7_1/run_loop.sh'
    $bash   = 'C:\Program Files\Git\bin\bash.exe'
    $log    = Join-Path $outDir "detached_$stamp.log"
    $err    = Join-Path $outDir "detached_$stamp.err"
    $p = Start-Process -FilePath $bash -ArgumentList $loop -WorkingDirectory $root `
        -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru
}
else {
    if (-not $Funds) { throw 'uiad requires -Funds' }
    $outDir = Join-Path $root 'output\uiad_rgvia_maps_20261004'
    $script = Join-Path $PSScriptRoot 'collect_uiad_rgvia_maps.py'
    $log    = Join-Path $outDir "run_$stamp.log"
    $err    = Join-Path $outDir "run_$stamp.err"
    # the project path contains spaces: one quoted argument string, not an array
    $argString = '-B "{0}" --funds {1}' -f $script, $Funds
    $env:PYTHONUTF8 = '1'
    $p = Start-Process -FilePath 'python' -ArgumentList $argString -WorkingDirectory $root `
        -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru
}

"task $Task"
"PID  $($p.Id)"
"log  $log"
