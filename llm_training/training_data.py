from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.utils import ensure_parent, utc_now_iso

SYSTEM_MESSAGE = "Plan approved desktop commands only."


def build_training_record(
    instruction: str,
    approved_plan: dict[str, Any],
    *,
    screen_context: dict[str, Any] | None = None,
    source_plan: dict[str, Any] | None = None,
    notes: str = "",
    origin: str = "manual",
) -> dict[str, Any]:
    normalized_instruction = instruction.strip()
    minimal_plan = minimal_expected_plan(approved_plan)
    record = {
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": normalized_instruction},
        ],
        "screen_context": dict(screen_context or {}),
        "expected_plan": minimal_plan,
        "metadata": {
            "captured_at": utc_now_iso(),
            "origin": origin,
            "notes": notes,
            "instruction": normalized_instruction,
        },
    }
    if source_plan is not None:
        record["metadata"]["source_plan"] = source_plan
    record["metadata"]["record_id"] = record_id_for(record)
    return record


def minimal_expected_plan(plan_like: dict[str, Any]) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    for item in plan_like.get("commands", []):
        if not isinstance(item, dict):
            continue
        command_name = item.get("command_name")
        if not command_name:
            continue
        commands.append(
            {
                "command_name": str(command_name),
                "inputs": dict(item.get("inputs") or {}),
            }
        )
    return {
        "status": str(plan_like.get("status") or "ready"),
        "commands": commands,
    }


def canonical_record_json(record: dict[str, Any]) -> str:
    canonical = {
        "messages": record.get("messages", []),
        "screen_context": record.get("screen_context", {}),
        "expected_plan": record.get("expected_plan", {}),
    }
    return json.dumps(canonical, ensure_ascii=True, sort_keys=True)


def record_id_for(record: dict[str, Any]) -> str:
    digest = hashlib.sha1(canonical_record_json(record).encode("utf-8")).hexdigest()
    return digest[:16]


def append_jsonl_record(path: str | Path, record: dict[str, Any]) -> None:
    target = ensure_parent(path)
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True))
        handle.write("\n")


def read_jsonl_records(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        records.append(json.loads(raw_line))
    return records


def write_jsonl_records(path: str | Path, records: list[dict[str, Any]]) -> None:
    target = ensure_parent(path)
    with Path(target).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True))
            handle.write("\n")


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = record_id_for(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped
