param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$PipArgs
)

$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $workspaceRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $venvPython)) {
  throw "Virtual environment not found. Run .\\scripts\\setup_env.ps1 first."
}

if (-not $PipArgs -or $PipArgs.Count -eq 0) {
  throw "Usage: .\\scripts\\pip_sync.ps1 <pip arguments>"
}

& $venvPython -m pip @PipArgs
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

$mutatingCommands = @("install", "uninstall")
if ($mutatingCommands -contains $PipArgs[0].ToLowerInvariant()) {
  & (Join-Path $PSScriptRoot "freeze_requirements.ps1")
}

