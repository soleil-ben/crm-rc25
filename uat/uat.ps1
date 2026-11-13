# Solaris Express CRM - portable UAT launcher (RC-UAT-25).
#
#   uat.ps1 start  [-Headless]   build if needed, seed if no UAT database, start, open browser
#   uat.ps1 reset  [-Headless]   stop, rebuild the UAT database from scratch, start
#   uat.ps1 stop                 stop the backend and frontend this launcher started
#   uat.ps1 smoke                HTTP checks against the running servers
#   uat.ps1 python               list every Python on this PC and the one START would use
#
# Synthetic UAT data only. Never reads or writes a backend\.env; every setting is given here
# or in uat\uat.env. Email is written to local files only (data\uat\account_mail).
# Windows PowerShell 5.1 compatible.

param(
    [Parameter(Position = 0)][ValidateSet('start', 'reset', 'stop', 'smoke', 'python')][string]$Action = 'start',
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$UatDir = Join-Path $Root 'data\uat'
$LogDir = Join-Path $UatDir 'logs'
$PidFile = Join-Path $UatDir 'servers.pid'
$VenvPy = Join-Path $Backend '.venv\Scripts\python.exe'
$BackendPort = 8000
$FrontendPort = 5173

function Say([string]$msg) { Write-Host "[uat] $msg" }
function Fail([string]$msg) { Write-Host "[uat] ERROR: $msg" -ForegroundColor Red; exit 1 }

# Supported Python: 64-bit CPython 3.11 to 3.14. Tested: 3.12.10 (the reference) and 3.14.9
# (RC-UAT-19: every pinned package installs from a wheel and the backend tests pass).
# Python 3.15 is NOT supported yet: httptools, MarkupSafe, pydantic_core, PyYAML and watchfiles
# have no 3.15 wheel at the pinned versions (pydantic_core would need a Rust build).
$PythonPreference = @('3.12', '3.13', '3.14', '3.11')
$Python315Reason = 'Python 3.15+ is not supported yet: the pinned httptools, MarkupSafe, pydantic_core, PyYAML and watchfiles have no 3.15 wheel'

function Invoke-Capture([string]$exe, [string[]]$arguments) {
    # Run a program and return its standard output, or $null when it fails. Local
    # ErrorActionPreference: under PowerShell 5.1 with 'Stop', any text a program writes to
    # stderr (a harmless warning) would otherwise abort the call.
    $ErrorActionPreference = 'Continue'
    $out = $null
    try { $out = & $exe @arguments 2>$null } catch { return $null }
    if ($LASTEXITCODE -ne 0) { return $null }
    return $out
}

function Get-UatPythonOverride {
    # UAT_PYTHON as typed: `set UAT_PYTHON="C:\Program Files\...\python.exe"` keeps the quotes in
    # cmd, so strip them; an unusable value is reported, never a crash.
    if (-not $env:UAT_PYTHON) { return $null }
    $v = $env:UAT_PYTHON.Trim().Trim('"').Trim("'").Trim()
    if (-not $v) { return $null }
    try { return [System.IO.Path]::GetFullPath($v) } catch { return $v }
}

function Get-PythonCandidates {
    # Every python.exe this PC offers, from the override, the py launcher, the standard install
    # folders and PATH. WindowsApps entries (Microsoft Store aliases) are listed but never run:
    # an alias opens the Store instead of running Python.
    $paths = New-Object System.Collections.Generic.List[string]
    $override = Get-UatPythonOverride
    if ($override) { $paths.Add($override) }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($line in @(Invoke-Capture 'py' @('-0p'))) {
            $m = [regex]::Match([string]$line, '([A-Za-z]:\\.*?python[w]?\.exe)', 'IgnoreCase')
            if ($m.Success) { $paths.Add($m.Groups[1].Value.Trim()) }
        }
    }
    $globs = @()
    if ($env:LOCALAPPDATA) {
        $globs += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'
        $globs += Join-Path $env:LOCALAPPDATA 'Python\pythoncore-3*\python.exe'
    }
    if ($env:ProgramFiles) { $globs += Join-Path $env:ProgramFiles 'Python3*\python.exe' }
    if (${env:ProgramFiles(x86)}) { $globs += Join-Path ${env:ProgramFiles(x86)} 'Python3*\python.exe' }
    $globs += 'C:\Python3*\python.exe'
    foreach ($g in $globs) {
        foreach ($f in (Get-ChildItem -Path $g -ErrorAction SilentlyContinue)) { $paths.Add($f.FullName) }
    }
    foreach ($name in @('python', 'python3')) {
        foreach ($c in (Get-Command $name -All -CommandType Application -ErrorAction SilentlyContinue)) {
            $paths.Add($c.Source)
        }
    }
    if ($env:LOCALAPPDATA) {
        foreach ($name in @('python.exe', 'python3.exe')) {
            $alias = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\$name"
            if (Test-Path -LiteralPath $alias) { $paths.Add($alias) }
        }
    }
    $seen = @{}
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($p in $paths) {
        if (-not $p) { continue }
        $full = $p
        try { $full = [System.IO.Path]::GetFullPath($p) } catch { }
        $key = $full.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if ($full -match '\\WindowsApps\\') {
            $out.Add([pscustomobject]@{ Path = $full; Version = '-'; Bits = 0; Ok = $false; Note = 'WindowsApps (Microsoft Store alias or Store Python), skipped: install from python.org' })
            continue
        }
        $exists = $false
        try { $exists = Test-Path -LiteralPath $full } catch { }
        if (-not $exists) {
            $out.Add([pscustomobject]@{ Path = $full; Version = '-'; Bits = 0; Ok = $false; Note = 'file not found' })
            continue
        }
        $info = Invoke-Capture $full @('-c', "import sys, struct; print('%d.%d.%d %d' % (sys.version_info[0], sys.version_info[1], sys.version_info[2], struct.calcsize('P') * 8))")
        if ($info) { $info = @($info)[-1] }
        if (-not $info) {
            $out.Add([pscustomobject]@{ Path = $full; Version = '?'; Bits = 0; Ok = $false; Note = 'does not run' })
            continue
        }
        $parts = ([string]$info).Trim().Split(' ')
        $version = $parts[0]; $bits = [int]$parts[1]
        $vp = $version.Split('.'); $major = [int]$vp[0]; $minor = [int]$vp[1]
        $ok = $false; $note = ''
        if ($major -ne 3 -or $minor -lt 11) { $note = 'too old (3.11 to 3.14 needed)' }
        elseif ($minor -ge 15) { $note = 'too new: ' + $Python315Reason }
        elseif ($bits -ne 64) { $note = '32-bit; the pinned packages need 64-bit Python' }
        else { $ok = $true; $note = 'usable' }
        $out.Add([pscustomobject]@{ Path = $full; Version = $version; Bits = $bits; Ok = $ok; Note = $note })
    }
    return $out
}

function Find-Python {
    $all = Get-PythonCandidates
    $override = Get-UatPythonOverride
    if ($override) {
        # An explicit choice wins when it is usable; otherwise say why and fall back.
        $chosen = $all | Where-Object { $_.Path -eq $override } | Select-Object -First 1
        if ($chosen -and $chosen.Ok) { return @{ Exe = $chosen.Path; Pre = @(); Version = $chosen.Version } }
        if ($chosen) { Say "UAT_PYTHON is not usable ($($chosen.Note)); looking for another Python." }
    }
    foreach ($want in $PythonPreference) {
        foreach ($c in $all) {
            if ($c.Ok -and $c.Version.StartsWith("$want.")) {
                return @{ Exe = $c.Path; Pre = @(); Version = $c.Version }
            }
        }
    }
    Write-Host '[uat] ERROR: no usable Python was found. Supported: 64-bit Python 3.11 to 3.14 (3.12.10 recommended).' -ForegroundColor Red
    if ($all.Count -eq 0) {
        Write-Host '[uat] No Python was found at all (py launcher, standard install folders, PATH).'
    } else {
        Write-Host '[uat] Every Python this PC offers:'
        foreach ($c in $all) { Write-Host ("[uat]   {0,-8} {1}  -- {2}" -f $c.Version, $c.Path, $c.Note) }
    }
    Write-Host @'
[uat] How to fix:
[uat]   1. Install Python 3.12.10, 64-bit, from https://www.python.org/downloads/release/python-31210/
[uat]      ("Windows installer (64-bit)"). On the first screen tick "Add python.exe to PATH";
[uat]      keep "Use admin privileges when installing py.exe" if offered. Python 3.14 also works.
[uat]   2. If you installed Python 3.15: keep it, and install 3.12 (or 3.14) alongside it.
[uat]   3. Close this window, then run START_UAT.bat again.
[uat]   Or point the launcher at a specific python.exe, then run START_UAT.bat from the same window:
[uat]      set UAT_PYTHON=C:\full\path\to\python.exe
[uat]   Optional: Settings > Apps > Advanced app settings > App execution aliases > turn off
[uat]      "python.exe" and "python3.exe" (Microsoft Store aliases). The launcher skips them anyway.
'@
    exit 1
}

function Check-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Fail 'Node.js was not found. Install Node.js 24 LTS (tested with 24.11.1, npm 11.6.2) from nodejs.org, then run again.'
    }
    $v = (node -v).Trim().TrimStart('v'); $p = $v.Split('.')
    $major = [int]$p[0]; $minor = [int]$p[1]
    if ($major -lt 20 -or ($major -eq 20 -and $minor -lt 19) -or ($major -eq 22 -and $minor -lt 12) -or $major -eq 21) {
        Fail "Node.js $v is too old for Vite. Install Node.js 24 LTS (tested with 24.11.1)."
    }
    return $v
}

function Load-EnvFile([string]$path) {
    if (-not (Test-Path $path)) { return }
    foreach ($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        [Environment]::SetEnvironmentVariable($t.Substring(0, $i).Trim(), $t.Substring($i + 1).Trim(), 'Process')
    }
}

function Set-UatEnvironment {
    if (Test-Path (Join-Path $Backend '.env')) {
        Fail 'backend\.env exists. This UAT package must run without one (it would add settings this launcher does not control). Rename or remove backend\.env, then run again.'
    }
    # Machine-local, generated once, never shipped: a random secret for this PC only.
    $local = Join-Path $PSScriptRoot 'uat.local.env'
    if (-not (Test-Path $local)) {
        $bytes = New-Object byte[] 48
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $secret = [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_').TrimEnd('=')
        $content = "# Generated by uat.ps1 on $(Get-Date -Format s). Local to this PC; do not share.`r`nSECRET_KEY=$secret`r`n"
        [System.IO.File]::WriteAllText($local, $content, (New-Object System.Text.UTF8Encoding $false))
        Say 'Generated uat\uat.local.env (random SECRET_KEY for this PC).'
    }
    Load-EnvFile (Join-Path $PSScriptRoot 'uat.env')
    Load-EnvFile $local
    New-Item -ItemType Directory -Force -Path $UatDir, $LogDir | Out-Null
    $u = $UatDir -replace '\\', '/'
    $env:DATABASE_URL = "sqlite:///$u/solaris_uat.uat.db"
    $env:ACCOUNT_EMAIL_CAPTURE_DIR = "$u/account_mail"
    $env:TARIFF_INTAKE_DIR = "$u/tariff_intake"
    $env:VITE_API_TARGET = "http://127.0.0.1:$BackendPort"
}

function Ensure-Backend {
    if (Test-Path $VenvPy) {
        # A venv built with a Python that has since been removed or upgraded no longer runs.
        $alive = Invoke-Capture $VenvPy @('-c', 'import fastapi, sys; print(sys.version_info[1])')
        if ($alive) { return }
        Say 'backend\.venv no longer works (its Python was removed or changed). Rebuilding it...'
        Remove-Item -Recurse -Force (Join-Path $Backend '.venv')
    }
    $py = Find-Python
    Say "Creating the Python environment with Python $($py.Version) (first run only, a few minutes)..."
    & $py.Exe @($py.Pre) -m venv (Join-Path $Backend '.venv')
    if ($LASTEXITCODE -ne 0) { Fail 'python -m venv failed.' }
    & $VenvPy -m pip install --disable-pip-version-check -q --upgrade pip
    & $VenvPy -m pip install --disable-pip-version-check -q -r (Join-Path $Backend 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force (Join-Path $Backend '.venv'); Fail 'Installing the pinned Python packages failed (see above). Check the internet connection and run again.' }
    & $VenvPy -m pip install --disable-pip-version-check -q --no-deps -e $Backend
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force (Join-Path $Backend '.venv'); Fail 'Installing the backend package failed.' }
}

function Ensure-Frontend {
    $nodeVersion = Check-Node
    if (Test-Path (Join-Path $Frontend 'node_modules\.bin\vite.cmd')) { return }
    Say "Installing the frontend packages with Node $nodeVersion (first run only, a few minutes)..."
    Push-Location $Frontend
    try { & cmd.exe /c 'npm ci --no-audit --no-fund' ; if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed (see above).' } }
    finally { Pop-Location }
}

function Invoke-UatEnv([string[]]$args2) {
    # uat_env.py refuses to build the database DATABASE_URL already points at (its safety
    # check 3); it sets DATABASE_URL for its own subprocesses. So it runs without it, as in
    # docs\UAT\HOW_TO_RUN.md, where the reset comes before the backend's settings.
    $saved = $env:DATABASE_URL
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    try { & $VenvPy (Join-Path $Root 'scripts\uat_env.py') @args2 }
    finally { $env:DATABASE_URL = $saved }
    if ($LASTEXITCODE -ne 0) { Fail "scripts\uat_env.py $($args2 -join ' ') failed (see above)." }
}

function Test-Port([int]$port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return [bool]$c
}

function Wait-Url([string]$url, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Stop-Servers {
    if (-not (Test-Path $PidFile)) { return }
    foreach ($procId in Get-Content $PidFile) {
        if ($procId -match '^\d+$') { & taskkill.exe /PID $procId /T /F 2>$null | Out-Null }
    }
    Remove-Item -Force $PidFile
    Say 'Stopped the backend and frontend.'
}

function Start-Servers {
    foreach ($p in @($BackendPort, $FrontendPort)) {
        if (Test-Port $p) { Fail "Port $p is already in use. Close the program using it (or run STOP_UAT.bat), then run again." }
    }
    $bLog = Join-Path $LogDir 'backend.log'; $fLog = Join-Path $LogDir 'frontend.log'
    $bCmd = "`"$VenvPy`" -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort --app-dir `"$Backend`" --no-proxy-headers > `"$bLog`" 2>&1"
    $b = Start-Process -FilePath cmd.exe -ArgumentList '/c', "`"$bCmd`"" -WorkingDirectory $Backend -WindowStyle Hidden -PassThru
    $fCmd = "npm run dev -- --port $FrontendPort --strictPort > `"$fLog`" 2>&1"
    $f = Start-Process -FilePath cmd.exe -ArgumentList '/c', "`"$fCmd`"" -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru
    Set-Content -Path $PidFile -Value @($b.Id, $f.Id)
    Say "Waiting for the backend on :$BackendPort ..."
    if (-not (Wait-Url "http://127.0.0.1:$BackendPort/health/ready" 90)) { Stop-Servers; Fail "The backend did not become ready. See $bLog" }
    Say "Waiting for the frontend on :$FrontendPort ..."
    if (-not (Wait-Url "http://localhost:$FrontendPort/" 120)) { Stop-Servers; Fail "The frontend did not start. See $fLog" }
}

function Show-Running {
    Write-Host ''
    Say 'Solaris CRM UAT is running.'
    Say "  Staff Portal:      http://localhost:$FrontendPort"
    Say "  Customer Account:  http://localhost:$FrontendPort/account"
    Say "  Captured emails:   $UatDir\account_mail   (open the files in a text editor)"
    Say "  Logs:              $LogDir"
    Say '  Logins: README_LOUIS.md ; passwords: docs\UAT\ENVIRONMENT.md section 2'
}

switch ($Action) {
    'stop' { Stop-Servers; exit 0 }
    'python' {
        # Diagnostic: every Python this PC offers, and the one START would use.
        foreach ($c in (Get-PythonCandidates)) { Write-Host ("[uat]   {0,-8} {1}  -- {2}" -f $c.Version, $c.Path, $c.Note) }
        $py = Find-Python
        Say "START_UAT.bat would use Python $($py.Version): $($py.Exe)"
        exit 0
    }
    'smoke' {
        Set-UatEnvironment
        & $VenvPy (Join-Path $PSScriptRoot 'uat_smoke.py') --root $Root
        exit $LASTEXITCODE
    }
    default {
        Set-UatEnvironment
        Stop-Servers
        Ensure-Backend
        Ensure-Frontend
        $db = Join-Path $UatDir 'solaris_uat.uat.db'
        if ($Action -eq 'reset' -or -not (Test-Path $db)) {
            Say 'Building the UAT database from scratch (synthetic data only)...'
            Invoke-UatEnv @('--reset')
        } else {
            Say 'Using the existing UAT database (RESET_UAT.bat rebuilds it). Adding a fresh demo exchange rate...'
            Invoke-UatEnv @('--refresh-fx')
        }
        Start-Servers
        Show-Running
        if ($Headless) { exit 0 }
        Start-Process "http://localhost:$FrontendPort"
        Write-Host ''
        Read-Host '[uat] Leave this window open while testing. Press Enter here to stop the servers'
        Stop-Servers
    }
}
