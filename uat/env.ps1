# Dot-source to get the UAT settings in the current PowerShell (for running a worker once):
#   . .\uat\env.ps1
# Same settings uat.ps1 uses: uat\uat.env, uat\uat.local.env and the data\uat paths.
$uatRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
foreach ($f in @('uat.env', 'uat.local.env')) {
    $p = Join-Path $PSScriptRoot $f
    if (-not (Test-Path $p)) { continue }
    foreach ($line in Get-Content -LiteralPath $p -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -gt 0) { [Environment]::SetEnvironmentVariable($t.Substring(0, $i).Trim(), $t.Substring($i + 1).Trim(), 'Process') }
    }
}
$u = (Join-Path $uatRoot 'data\uat') -replace '\\', '/'
$env:DATABASE_URL = "sqlite:///$u/solaris_uat.uat.db"
$env:ACCOUNT_EMAIL_CAPTURE_DIR = "$u/account_mail"
$env:TARIFF_INTAKE_DIR = "$u/tariff_intake"
Set-Location (Join-Path $uatRoot 'backend')
$env:PYTHONPATH = (Get-Location).Path
