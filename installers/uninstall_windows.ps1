# Remove the Windows shortcuts and (optionally) the virtual environment.
$ErrorActionPreference = 'Stop'
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$Venv       = Join-Path $ProjectDir '.venv'

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Annuity Monte Carlo.lnk'
$desktop   = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Annuity Monte Carlo.lnk'
foreach ($p in @($startMenu, $desktop)) {
    if (Test-Path $p) { Remove-Item $p -Force; Write-Host "Removed $p" }
}

if (Test-Path $Venv) {
    $reply = Read-Host "Also delete the virtual environment at $Venv? [y/N]"
    if ($reply -match '^(y|yes)$') { Remove-Item $Venv -Recurse -Force; Write-Host "Deleted $Venv" }
}
