# Install the Windows-only drawing toolchain. This script never opens CAN.
param(
    [string]$CondaRoot = 'D:\Miniconda3'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$conda = Join-Path $CondaRoot 'Scripts\conda.exe'
$python = Join-Path $CondaRoot 'envs\piper\python.exe'
$node = Join-Path $CondaRoot 'envs\piper\node.exe'
$npm = Join-Path $CondaRoot 'envs\piper\npm.cmd'
$trazor = Join-Path $repo 'vendor\trazor'
$trazorCommit = 'd5dd561830defbff379a5fba18990cf7efc0267d'

if (-not (Test-Path -LiteralPath $conda)) { throw "Conda not found: $conda" }
if (-not (Test-Path -LiteralPath $python)) {
    & $conda create -y -n piper -c conda-forge --override-channels python=3.12 nodejs=24
    if ($LASTEXITCODE -ne 0) { throw 'Conda environment creation failed' }
}
if (-not (Test-Path -LiteralPath $node)) {
    & $conda install -y -n piper -c conda-forge --override-channels nodejs=24
    if ($LASTEXITCODE -ne 0) { throw 'Conda Node.js install failed' }
}
& $python -m pip install -r (Join-Path $repo 'requirements-sdk.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency install failed' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed' }

if (-not (Test-Path -LiteralPath $npm)) { throw "npm not found: $npm" }
if (-not (Test-Path -LiteralPath $trazor)) {
    New-Item -ItemType Directory -Path (Join-Path $repo 'vendor') -Force | Out-Null
    git clone https://github.com/PhenX/Trazor.git $trazor
    if ($LASTEXITCODE -ne 0) { throw 'Trazor clone failed' }
    git -C $trazor checkout $trazorCommit
    if ($LASTEXITCODE -ne 0) { throw 'Trazor checkout failed' }
}
$actualCommit = (git -C $trazor rev-parse HEAD).Trim()
if ($actualCommit -ne $trazorCommit) {
    throw "Trazor is at $actualCommit, expected $trazorCommit. Resolve manually; no files were reset."
}
Push-Location $trazor
try {
    & $npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Trazor npm ci failed' }
} finally {
    Pop-Location
}
Copy-Item -LiteralPath (Join-Path $repo 'trazor_centerline_runner.ts') -Destination (Join-Path $trazor 'piper_centerline_runner.ts') -Force
Write-Host "Windows piper ready: $python"
Write-Host "Trazor ready: $trazor"
Write-Host 'Paper calibration was not modified.'
