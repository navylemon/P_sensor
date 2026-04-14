[CmdletBinding()]
param(
  [switch]$Recreate
)

$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $workspaceRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\\python.exe"
$requirementsPath = Join-Path $workspaceRoot "requirements.txt"
$localDevRoot = Join-Path $workspaceRoot "dev_local"
$tmpRoot = Join-Path $localDevRoot "tmp"

function Get-ProjectPython {
  $candidates = @()

  if ($env:PROJECT_PYTHON) {
    $candidates += $env:PROJECT_PYTHON
  }

  $candidates += "C:\\python\\python.exe"

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return "py -3"
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return $python.Source
  }

  throw "Python interpreter not found. Set PROJECT_PYTHON or install Python."
}

function Invoke-PythonCommand {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PythonCommand,
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments
  )

  if ($PythonCommand -eq "py -3") {
    & py -3 @Arguments
  } else {
    & $PythonCommand @Arguments
  }

  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed: $PythonCommand $($Arguments -join ' ')"
  }
}

function Install-PipFromBundledWheel {
  param(
    [Parameter(Mandatory = $true)]
    [string]$BasePythonPath
  )

  $baseRoot = Split-Path -Parent $BasePythonPath
  $wheelPath = Get-ChildItem -Path (Join-Path $baseRoot "Lib\\ensurepip\\_bundled") -Filter "pip-*.whl" |
    Sort-Object Name -Descending |
    Select-Object -First 1 -ExpandProperty FullName

  if (-not $wheelPath) {
    throw "Bundled pip wheel not found."
  }

  $tempZip = Join-Path $tmpRoot "pip-bootstrap.zip"
  $tempExtract = Join-Path $venvPath "Lib\\site-packages\\_pip_bootstrap"
  $sitePackages = Join-Path $venvPath "Lib\\site-packages"

  New-Item -ItemType Directory -Force $tmpRoot | Out-Null
  Copy-Item -LiteralPath $wheelPath -Destination $tempZip -Force

  if (Test-Path $tempExtract) {
    Remove-Item -LiteralPath $tempExtract -Recurse -Force
  }

  Expand-Archive -LiteralPath $tempZip -DestinationPath $tempExtract -Force
  Copy-Item -Path (Join-Path $tempExtract "pip") -Destination $sitePackages -Recurse -Force
  Copy-Item -Path (Join-Path $tempExtract "pip-*.dist-info") -Destination $sitePackages -Recurse -Force

  Ensure-PipWrappers
}

function Ensure-PipWrappers {
  @(
    @{ Name = "pip.bat"; Content = "@echo off`r`n""%~dp0python.exe"" -m pip %*`r`n" },
    @{ Name = "pip3.bat"; Content = "@echo off`r`n""%~dp0python.exe"" -m pip %*`r`n" },
    @{ Name = "pip3.13.bat"; Content = "@echo off`r`n""%~dp0python.exe"" -m pip %*`r`n" }
  ) | ForEach-Object {
    Set-Content -LiteralPath (Join-Path $venvPath "Scripts\\$($_.Name)") -Value $_.Content -Encoding ascii
  }
}

function Resolve-BasePythonPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PythonCommand
  )

  if ($PythonCommand -eq "py -3") {
    $resolvedBasePython = (& py -3 -c "import sys; print(sys.executable)")
    if ($LASTEXITCODE -ne 0) {
      throw "Unable to resolve base python from py launcher."
    }
    return $resolvedBasePython.Trim()
  }

  return $PythonCommand
}

function Ensure-ActivationScripts {
  param(
    [Parameter(Mandatory = $true)]
    [string]$BasePythonPath
  )

  $baseRoot = Split-Path -Parent $BasePythonPath
  $venvScriptRoot = Join-Path $baseRoot "Lib\\venv\\scripts"
  $venvBinDir = Join-Path $venvPath "Scripts"
  $promptName = Split-Path $venvPath -Leaf

  New-Item -ItemType Directory -Force $venvBinDir | Out-Null

  $activatePs1Template = Join-Path $venvScriptRoot "common\\Activate.ps1"
  if (Test-Path $activatePs1Template) {
    Copy-Item -LiteralPath $activatePs1Template -Destination (Join-Path $venvBinDir "Activate.ps1") -Force
  }

  $activateBatTemplate = Join-Path $venvScriptRoot "nt\\activate.bat"
  if (Test-Path $activateBatTemplate) {
    $activateBat = Get-Content -LiteralPath $activateBatTemplate -Raw
    $activateBat = $activateBat.Replace("__VENV_DIR__", $venvPath)
    $activateBat = $activateBat.Replace("__VENV_PROMPT__", $promptName)
    $activateBat = $activateBat.Replace("__VENV_BIN_NAME__", "Scripts")
    Set-Content -LiteralPath (Join-Path $venvBinDir "activate.bat") -Value $activateBat -Encoding ascii
  }

  $deactivateBatTemplate = Join-Path $venvScriptRoot "nt\\deactivate.bat"
  if (Test-Path $deactivateBatTemplate) {
    Copy-Item -LiteralPath $deactivateBatTemplate -Destination (Join-Path $venvBinDir "deactivate.bat") -Force
  }
}

function Ensure-PyVenvConfig {
  param(
    [Parameter(Mandatory = $true)]
    [string]$BasePythonPath
  )

  $resolvedVenvPath = [System.IO.Path]::GetFullPath($venvPath)
  $resolvedBasePythonPath = [System.IO.Path]::GetFullPath($BasePythonPath)
  $baseRoot = Split-Path -Parent $resolvedBasePythonPath
  $pyvenvConfigPath = Join-Path $venvPath "pyvenv.cfg"
  $includeSystemSitePackages = "false"

  if (Test-Path $pyvenvConfigPath) {
    $existingSetting = Get-Content -LiteralPath $pyvenvConfigPath |
      Where-Object { $_ -match "^include-system-site-packages\\s*=\\s*" } |
      Select-Object -First 1

    if ($existingSetting) {
      $includeSystemSitePackages = ($existingSetting -split "\\s*=\\s*", 2)[1].Trim()
    }
  }

  $version = & $resolvedBasePythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve Python version from $resolvedBasePythonPath"
  }

  $content = @(
    "home = $baseRoot",
    "include-system-site-packages = $includeSystemSitePackages",
    "version = $($version.Trim())",
    "executable = $resolvedBasePythonPath",
    "command = $resolvedBasePythonPath -m venv --without-pip --upgrade $resolvedVenvPath",
    "prompt = .venv"
  )

  Set-Content -LiteralPath $pyvenvConfigPath -Value $content -Encoding ascii
}

function RequirementsHasPackages {
  if (-not (Test-Path $requirementsPath)) {
    return $false
  }

  $meaningfulLines = Get-Content $requirementsPath |
    Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") }

  return [bool]$meaningfulLines
}

$projectPython = Get-ProjectPython
Write-Host "Using Python: $projectPython"

if ($Recreate -and (Test-Path $venvPath)) {
  $backupPath = Join-Path $workspaceRoot (".venv_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
  Rename-Item -LiteralPath $venvPath -NewName (Split-Path $backupPath -Leaf)
}

if (-not (Test-Path $venvPython)) {
  Invoke-PythonCommand -PythonCommand $projectPython -Arguments @("-m", "venv", $venvPath)
}

try {
  & $venvPython -m pip --version | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "pip missing"
  }
} catch {
  $resolvedBasePython = Resolve-BasePythonPath -PythonCommand $projectPython
  Install-PipFromBundledWheel -BasePythonPath $resolvedBasePython
}

Ensure-PipWrappers
$resolvedBasePython = Resolve-BasePythonPath -PythonCommand $projectPython
Ensure-ActivationScripts -BasePythonPath $resolvedBasePython
Ensure-PyVenvConfig -BasePythonPath $resolvedBasePython

if (RequirementsHasPackages) {
  & $venvPython -m pip install -r $requirementsPath
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install dependencies from requirements.txt"
  }
}

& (Join-Path $PSScriptRoot "freeze_requirements.ps1")

Write-Host "Environment ready."
Write-Host "Activate with: .\\.venv\\Scripts\\Activate.ps1"
