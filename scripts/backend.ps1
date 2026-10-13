param([ValidateSet('serve','seed','migrate','test','reset','worker','agent-worker','index-policies')][string]$Action = 'serve', [string]$Target,
    [ValidateSet('success','timeout_before','timeout_after','unavailable')][string]$Fault = 'success', [switch]$Watch)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run uv sync --locked first' }
$oldPythonPath = $env:PYTHONPATH
Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'backend'
    switch ($Action) {
        'serve' { & $pythonExe -m app.cli serve }
        'seed' { & $pythonExe -m app.seed }
        'migrate' { & $pythonExe -m alembic upgrade head }
        'test' { & $pythonExe -m pytest }
        'worker' { if ($Watch) { & $pythonExe -m app.cli refund-worker --fault $Fault --watch } else { & $pythonExe -m app.cli refund-worker --fault $Fault } }
        'agent-worker' { if ($Watch) { & $pythonExe -m app.cli agent-worker --watch } else { & $pythonExe -m app.cli agent-worker } }
        'index-policies' { & $pythonExe -m app.cli index-policies }
        'reset' {
            if (-not $Target) { throw 'Reset requires -Target with the exact local database name' }
            & $pythonExe -m app.cli reset --target $Target
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Backend $Action failed (exit $LASTEXITCODE)" }
} finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
