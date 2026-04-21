$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workspaceRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $pythonPath)) {
  throw "Virtual environment not found. Run .\\scripts\\setup_env.ps1 first."
}

$env:PYTHONPATH = Join-Path $workspaceRoot "src"
Push-Location $workspaceRoot
try {
  & $pythonPath -m p_sensor --profile automation
} finally {
  Pop-Location
}
