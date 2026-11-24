param([Parameter(Mandatory=$true)][ValidatePattern('^inputbuf[0-9]+$')][string]$RunName)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$run = Join-Path $root "build/qa/phase3b-watch/$RunName"
$ready = Join-Path $run 'scheduler.ready'
$etl = Join-Path $run 'scheduler.private.etl'
if (!(Test-Path -LiteralPath (Join-Path $run 'refill-image.private.json'))) { throw 'Prepare the diagnostic image first.' }
foreach ($file in @($ready, $etl, (Join-Path $run 'api-attribution-d-conditions.json'))) {
    if (Test-Path -LiteralPath $file) { throw 'Use a fresh attribution directory.' }
}
$wpr = Join-Path ([Environment]::GetFolderPath('System')) 'wpr.exe'
$profile = Join-Path $PSScriptRoot 'decoder-scheduler.wprp'
$instance = "VlogCraftDecoder-$RunName"
& $wpr -start "$profile!VlogCraftDecoder" -instancename $instance
if ($LASTEXITCODE -ne 0) { throw "Windows declined scheduler collection ($LASTEXITCODE)." }
try {
    [IO.File]::WriteAllText($ready, $instance)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 120 -and !(Test-Path -LiteralPath (Join-Path $run 'api-attribution-exit.json'))) {
        Start-Sleep -Milliseconds 500
    }
} finally {
    & $wpr -stop $etl -skipPdbGen -instancename $instance
    if ($LASTEXITCODE -ne 0) {
        & $wpr -cancel -instancename $instance
        throw 'Saving the owned scheduler trace failed.'
    }
}
