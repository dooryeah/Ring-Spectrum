param(
    [string]$Version = "0.4.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root "venv\Scripts\python.exe"
$releaseDir = Join-Path $root "build\release-v$Version"
$deliveryDir = Join-Path $root "build\delivery-v$Version"
$versionedExe = Join-Path $root "RingSpectrum_v${Version}.exe"
$versionedZip = Join-Path $root "RingSpectrum_v${Version}_Delivery.zip"
$compatZip = Join-Path $root "RingSpectrum_Delivery.zip"

if (-not (Test-Path $python)) {
    throw "Virtual environment Python not found: $python"
}

Push-Location $root
try {
    & $python -m PyInstaller `
        --noconfirm `
        --onefile `
        --windowed `
        --name RingSpectrum `
        --distpath $releaseDir `
        --workpath build `
        --specpath . `
        main.py

    $buildRoot = [IO.Path]::GetFullPath((Join-Path $root "build"))
    $resolvedDeliveryDir = [IO.Path]::GetFullPath($deliveryDir)
    if (-not $resolvedDeliveryDir.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a delivery directory outside the build folder: $resolvedDeliveryDir"
    }
    if (Test-Path $deliveryDir) {
        Remove-Item -LiteralPath $deliveryDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $deliveryDir | Out-Null

    Copy-Item -LiteralPath (Join-Path $releaseDir "RingSpectrum.exe") -Destination $deliveryDir
    Copy-Item -LiteralPath (Join-Path $root "config.json") -Destination $deliveryDir
    Copy-Item -LiteralPath (Join-Path $root "USER_GUIDE.txt") -Destination $deliveryDir
    Copy-Item -LiteralPath (Join-Path $root "CHANGELOG.txt") -Destination $deliveryDir

    Copy-Item -LiteralPath (Join-Path $releaseDir "RingSpectrum.exe") -Destination $versionedExe -Force
    Compress-Archive -Path (Join-Path $deliveryDir "*") -DestinationPath $versionedZip -Force
    Compress-Archive -Path (Join-Path $deliveryDir "*") -DestinationPath $compatZip -Force

    Write-Host "Standalone executable: $versionedExe"
    Write-Host "Release package: $versionedZip"
    Write-Host "Compatibility package: $compatZip"
}
finally {
    Pop-Location
}
