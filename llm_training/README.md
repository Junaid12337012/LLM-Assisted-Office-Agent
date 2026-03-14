# Local fine-tune stack

This repo now ships with a practical local fine-tune path based on `Transformers + PEFT`.

## Recommended path for this machine

This PC is a Windows CPU-only setup, so use a very small local model first.

- Recommended runtime: `Ollama`
- Recommended model: `qwen2.5:0.5b`
- Recommended smoke-train base model: `sshleifer/tiny-gpt2`

## Install

```powershell
.\.tools\python311\runtime\python.exe -m pip install -r .\requirements-train.txt
```

## Validate datasets

```powershell
.\.tools\python311\runtime\python.exe .\llm\dataset_validator.py .\datasets\local_agent_train.jsonl
.\.tools\python311\runtime\python.exe .\llm\dataset_validator.py .\datasets\local_agent_eval.jsonl
```

## Capture approved plans as new training data

```powershell
.\.tools\python311\runtime\python.exe .\desktop_backend.py capture-plan-feedback --instruction "print all today voucher" --local-model --with-screen
.\.tools\python311\runtime\python.exe .\desktop_backend.py export-feedback-dataset --include-seed-dataset
```

This stores approved examples in:

- `data/feedback/local_agent_feedback.jsonl`

and can export a merged train set to:

- `datasets/local_agent_train_feedback.jsonl`

## Check local OpenAI-compatible server

```powershell
$env:LOCAL_AGENT_BASE_URL='http://127.0.0.1:1234/v1'
.\.tools\python311\runtime\python.exe .\llm_training\check_local_server.py
```

## Ollama on this PC

The easiest one-command startup path is:

```powershell
powershell -ExecutionPolicy Bypass -File .\llm_training\start_ollama_server.ps1
```

That script:

- starts `ollama serve` if needed
- pulls `qwen2.5:0.5b`
- sets `LOCAL_AGENT_BASE_URL` to `http://127.0.0.1:11434/v1`
- sets `LOCAL_AGENT_MODEL` to `qwen2.5:0.5b`
- probes the `/v1/models` endpoint

Then test the agent:

```powershell
.\.tools\python311\runtime\python.exe .\desktop_backend.py local-agent-plan --instruction "print all today voucher" --with-screen
```

## LM Studio on this PC

If you want LM Studio instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\llm_training\start_lm_studio_server.ps1
```

Then load a model in LM Studio and run:

```powershell
$env:LOCAL_AGENT_MODEL='your-loaded-model-id'
.\.tools\python311\runtime\python.exe .\desktop_backend.py local-agent-plan --instruction "print all today voucher" --with-screen
```

## Train LoRA adapter

```powershell
.\.tools\python311\runtime\python.exe .\llm_training\train_peft.py `
  --base-model Qwen/Qwen2.5-3B-Instruct `
  --train-file .\datasets\local_agent_train.jsonl `
  --eval-file .\datasets\local_agent_eval.jsonl `
  --output-dir .\artifacts\local_agent_adapter
```

The trainer now also accepts extra train files:

```powershell
.\.tools\python311\runtime\python.exe .\llm_training\train_peft.py `
  --base-model sshleifer/tiny-gpt2 `
  --train-file .\datasets\local_agent_train.jsonl `
  --extra-train-file .\data\feedback\local_agent_feedback.jsonl `
  --eval-file .\datasets\local_agent_eval.jsonl `
  --output-dir .\artifacts\local_agent_adapter_feedback
```

## Tiny smoke-train used on this machine

```powershell
powershell -ExecutionPolicy Bypass -File .\llm_training\smoke_train_tiny.ps1
```

This writes:

- `artifacts/local_agent_adapter_tiny/adapter_model.safetensors`
- `artifacts/local_agent_adapter_tiny/training_manifest.json`

## Feedback retrain loop

The fastest one-command cycle for this repo is:

```powershell
powershell -ExecutionPolicy Bypass -File .\llm_training\train_feedback_loop.ps1
```

That:

- merges the seed train set with `data/feedback/local_agent_feedback.jsonl`
- writes `datasets/local_agent_train_merged.jsonl`
- runs a tiny CPU-safe fine-tune
- writes the adapter to `artifacts/local_agent_adapter_feedback`

## Evaluate the planner

Heuristic planner:

```powershell
.\.tools\python311\runtime\python.exe .\llm_training\evaluate_local_agent.py
```

Local model planner:

```powershell
$env:LOCAL_AGENT_BASE_URL='http://127.0.0.1:11434/v1'
$env:LOCAL_AGENT_MODEL='qwen2.5:0.5b'
.\.tools\python311\runtime\python.exe .\llm_training\evaluate_local_agent.py --use-local-model
```

## Use the trained model

Point your local OpenAI-compatible server at the fine-tuned model or merged adapter,
then run:

```powershell
$env:LOCAL_AGENT_BASE_URL='http://127.0.0.1:1234/v1'
$env:LOCAL_AGENT_MODEL='local-agent'
.\.tools\python311\runtime\python.exe .\desktop_backend.py local-agent-plan --instruction "print all today voucher" --with-screen
```

If you leave the env vars unset, the client now auto-detects:

1. LM Studio on `127.0.0.1:1234`
2. Ollama on `127.0.0.1:11434`

and picks the first live model it finds.
