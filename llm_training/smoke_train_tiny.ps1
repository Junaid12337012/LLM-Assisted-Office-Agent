param(
    [string]$BaseModel = "sshleifer/tiny-gpt2",
    [string]$OutputDir = "artifacts/local_agent_adapter_tiny"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".tools\python311\runtime\python.exe"

& $python (Join-Path $repoRoot "llm_training\train_peft.py") `
    --base-model $BaseModel `
    --output-dir (Join-Path $repoRoot $OutputDir) `
    --max-train-samples 4 `
    --max-eval-samples 2 `
    --num-train-epochs 1 `
    --batch-size 1 `
    --grad-accum 1 `
    --learning-rate 1e-4 `
    --save-strategy no
