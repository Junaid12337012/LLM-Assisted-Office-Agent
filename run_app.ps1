param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandParts
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
$python = Join-Path $repoRoot '.tools\python311\runtime\python.exe'
$desktopScript = Join-Path $repoRoot 'desktop_app.ps1'
$consoleScript = Join-Path $repoRoot 'agent_console.ps1'

if (-not (Test-Path $python)) {
    throw "Portable Python runtime not found at $python"
}
if (-not (Test-Path $desktopScript)) {
    throw "Desktop app script not found at $desktopScript"
}
if (-not (Test-Path $consoleScript)) {
    throw "Agent console script not found at $consoleScript"
}

if ($CommandParts.Count -eq 0) {
    powershell -ExecutionPolicy Bypass -File $desktopScript
    exit $LASTEXITCODE
}

if ($CommandParts[0] -in @('--desktop', '-Desktop')) {
    powershell -ExecutionPolicy Bypass -File $desktopScript
    exit $LASTEXITCODE
}

if ($CommandParts[0] -in @('--console', '-Console')) {
    powershell -ExecutionPolicy Bypass -File $consoleScript
    exit $LASTEXITCODE
}

if ($CommandParts[0] -in @('--web', '-Web')) {
    & $python -c "import sys; sys.path.insert(0, r'$repoRoot'); from app.web_gui import run_server; run_server()"
    exit $LASTEXITCODE
}

$rawCommand = $CommandParts -join ' '
& $python -c "import sys; sys.path.insert(0, r'$repoRoot'); from app.main import run_cli; raise SystemExit(run_cli(sys.argv[1]))" "$rawCommand"
exit $LASTEXITCODE
