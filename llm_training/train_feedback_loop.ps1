param(
    [string]$BaseModel = "sshleifer/tiny-gpt2",
    [string]$FeedbackFile = "data/feedback/local_agent_feedback.jsonl",
    [string]$MergedTrainFile = "datasets/local_agent_train_merged.jsonl",
    [string]$EvalFile = "datasets/local_agent_eval.jsonl",
    [string]$OutputDir = "artifacts/local_agent_adapter_feedback",
    [int]$Epochs = 1
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".tools\python311\runtime\python.exe"

& $python (Join-Path $repoRoot "desktop_backend.py") export-feedback-dataset `
    --dataset-file (Join-Path $repoRoot $FeedbackFile) `
    --output-file (Join-Path $repoRoot $MergedTrainFile) `
    --include-seed-dataset

& $python (Join-Path $repoRoot "llm_training\train_peft.py") `
    --base-model $BaseModel `
    --train-file (Join-Path $repoRoot $MergedTrainFile) `
    --eval-file (Join-Path $repoRoot $EvalFile) `
    --output-dir (Join-Path $repoRoot $OutputDir) `
    --num-train-epochs $Epochs `
    --batch-size 1 `
    --grad-accum 1 `
    --learning-rate 1e-4 `
    --save-strategy no
