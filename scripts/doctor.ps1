$ErrorActionPreference = 'Stop'
$Conda = if ($env:CONDA_EXE) { $env:CONDA_EXE } else { 'conda.exe' }
& $Conda run -n mcpserver --no-capture-output mcp-doctor
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Conda run -n mcpserver --no-capture-output python "$PSScriptRoot\smoke_test.py"
exit $LASTEXITCODE
