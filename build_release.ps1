param(
    [string]$Version = "0.5.1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root "venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
$releaseDir = Join-Path $root "build\release-v$Version"
$deliveryDir = Join-Path $root "build\delivery-v$Version"
$artifactDir = Join-Path $root "releases\v$Version"
$specDir = Join-Path $root "tools\specs"
$versionedExe = Join-Path $artifactDir "RingSpectrum_v${Version}.exe"
$versionedZip = Join-Path $artifactDir "RingSpectrum_v${Version}_Delivery.zip"
$compatZip = Join-Path $artifactDir "RingSpectrum_Delivery.zip"

Push-Location $root
try {
    New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
    New-Item -ItemType Directory -Path $specDir -Force | Out-Null

    & $python -m PyInstaller `
        --noconfirm `
        --onefile `
        --windowed `
        --name RingSpectrum `
        --distpath $releaseDir `
        --workpath build `
        --specpath $specDir `
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
