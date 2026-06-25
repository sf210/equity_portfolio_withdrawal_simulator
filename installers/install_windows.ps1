# Installer for the Equity Portfolio Withdrawal Simulator (Windows).
#
# - Verifies Python >= 3.12 (with tkinter); offers to install Python 3.14 if not
#   (via the official python.org installer).
# - Creates a virtual environment (.venv) in the project directory.
# - Installs the Python dependencies from requirements.txt.
# - Adds Start Menu + Desktop shortcuts that launch the Monte Carlo GUI, using
#   the project icon.
#
# Run via install_windows.bat (double-click), or:
#   powershell -ExecutionPolicy Bypass -File install_windows.ps1
#
# Re-runnable: existing venv / shortcuts are refreshed in place.

$ErrorActionPreference = 'Stop'

$MinVersion = [version]'3.12'
$PyTarget   = '3.14'
# Patch release for the python.org installer fallback. Override via env var:
#   set PY_FULL=3.14.1   (before running install_windows.bat)
$PyFull = if ($env:PY_FULL) { $env:PY_FULL } else { '3.14.0' }

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$Gui        = Join-Path $ProjectDir 'montecarlo_gui.py'
$Venv       = Join-Path $ProjectDir '.venv'
$Reqs       = Join-Path $ProjectDir 'requirements.txt'
$IconIco    = Join-Path $ScriptDir 'icons\icon.ico'

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Gui)) { Die "Cannot find montecarlo_gui.py at $Gui" }

# Returns the python.exe path of the first candidate that is >= MinVersion and
# has tkinter, or $null.
function Find-Python {
    $check = @'
import sys, importlib.util
if sys.version_info < (3, 12):
    sys.exit(1)
try:
    import tkinter  # noqa: F401
except Exception:
    sys.exit(2)
print(sys.executable)
'@
    $candidates = @(
        @('py', '-3.14'), @('py', '-3.13'), @('py', '-3.12'),
        @('py', '-3'),    @('python'),       @('python3')
    )
    foreach ($c in $candidates) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $cargs = @()
        if ($c.Count -gt 1) { $cargs += $c[1..($c.Count - 1)] }
        $cargs += @('-c', $check)
        try {
            $out = & $exe @cargs 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
        } catch { }
    }
    return $null
}

function Install-Python {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -match 'ARM64') { 'arm64' } else { 'amd64' }
    $file = "python-$PyFull-$arch.exe"
    $url  = "https://www.python.org/ftp/python/$PyFull/$file"
    $dest = Join-Path $env:TEMP $file
    Info "Downloading the official Python $PyFull installer"
    Write-Host "    $url"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    } catch {
        Die @"
Could not download $url
Install Python $PyTarget manually from https://www.python.org/downloads/windows/
then re-run this installer. (Set PY_FULL=<version> if $PyFull is not current.)
"@
    }
    Info "Running the Python installer (a UAC prompt may appear)"
    # Per-user, add to PATH, include Tcl/Tk + pip, no UI.
    $proc = Start-Process -FilePath $dest -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1',
        'Include_tcltk=1', 'Include_pip=1', 'Include_launcher=1'
    )
    if ($proc.ExitCode -ne 0) {
        Die "Python installer exited with code $($proc.ExitCode). Install Python $PyTarget manually and re-run."
    }
    # Make the freshly installed python/py visible to this session.
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path','User')
}

$Python = Find-Python
if (-not $Python) {
    Warn "Python $($MinVersion) or newer (with tkinter) was not found."
    $reply = Read-Host "May I install Python $PyTarget now? [y/N]"
    if ($reply -match '^(y|yes)$') {
        Install-Python
        $Python = Find-Python
    } else {
        Die "Python is required. Install Python $PyTarget, then re-run."
    }
    if (-not $Python) {
        Die "Still no suitable Python after install. Install Python $PyTarget (with tkinter) manually, then re-run."
    }
}
Info "Using Python: $Python"
& $Python -V

if (Test-Path $Venv) { Info "Refreshing virtual environment at $Venv" }
else { Info "Creating virtual environment at $Venv" }
& $Python -m venv $Venv
if ($LASTEXITCODE -ne 0) { Die "Failed to create the virtual environment." }

$VenvPy  = Join-Path $Venv 'Scripts\python.exe'
$VenvPyw = Join-Path $Venv 'Scripts\pythonw.exe'
& $VenvPy -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Die "tkinter is not available in the virtual environment. Reinstall Python from python.org with the 'tcl/tk and IDLE' option, then re-run."
}

Info "Installing dependencies from requirements.txt"
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r $Reqs
if ($LASTEXITCODE -ne 0) { Die "Dependency installation failed." }

# --- shortcuts ----------------------------------------------------------------
Info "Creating Start Menu and Desktop shortcuts"
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path) {
    $sc = $shell.CreateShortcut($path)
    $sc.TargetPath       = $VenvPyw          # pythonw -> no console window
    $sc.Arguments        = "`"$Gui`""
    $sc.WorkingDirectory = $ProjectDir
    $sc.IconLocation     = $IconIco
    $sc.Description       = 'Annuity-equivalent withdrawal Monte Carlo'
    $sc.Save()
}

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
New-Shortcut (Join-Path $startMenu 'Annuity Monte Carlo.lnk')
$desktop = [Environment]::GetFolderPath('Desktop')
New-Shortcut (Join-Path $desktop 'Annuity Monte Carlo.lnk')

Info "Done."
Write-Host ""
Write-Host "  Launch 'Annuity Monte Carlo' from the Start Menu or the Desktop shortcut."
