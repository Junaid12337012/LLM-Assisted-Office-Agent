from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm.dataset_validator import validate_jsonl_file


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        rows.append(json.loads(raw_line))
    return rows


def _load_many_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_load_jsonl(path))
    return rows


def _import_hf_dataset_class() -> Any:
    repo_path = str(REPO_ROOT)
    removed = False
    if repo_path in sys.path:
        sys.path.remove(repo_path)
        removed = True
    try:
        datasets_module = importlib.import_module("datasets")
    finally:
        if removed:
            sys.path.insert(0, repo_path)
    dataset_class = getattr(datasets_module, "Dataset", None)
    if dataset_class is None:
        raise RuntimeError("Hugging Face 'datasets' package is installed incorrectly or shadowed.")
    return dataset_class


def _format_messages(messages: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for message in messages:
        role = str(message["role"]).upper()
        content = str(message["content"]).strip()
        blocks.append(f"{role}:\n{content}")
    return "\n\n".join(blocks)


def _build_example(record: dict[str, Any]) -> dict[str, str]:
    prompt_parts = [_format_messages(record["messages"])]
    screen_context = record.get("screen_context")
    if isinstance(screen_context, dict) and screen_context:
        prompt_parts.append("SCREEN_CONTEXT:\n" + json.dumps(screen_context, ensure_ascii=True, indent=2))
    prompt_parts.append("Return a safe JSON plan using approved commands only.")
    target = json.dumps(record["expected_plan"], ensure_ascii=True, indent=2)
    return {
        "prompt": "\n\n".join(prompt_parts),
        "target": target,
        "text": "\n\n".join(prompt_parts) + "\n\nASSISTANT:\n" + target,
    }


def _resolve_target_modules(model: Any, explicit: list[str]) -> list[str]:
    if explicit:
        return explicit

    module_names = [name for name, _module in model.named_modules()]
    common_sets = (
        ["q_proj", "k_proj", "v_proj", "o_proj"],
        ["c_attn", "c_proj"],
        ["query_key_value", "dense"],
    )
    for candidate_set in common_sets:
        matched = [name for name in candidate_set if any(module_name.endswith(name) for module_name in module_names)]
        if matched:
            return matched
    raise RuntimeError(
        "Could not infer LoRA target modules automatically. Pass --target-module one or more times."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune a local planning model with Transformers + PEFT.")
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--train-file", default="datasets/local_agent_train.jsonl")
    parser.add_argument("--extra-train-file", action="append", default=[])
    parser.add_argument("--eval-file", default="datasets/local_agent_eval.jsonl")
    parser.add_argument("--output-dir", default="artifacts/local_agent_adapter")
    parser.add_argument("--epochs", "--num-train-epochs", dest="epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accumulation", "--grad-accum", dest="grad_accumulation", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--target-module", action="append", default=[])
    parser.add_argument("--max-train-samples", type=int, default=0)
    parser.add_argument("--max-eval-samples", type=int, default=0)
    parser.add_argument("--save-strategy", choices=["epoch", "no"], default="epoch")
    parser.add_argument("--eval-strategy", choices=["epoch", "no"], default="epoch")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    train_paths = [Path(args.train_file)] + [Path(item) for item in args.extra_train_file]
    eval_path = Path(args.eval_file)
    train_errors: list[str] = []
    for train_path in train_paths:
        train_errors.extend(validate_jsonl_file(train_path))
    eval_errors = validate_jsonl_file(eval_path)
    all_errors = train_errors + eval_errors
    if all_errors:
        raise SystemExit("\n".join(all_errors))

    from peft import LoraConfig, get_peft_model
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )
    Dataset = _import_hf_dataset_class()

    train_examples = [_build_example(item) for item in _load_many_jsonl(train_paths)]
    eval_examples = [_build_example(item) for item in _load_jsonl(eval_path)]
    if args.max_train_samples > 0:
        train_examples = train_examples[: args.max_train_samples]
    if args.max_eval_samples > 0:
        eval_examples = eval_examples[: args.max_eval_samples]
    if not eval_examples:
        args.eval_strategy = "no"
    use_cpu = not torch.cuda.is_available()

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def tokenize_batch(batch: dict[str, list[str]]) -> dict[str, Any]:
        tokenized = tokenizer(
            batch["text"],
            truncation=True,
            max_length=args.max_length,
            padding="max_length",
        )
        tokenized["labels"] = [list(ids) for ids in tokenized["input_ids"]]
        return tokenized

    train_dataset = Dataset.from_list(train_examples).map(tokenize_batch, batched=True, remove_columns=["prompt", "target", "text"])
    eval_dataset = None
    if eval_examples:
        eval_dataset = Dataset.from_list(eval_examples).map(
            tokenize_batch,
            batched=True,
            remove_columns=["prompt", "target", "text"],
        )

    model = AutoModelForCausalLM.from_pretrained(args.base_model)
    target_modules = _resolve_target_modules(model, [str(item) for item in args.target_module])
    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=target_modules,
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trainer = Trainer(
        model=model,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        processing_class=tokenizer,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
        args=TrainingArguments(
            output_dir=str(output_dir),
            learning_rate=args.learning_rate,
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accumulation,
            num_train_epochs=args.epochs,
            logging_steps=5,
            eval_strategy=args.eval_strategy,
            save_strategy=args.save_strategy,
            save_total_limit=2,
            report_to=[],
            fp16=False,
            optim="adamw_torch",
            use_cpu=use_cpu,
            dataloader_pin_memory=not use_cpu,
            remove_unused_columns=False,
            seed=args.seed,
        ),
    )

    train_result = trainer.train()
    eval_metrics = trainer.evaluate() if eval_dataset is not None and args.eval_strategy != "no" else {}
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    (output_dir / "training_manifest.json").write_text(
        json.dumps(
            {
                "base_model": args.base_model,
                "train_files": [str(path) for path in train_paths],
                "eval_file": str(eval_path),
                "epochs": args.epochs,
                "learning_rate": args.learning_rate,
                "batch_size": args.batch_size,
                "gradient_accumulation_steps": args.grad_accumulation,
                "max_length": args.max_length,
                "train_examples": len(train_examples),
                "eval_examples": len(eval_examples),
                "target_modules": target_modules,
                "train_metrics": train_result.metrics,
                "eval_metrics": eval_metrics,
                "lora": {
                    "r": args.lora_r,
                    "alpha": args.lora_alpha,
                    "dropout": args.lora_dropout,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
