param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$HeldMarker,
    [Parameter(Mandatory=$true)][string]$ReleaseMarker,
    [int]$MaxSeconds = 120
)

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$guardPath = Join-Path $rootPath 'slink_gen3_trade.guard'
$logPath = Join-Path $rootPath 'slink_gen3_trade.log'
if (-not [IO.File]::Exists($guardPath) -or -not [IO.File]::Exists($logPath)) {
    throw "A sealed journal must exist before the probe takes its guard: $guardPath"
}
$heldPath = [IO.Path]::GetFullPath($HeldMarker)
$releasePath = [IO.Path]::GetFullPath($ReleaseMarker)
$deadline = [DateTime]::UtcNow.AddSeconds($MaxSeconds)
$stream = $null
while ($null -eq $stream -and [DateTime]::UtcNow -lt $deadline) {
    try {
        $stream = [IO.File]::Open($guardPath, [IO.FileMode]::Open,
                                  [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        if ($_.Exception.HResult -notin @(-2147024864, -2147024863)) { throw }
        [Threading.Thread]::Sleep(5)
    }
}
if ($null -eq $stream) { throw "Timed out acquiring the OS journal guard: $guardPath" }
try {
    $started = [DateTime]::UtcNow.ToString('o')
    $held = "LOCK_HELD pid=$PID guard=$guardPath started_utc=$started"
    [IO.File]::WriteAllText($heldPath, $held + [Environment]::NewLine)
    Write-Output $held
    while (-not [IO.File]::Exists($releasePath) -and [DateTime]::UtcNow -lt $deadline) {
        [Threading.Thread]::Sleep(10)
    }
    if (-not [IO.File]::Exists($releasePath)) { throw "Timed out waiting for release marker: $releasePath" }
} finally {
    $stream.Dispose()
    Write-Output "LOCK_RELEASED pid=$PID guard=$guardPath released_utc=$([DateTime]::UtcNow.ToString('o'))"
}
