$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$envFile = Join-Path $repoRoot '.env'

if (Test-Path -LiteralPath $envFile) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            return
        }

        $parts = $line -split '=', 2
        if ($parts.Count -ne 2) {
            return
        }

        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        [System.Environment]::SetEnvironmentVariable($key, $value, 'Process')
    }
}

[System.Environment]::SetEnvironmentVariable('PYTHONPATH', (Join-Path $repoRoot 'src'), 'Process')
[System.Environment]::SetEnvironmentVariable(
    'SQL_TSHOOTER_LOG_PATH',
    (Join-Path $repoRoot 'logs\sql-tshooter.log'),
    'Process'
)

& python -m sql_tshooter.server
exit $LASTEXITCODE
