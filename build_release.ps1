param(
  [string]$OutDir = "release"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$productName = "Quarm NPC Overlay"
$exeBase = "Quarm_NPC_Overlay"
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
  $productName = "Quarm NPC Overlay"
  $version = "0.0.0"
}

$dist = Join-Path $root "dist"
$build = Join-Path $root "build"
$stagingRoot = Join-Path $root $OutDir
$stamp = Get-Date -Format "yyyyMMdd"
$zipPath = Join-Path $stagingRoot ("{0}_v{1}_{2}.zip" -f $exeBase, $version, $stamp)
$stage = Join-Path $stagingRoot $exeBase

Write-Host "Installing/ensuring PyInstaller is available..."
python -m pip install pyinstaller --quiet --upgrade

Write-Host "Building executable..."
python -m PyInstaller `
  --onefile `
  --windowed `
  --name $exeBase `
  --icon=NONE `
  --distpath "$dist" `
  --workpath "$build" `
  --specpath "$root" `
  --clean `
  quarm_npc_overlay.py

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$exe = Join-Path $dist ("{0}.exe" -f $exeBase)
if (-not (Test-Path $exe)) {
  throw "Build did not produce expected EXE: $exe"
}

Write-Host "Building packaged npc_data.db..."
$sqlToUse = $null
try {
  $explicit = Join-Path $root "quarm.sql"
  if (Test-Path $explicit) {
    $sqlToUse = $explicit
  } else {
    $candidate = Get-ChildItem -Path $root -Filter "quarm*.sql" -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($candidate) { $sqlToUse = $candidate.FullName }
  }
} catch {
  $sqlToUse = $null
}

if (-not $sqlToUse) {
  throw "No quarm.sql / quarm*.sql found. Provide a full Quarm SQL dump to build npc_data.db for the release."
}

python .\load_db.py --sql $sqlToUse --out (Join-Path $dist "npc_data.db")
if ($LASTEXITCODE -ne 0) {
  throw "load_db.py failed with exit code $LASTEXITCODE"
}

New-Item -ItemType Directory -Force -Path $stage | Out-Null

Copy-Item -Force $exe $stage

$db = Join-Path $dist "npc_data.db"
if (Test-Path $db) { Copy-Item -Force $db $stage }

# Optional docs
if (Test-Path .\README.md) { Copy-Item -Force .\README.md $stage }
if (Test-Path .\app_config.json) { Copy-Item -Force .\app_config.json $stage }

New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

Write-Host "Creating release zip..."
Compress-Archive -Force -Path (Join-Path $stage '*') -DestinationPath $zipPath

Write-Host "Release created: $zipPath"
