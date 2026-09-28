# Copy only the maintained drawing workflow into the WSL project directory.
$ErrorActionPreference = 'Stop'
$destination = '\\wsl.localhost\Ubuntu\home\chenrui\playground'
$files = @('AGENTS.md', 'README.md', 'environment.yml', 'requirements-sdk.txt', 'calibrate_paper.py', 'read_piper_status.py', 'execute_plan.py', 'prepare_centerline_plan.py')

if (-not (Test-Path -LiteralPath $destination)) {
    throw "Ubuntu WSL is not running or $destination does not exist. Start Ubuntu once, then retry."
}
foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $destination $file) -Force
}
$trazorDestination = Join-Path $destination 'vendor\trazor\piper_centerline_runner.ts'
if (-not (Test-Path -LiteralPath (Split-Path -Parent $trazorDestination))) {
    throw 'Trazor is not installed in WSL. Follow README.md first.'
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'trazor_centerline_runner.ts') -Destination $trazorDestination -Force
Write-Host "Synced maintained Piper drawing files to $destination"
