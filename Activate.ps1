$ErrorActionPreference = "Stop"

$activateScript = Join-Path $PSScriptRoot ".venv\\Scripts\\Activate.ps1"

if (-not (Test-Path $activateScript)) {
  throw "Virtual environment activation script not found. Run .\\scripts\\setup_env.ps1 first."
}

& $activateScript
