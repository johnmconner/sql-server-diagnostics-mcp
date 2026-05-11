$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$envFile = Join-Path $repoRoot '.env'

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw 'Python was not found on PATH. Install Python 3.11+ and rerun this script.'
}

$pythonExe = $pythonCommand.Source

Write-Host "Using Python: $pythonExe"
Write-Host 'Installing project dependencies...'
& $pythonExe -m pip install -e "${repoRoot}[dev]"
if ($LASTEXITCODE -ne 0) {
    throw 'Dependency installation failed.'
}

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Missing .env file at $envFile"
}

Get-Content -LiteralPath $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) {
        return
    }

    $parts = $line -split '=', 2
    if ($parts.Count -ne 2) {
        return
    }

    [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
}

$logPath = Join-Path $repoRoot 'logs\sql-tshooter.log'
[System.Environment]::SetEnvironmentVariable('SQL_TSHOOTER_LOG_PATH', $logPath, 'Process')
[System.Environment]::SetEnvironmentVariable('PYTHONPATH', (Join-Path $repoRoot 'src'), 'Process')

Write-Host 'Running preflight...'
& $pythonExe -m sql_tshooter.preflight
if ($LASTEXITCODE -ne 0) {
    throw 'Preflight failed.'
}

$launcherPath = Join-Path $repoRoot 'scripts\run_sql_tshooter_mcp.py'

Write-Host ''
Write-Host 'Codex config snippet:'
Write-Host ''
Write-Host '[mcp_servers.sql-tshooter]'
Write-Host ("command = '{0}'" -f $pythonExe)
Write-Host ("args = ['{0}']" -f $launcherPath)
Write-Host ''
Write-Host ("Log path: {0}" -f $logPath)
