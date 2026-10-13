param([ValidateSet('dev','build','preview','install')][string]$Action = 'dev')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    if ($Action -eq 'install') { & npm.cmd ci --cache ../.runtime/npm-cache --no-fund --no-audit }
    else { & npm.cmd run $Action }
    if ($LASTEXITCODE -ne 0) { throw "Frontend $Action failed (exit $LASTEXITCODE)" }
} finally { Pop-Location }
