# Reattach the candleLight USB-CAN adapter to Ubuntu WSL and enable can0.
# Run this from an elevated PowerShell window when the device is Not shared.

$ErrorActionPreference = 'Stop'
$usbipd = 'C:\Program Files\usbipd-win\usbipd.exe'

if (-not (Test-Path -LiteralPath $usbipd)) {
    throw "usbipd-win is not installed. Install it first: winget install dorssel.usbipd-win"
}

$device = & $usbipd list | Select-String -Pattern 'candleLight USB to CAN adapter' | Select-Object -First 1
if (-not $device) {
    throw 'candleLight USB-CAN adapter was not found. Check its USB connection, then run usbipd list.'
}

$busId = ($device.Line -split '\s+')[0]
Write-Host "Found candleLight USB-CAN at BUSID $busId"

# Binding is persistent. It can require an elevated PowerShell window the first time.
if ($device.Line -match 'Not shared') {
    Write-Host "Sharing $busId with usbipd..."
    & $usbipd bind --busid $busId
}

Write-Host 'Keeping Ubuntu WSL running so the USB-CAN attachment persists...'
Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', 'Ubuntu', '--', 'bash', '-lc', 'while true; do sleep 3600; done') -WindowStyle Hidden
Start-Sleep -Seconds 1

Write-Host "Attaching $busId to Ubuntu WSL with auto-reconnect..."
# `usbipd attach --auto-attach` remains running as a monitor.  It must be a
# background process; otherwise this script never reaches CAN setup.
Start-Process -FilePath $usbipd -ArgumentList @(
    'attach', '--wsl', 'Ubuntu', '--busid', $busId, '--auto-attach'
) -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds(15)
do {
    Start-Sleep -Milliseconds 500
    wsl -d Ubuntu -- bash -lc 'test -e /sys/class/net/can0'
    $canPresent = $LASTEXITCODE -eq 0
} while (-not $canPresent -and (Get-Date) -lt $deadline)

if (-not $canPresent) {
    throw 'USB-CAN was not attached to WSL within 15 seconds. Reconnect the adapter and rerun this launcher.'
}

Write-Host 'Enabling can0 at 1 Mbps...'
# Use WSL root directly so this launcher never needs to receive or store the
# Ubuntu password.  Bringing the interface down first makes recovery idempotent.
wsl -d Ubuntu -u root -- bash -lc 'ip link set can0 down 2>/dev/null || true; ip link set can0 up type can bitrate 1000000; ip -details link show can0'

Write-Host ''
Write-Host 'Ready. Optional read-only verification:'
Write-Host 'wsl -d Ubuntu -- bash -lc "source ~/miniconda3/etc/profile.d/conda.sh && conda activate piper && python ~/playground/read_piper_status.py"'
