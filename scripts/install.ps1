param(
    [string]$EnvironmentName = 'mcpserver'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Conda = if ($env:CONDA_EXE) { $env:CONDA_EXE } else { 'conda.exe' }

$existing = & $Conda env list --json | ConvertFrom-Json
$environmentPath = $existing.envs | Where-Object { (Split-Path $_ -Leaf) -eq $EnvironmentName }
if ($environmentPath) {
    & $Conda run -n $EnvironmentName python -m pip install -e "${Root}[dev]"
} else {
    Push-Location $Root
    try {
        & $Conda env create -n $EnvironmentName -f "$Root\environment.yml"
    } finally {
        Pop-Location
    }
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Conda run -n $EnvironmentName --no-capture-output python "$PSScriptRoot\smoke_test.py"
exit $LASTEXITCODE
