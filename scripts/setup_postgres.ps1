param([ValidateSet('setup','start','stop','status')][string]$Action = 'setup', [string]$RuntimeAlias)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$runtimeRoot = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$aliasConfig = Join-Path $runtimeRoot 'pg-runtime-alias'
if (-not $RuntimeAlias -and (Test-Path -LiteralPath $aliasConfig)) {
    $RuntimeAlias = (Get-Content -Raw -LiteralPath $aliasConfig).Trim()
}
if ($RuntimeAlias) {
    $RuntimeAlias = [IO.Path]::GetFullPath($RuntimeAlias)
    if ($RuntimeAlias -match '[^\x00-\x7F]') { throw 'RuntimeAlias must be an ASCII path' }
    if (Test-Path -LiteralPath $RuntimeAlias) {
        $link = Get-Item -LiteralPath $RuntimeAlias
        if ($link.LinkType -ne 'Junction' -or $link.Target -ne $runtimeRoot) { throw 'Alias is not this project runtime junction' }
    } else {
        New-Item -ItemType Junction -Path $RuntimeAlias -Target $runtimeRoot | Out-Null
    }
    Set-Content -LiteralPath $aliasConfig -Value $RuntimeAlias -Encoding utf8
    $runtimeRoot = $RuntimeAlias
}
$pgBin = Join-Path $runtimeRoot 'pgsql/bin'
$pgData = Join-Path $runtimeRoot 'pgdata'
$pgLog = Join-Path $runtimeRoot 'postgres.log'
$archivePath = Join-Path $runtimeRoot 'postgresql-windows.zip'
$pgPort = 55432

function Run-Pg([string]$Name, [string[]]$Arguments) {
    & (Join-Path $pgBin "$Name.exe") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
}
function Start-LocalPg {
    & (Join-Path $pgBin 'pg_ctl.exe') status -D $pgData *> $null
    if ($LASTEXITCODE -eq 0) { Write-Output 'PostgreSQL already running'; return }
    # pg_ctl launches the server; explicitly hide the helper window.
    $startArgs = @('start', '-D', ('"' + $pgData + '"'), '-l', ('"' + $pgLog + '"'), '-w')
    $helper = Start-Process -FilePath (Join-Path $pgBin 'pg_ctl.exe') -ArgumentList $startArgs -WindowStyle Hidden -PassThru
    # Start-Process -Wait waits for the server descendant too; wait only for pg_ctl.
    if (-not $helper.WaitForExit(15000)) { throw 'pg_ctl did not return within 15 seconds' }
    if ($helper.ExitCode -ne 0) { throw "PostgreSQL start failed; inspect .runtime/postgres.log" }
    Write-Output 'PostgreSQL listening on 127.0.0.1:55432'
}
if ($Action -eq 'setup') {
    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot 'pgsql/share/postgres.bki'))) {
        if (-not (Test-Path -LiteralPath $archivePath)) {
            # EDB binary download linked by postgresql.org/download/windows, checked 2026-10-11.
            Invoke-WebRequest 'https://sbp.enterprisedb.com/getfile.jsp?fileid=1260609' -OutFile $archivePath
        }
        $expectedHash = 'E2246BA91D22345BC3D017586C09EDE52D9DF180B1EEB480F050445F1CAD84E2'
        if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $expectedHash) {
            throw 'Downloaded archive differs from the M0 verified PostgreSQL 18.6 archive'
        }
        # Only the server runtime is needed; skip pgAdmin/StackBuilder and their many files.
        $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            foreach ($entry in $zip.Entries) {
                if ($entry.FullName -notmatch '^pgsql/(bin|lib|share)/' -or $entry.FullName.EndsWith('/')) { continue }
                $destination = [IO.Path]::GetFullPath((Join-Path $runtimeRoot $entry.FullName))
                if (-not $destination.StartsWith($runtimeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe archive entry' }
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $true)
            }
        } finally { $zip.Dispose() }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $pgData 'PG_VERSION'))) {
        if (Test-Path -LiteralPath (Join-Path $projectRoot '.env')) {
            throw 'Existing .env: configure manually rather than overwrite user settings'
        }
        $adminPassword = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
        $appPassword = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
        $passwordFile = Join-Path $runtimeRoot 'admin-password'
        Set-Content -LiteralPath $passwordFile -Value $adminPassword -Encoding ascii
        Run-Pg 'initdb' @('-D', $pgData, '-U', 'postgres', '--encoding=UTF8', '--locale=C', '--auth=scram-sha-256', "--pwfile=$passwordFile")
        Add-Content -LiteralPath (Join-Path $pgData 'postgresql.conf') -Value @"
listen_addresses = '127.0.0.1'
port = $pgPort
timezone = 'UTC'
log_statement = 'none'
log_min_error_statement = 'panic'
"@
        # Keep the generated app password only in ignored local configuration.
        Set-Content -LiteralPath (Join-Path $runtimeRoot 'app-password') -Value $appPassword -Encoding ascii
    }
    Start-LocalPg
    $oldPgPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = (Get-Content -Raw -LiteralPath (Join-Path $runtimeRoot 'admin-password')).Trim()
        $appPassword = (Get-Content -Raw -LiteralPath (Join-Path $runtimeRoot 'app-password')).Trim()
        # Generated hexadecimal passwords cannot inject SQL; never log this SQL file.
        $bootstrapFile = Join-Path $runtimeRoot 'bootstrap.sql'
        $bootstrapSql = @"
SELECT 'CREATE ROLE after_sales LOGIN PASSWORD ''$appPassword''' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname='after_sales') \gexec
SELECT 'CREATE DATABASE after_sales_dev OWNER after_sales' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='after_sales_dev') \gexec
SELECT 'CREATE DATABASE after_sales_test OWNER after_sales' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='after_sales_test') \gexec
"@
        Set-Content -LiteralPath $bootstrapFile -Value $bootstrapSql -Encoding utf8
        Run-Pg 'psql' @('-h','127.0.0.1','-p',"$pgPort",'-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-f',$bootstrapFile)
        $envPath = Join-Path $projectRoot '.env'
        if (-not (Test-Path -LiteralPath $envPath)) {
            Set-Content -LiteralPath $envPath -Value "DEV_MODE=true`nDATABASE_URL=postgresql+psycopg://after_sales:$appPassword@127.0.0.1:$pgPort/after_sales_dev`nSESSION_TTL_SECONDS=3600" -Encoding utf8
        }
    } finally {
        $env:PGPASSWORD = $oldPgPassword
    }
    Run-Pg 'postgres' @('--version')
} elseif ($Action -eq 'start') {
    Start-LocalPg
} elseif ($Action -eq 'stop') {
    Run-Pg 'pg_ctl' @('stop','-D',$pgData,'-m','fast','-w')
} else {
    Run-Pg 'pg_ctl' @('status','-D',$pgData)
}
