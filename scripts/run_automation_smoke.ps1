[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Config = "config/channel_settings_automation.example.json",
    [string]$Recipe = "config/experiment_recipe_smoke.example.json",
    [string]$MotionConfig = "dev_local/config/stage_shot702_osms20_35.local.json",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SmokeArgs
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
    $motionConfigPath = Join-Path $Root $MotionConfig
    if (Test-Path $motionConfigPath) {
        & $Python -m p_sensor.automation.smoke_cli --config $Config --recipe $Recipe --motion-config $MotionConfig @SmokeArgs
    } else {
        & $Python -m p_sensor.automation.smoke_cli --config $Config --recipe $Recipe @SmokeArgs
    }
} finally {
    Pop-Location
}
