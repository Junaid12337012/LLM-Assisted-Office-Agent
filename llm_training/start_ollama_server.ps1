param(
    [string]$Model = "qwen2.5:0.5b",
    [switch]$SkipPull,
    [switch]$SkipProbe
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".tools\python311\runtime\python.exe"

function Get-OllamaPath {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    throw "Ollama is not installed. Install it first, then rerun this script."
}

function Test-OllamaEndpoint {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

$ollama = Get-OllamaPath
if (-not (Test-OllamaEndpoint)) {
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 3
}

if (-not $SkipPull) {
    & $ollama pull $Model
}

$env:LOCAL_AGENT_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LOCAL_AGENT_MODEL = $Model

Write-Host "LOCAL_AGENT_BASE_URL=$env:LOCAL_AGENT_BASE_URL"
Write-Host "LOCAL_AGENT_MODEL=$env:LOCAL_AGENT_MODEL"
Write-Host "Env vars are optional after this setup because the client can auto-detect Ollama."

if (-not $SkipProbe) {
    & $python (Join-Path $repoRoot "llm_training\check_local_server.py")
}

Write-Host ""
Write-Host "Test the planner with:"
Write-Host "  `$env:LOCAL_AGENT_BASE_URL='http://127.0.0.1:11434/v1'"
Write-Host "  `$env:LOCAL_AGENT_MODEL='$Model'"
Write-Host "  .\\.tools\\python311\\runtime\\python.exe .\\desktop_backend.py local-agent-plan --instruction ""print all today voucher"" --with-screen"
