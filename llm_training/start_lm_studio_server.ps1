param(
    [int]$Port = 1234,
    [switch]$SkipProbe
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".tools\python311\runtime\python.exe"
$lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"

function Test-LmStudioEndpoint {
    param([int]$ServerPort)
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$ServerPort/v1/models" -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-Path $lms)) {
    throw "LM Studio CLI was not found at $lms. Install LM Studio first, then rerun this script."
}

if (-not (Test-LmStudioEndpoint -ServerPort $Port)) {
    $command = "`"$lms`" server start --port $Port"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $command -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 5
}

$env:LOCAL_AGENT_BASE_URL = "http://127.0.0.1:$Port/v1"
Write-Host "LOCAL_AGENT_BASE_URL=$env:LOCAL_AGENT_BASE_URL"
Write-Host "Load a model inside LM Studio or with the LM Studio CLI before running the agent."

if (-not $SkipProbe) {
    try {
        & $python (Join-Path $repoRoot "llm_training\check_local_server.py")
    }
    catch {
        Write-Warning "LM Studio did not answer on port $Port. Open LM Studio once, load a model, and rerun this script."
    }
}

Write-Host ""
Write-Host "Then set the model name and test:"
Write-Host "  `$env:LOCAL_AGENT_BASE_URL='http://127.0.0.1:$Port/v1'"
Write-Host "  `$env:LOCAL_AGENT_MODEL='your-loaded-model-id'"
Write-Host "  .\\.tools\\python311\\runtime\\python.exe .\\desktop_backend.py local-agent-plan --instruction ""print all today voucher"" --with-screen"
