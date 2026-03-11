$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
$python = Join-Path $repoRoot '.tools\python311\runtime\python.exe'

if (-not (Test-Path $python)) {
    throw "Portable Python runtime not found at $python"
}

& $python -c "import sys, unittest; sys.path.insert(0, r'$repoRoot'); suite = unittest.defaultTestLoader.discover(r'$repoRoot\tests'); result = unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(0 if result.wasSuccessful() else 1)"
exit $LASTEXITCODE
