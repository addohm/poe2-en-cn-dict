# Rebuild the dictionary with the Node.js implementation.
# Run after either client is patched:  powershell -File update.ps1
# Reads ../config.json and writes ../dictionary (shared with the Python impl).
[CmdletBinding()]
param(
  [string]$Cn,
  [string]$Intl,
  [switch]$SkipSchemaDownload
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = $PSScriptRoot                        # nodejs/
$repo = Split-Path $PSScriptRoot -Parent     # repo root
$node = Join-Path $root "tools\node\node.exe"
$extract = Join-Path $root "extract"
$cacheDir = Join-Path $extract "cache"
$schemaPath = Join-Path $cacheDir "schema.min.json"

if (-not (Test-Path $node)) {
  throw "Portable Node not found at $node. Run setup.ps1 first."
}

$config = Get-Content (Join-Path $repo "config.json") -Raw | ConvertFrom-Json
if ($Cn)   { $config.cn = $Cn }
if ($Intl) { $config.intl = $Intl }

foreach ($p in @($config.cn, $config.intl)) {
  if (-not (Test-Path (Join-Path $p "Bundles2\_.index.bin"))) {
    throw "No PoE2 bundle index found under '$p'. Check ../config.json."
  }
}

New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

if (-not $SkipSchemaDownload) {
  try {
    Write-Host "Downloading latest dat-schema..."
    Invoke-WebRequest -Uri $config.schemaUrl -OutFile $schemaPath -TimeoutSec 120
  } catch {
    if (Test-Path $schemaPath) {
      Write-Warning "Schema download failed ($($_.Exception.Message)); using cached schema."
    } else {
      throw "Schema download failed and no cached schema exists: $($_.Exception.Message)"
    }
  }
}

Write-Host "Building dictionary..."
Push-Location $extract
try {
  & $node "scripts\build.mjs" `
    --cn $config.cn `
    --intl $config.intl `
    --schema $schemaPath `
    --out (Join-Path $repo "dictionary")
  if ($LASTEXITCODE -ne 0) { throw "build.mjs exited with code $LASTEXITCODE" }
} finally {
  Pop-Location
}

Write-Host ""
Write-Host "Dictionary written to $(Join-Path $repo 'dictionary')" -ForegroundColor Green
