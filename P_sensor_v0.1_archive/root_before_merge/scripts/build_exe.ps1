$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workspaceRoot ".venv\\Scripts\\python.exe"
$specPath = Join-Path $workspaceRoot "P_sensor.spec"
$distExePath = Join-Path $workspaceRoot "dist\\P_sensor.exe"
$workPath = Join-Path $workspaceRoot ("dev_local\\tmp\\pyinstaller_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

if (-not (Test-Path $pythonPath)) {
  throw "Virtual environment not found. Run .\\scripts\\setup_env.ps1 first."
}

if (-not (Test-Path $specPath)) {
  throw "Spec file not found: $specPath"
}

Push-Location $workspaceRoot
try {
  New-Item -ItemType Directory -Force $workPath | Out-Null
  if (Test-Path $distExePath) {
    try {
      Remove-Item -LiteralPath $distExePath -Force
    } catch {
      throw "Failed to remove existing build artifact '$distExePath'. Close the running exe or release the file lock, then retry."
    }
  }
  & $pythonPath -m PyInstaller --noconfirm --clean --workpath $workPath $specPath
} finally {
  Pop-Location
}
