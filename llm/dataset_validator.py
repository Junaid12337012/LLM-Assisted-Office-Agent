from __future__ import annotations

import json
from pathlib import Path


def validate_jsonl_file(path: str | Path) -> list[str]:
    errors: list[str] = []
    target = Path(path)
    if not target.exists():
        return [f"Dataset file was not found: {target}"]

    for line_number, raw_line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            errors.append(f"{target.name}:{line_number} invalid JSON: {exc.msg}")
            continue
        errors.extend(_validate_record(record, target.name, line_number))
    return errors


def _validate_record(record: object, filename: str, line_number: int) -> list[str]:
    prefix = f"{filename}:{line_number}"
    errors: list[str] = []
    if not isinstance(record, dict):
        return [f"{prefix} record must be an object."]

    messages = record.get("messages")
    if not isinstance(messages, list) or not messages:
        errors.append(f"{prefix} messages must be a non-empty list.")
    else:
        for index, message in enumerate(messages, start=1):
            if not isinstance(message, dict):
                errors.append(f"{prefix} message {index} must be an object.")
                continue
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant", "tool"}:
                errors.append(f"{prefix} message {index} has an unsupported role '{role}'.")
            if not isinstance(content, str) or not content.strip():
                errors.append(f"{prefix} message {index} must include non-empty string content.")

    expected_plan = record.get("expected_plan")
    if not isinstance(expected_plan, dict):
        errors.append(f"{prefix} expected_plan must be an object.")
    else:
        if not isinstance(expected_plan.get("commands"), list):
            errors.append(f"{prefix} expected_plan.commands must be a list.")
        if not isinstance(expected_plan.get("status"), str):
            errors.append(f"{prefix} expected_plan.status must be a string.")

    if "screen_context" in record and not isinstance(record.get("screen_context"), dict):
        errors.append(f"{prefix} screen_context must be an object when provided.")

    return errors


if __name__ == "__main__":
    import sys

    dataset_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("datasets/local_agent_train.jsonl")
    dataset_errors = validate_jsonl_file(dataset_path)
    if dataset_errors:
        print("\n".join(dataset_errors))
        raise SystemExit(1)
    print(f"dataset-ok: {dataset_path}")
