param(
  [string]$Name = "EQ_Resist_Overlay",
  [string]$OutDir = "release"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$version = "0.0.0"
try {
  $appCfgPath = Join-Path $root "app_config.json"
  if (Test-Path $appCfgPath) {
    $appCfg = Get-Content -Raw -Path $appCfgPath | ConvertFrom-Json
    if ($appCfg -and $appCfg.version) {
      $version = [string]$appCfg.version
    }
  }
} catch {
  $version = "0.0.0"
}

$dist = Join-Path $root "dist"
$build = Join-Path $root "build"
$stagingRoot = Join-Path $root $OutDir
$stamp = Get-Date -Format "yyyyMMdd"
$zipPath = Join-Path $stagingRoot ("{0}_v{1}_{2}.zip" -f $Name, $version, $stamp)
$stage = Join-Path $stagingRoot $Name

Write-Host "Installing/ensuring PyInstaller is available..."
python -m pip install pyinstaller --quiet --upgrade

Write-Host "Building executable..."
python -m PyInstaller `
  --onefile `
  --windowed `
  --name $Name `
  --icon=NONE `
  --add-data "npc_types.sql;." `
  --distpath "$dist" `
  --workpath "$build" `
  --specpath "$root" `
  --clean `
  eq_resist_overlay.py

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$exe = Join-Path $dist ("{0}.exe" -f $Name)
if (-not (Test-Path $exe)) {
  throw "Build did not produce expected EXE: $exe"
}

Write-Host "Building packaged npc_data.db..."
python .\load_db.py --sql .\npc_types.sql --out (Join-Path $dist "npc_data.db")

if ($LASTEXITCODE -ne 0) {
  throw "load_db.py failed with exit code $LASTEXITCODE"
}

New-Item -ItemType Directory -Force -Path $stage | Out-Null

Copy-Item -Force $exe $stage

$db = Join-Path $dist "npc_data.db"
if (Test-Path $db) { Copy-Item -Force $db $stage }

# Include external SQL next to the EXE as a fallback + for easy rebuilds.
Copy-Item -Force .\npc_types.sql $stage

# Optional docs
if (Test-Path .\README.md) { Copy-Item -Force .\README.md $stage }

New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

Write-Host "Creating release zip..."
Compress-Archive -Force -Path (Join-Path $stage '*') -DestinationPath $zipPath

Write-Host "Release created: $zipPath"
