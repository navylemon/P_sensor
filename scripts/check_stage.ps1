[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Config = "dev_local/config/stage_shot702_osms20_35.local.json",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$StageArgs
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = Join-Path $Root "src"
Push-Location $Root
try {
    & $Python -m p_sensor.motion.shot_cli --config $Config @StageArgs
} finally {
    Pop-Location
}
