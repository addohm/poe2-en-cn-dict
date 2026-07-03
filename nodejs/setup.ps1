# First-time setup for the Node.js implementation. Installs a self-contained
# portable Node.js into nodejs/tools/node and the pathofexile-dat library into
# nodejs/extract. No admin rights; nothing is installed system-wide. Idempotent.
[CmdletBinding()]
param(
  [string]$NodeVersion = "v24.18.0"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = $PSScriptRoot                       # nodejs/
$tools = Join-Path $root "tools"
$nodeDir = Join-Path $tools "node"
$nodeExe = Join-Path $nodeDir "node.exe"
$extract = Join-Path $root "extract"

if (-not (Test-Path $nodeExe)) {
  New-Item -ItemType Directory -Force -Path $tools | Out-Null
  $zip = Join-Path $tools "node.zip"
  $url = "https://nodejs.org/dist/$NodeVersion/node-$NodeVersion-win-x64.zip"
  Write-Host "Downloading portable Node $NodeVersion ..."
  Invoke-WebRequest -Uri $url -OutFile $zip -TimeoutSec 600
  Expand-Archive -Path $zip -DestinationPath $tools -Force
  if (Test-Path $nodeDir) { Remove-Item -Recurse -Force $nodeDir }
  Rename-Item (Join-Path $tools "node-$NodeVersion-win-x64") $nodeDir
  Remove-Item $zip
  Write-Host "Node installed at $nodeExe"
} else {
  Write-Host "Node already present at $nodeExe"
}

if (-not (Test-Path (Join-Path $extract "package.json"))) {
  '{ "name": "poe2-dict-extract", "private": true, "version": "1.0.0" }' |
    Out-File -Encoding utf8 (Join-Path $extract "package.json")
}
$npmCli = Join-Path $nodeDir "node_modules\npm\bin\npm-cli.js"
if (-not (Test-Path (Join-Path $extract "node_modules\pathofexile-dat"))) {
  Write-Host "Installing pathofexile-dat ..."
  Push-Location $extract
  try { & $nodeExe $npmCli install pathofexile-dat | Out-Host }
  finally { Pop-Location }
}

Write-Host ""
Write-Host "Setup complete. Now run:  powershell -File update.ps1" -ForegroundColor Green
