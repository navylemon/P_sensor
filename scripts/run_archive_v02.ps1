$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$archiveRoot = Join-Path $workspaceRoot "P_sensor_v0.2_archive_20260414"
$archiveSrc = Join-Path $archiveRoot "src"
$pythonPath = Join-Path $workspaceRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $pythonPath)) {
  throw "Virtual environment not found. Run .\\scripts\\setup_env.ps1 first."
}

if (-not (Test-Path $archiveRoot)) {
  throw "Archive root not found: $archiveRoot"
}

if (-not (Test-Path $archiveSrc)) {
  throw "Archive source directory not found: $archiveSrc"
}

$env:PYTHONPATH = $archiveSrc

Push-Location $archiveRoot
try {
  & $pythonPath -m p_sensor
} finally {
  Pop-Location
}
