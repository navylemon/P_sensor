$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workspaceRoot ".venv\\Scripts\\python.exe"
$defaultConfig = Join-Path $workspaceRoot "dev_local\\config\\stage_shot702_osms20_35.local.json"

if (-not (Test-Path $pythonPath)) {
  throw "Virtual environment not found. Run .\\scripts\\setup_env.ps1 first."
}

$env:PYTHONPATH = Join-Path $workspaceRoot "src"
Push-Location $workspaceRoot
try {
  if (Test-Path $defaultConfig) {
    & $pythonPath -m p_sensor --profile stage --config $defaultConfig
  } else {
    & $pythonPath -m p_sensor --profile stage
  }
} finally {
  Pop-Location
}
