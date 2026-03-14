from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_training.training_data import (
    append_jsonl_record,
    build_training_record,
    dedupe_records,
    read_jsonl_records,
    write_jsonl_records,
)


class FeedbackStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save_feedback(
        self,
        *,
        instruction: str,
        approved_plan: dict[str, Any],
        screen_context: dict[str, Any] | None = None,
        source_plan: dict[str, Any] | None = None,
        notes: str = "",
        origin: str = "manual",
    ) -> dict[str, Any]:
        record = build_training_record(
            instruction,
            approved_plan,
            screen_context=screen_context,
            source_plan=source_plan,
            notes=notes,
            origin=origin,
        )
        append_jsonl_record(self.path, record)
        return record

    def list_feedback(self, limit: int = 20) -> list[dict[str, Any]]:
        records = read_jsonl_records(self.path)
        if limit <= 0:
            return records
        return records[-limit:]

    def export_dataset(
        self,
        output_path: str | Path,
        *,
        base_files: list[str | Path] | None = None,
        dedupe: bool = True,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for base_file in base_files or []:
            records.extend(read_jsonl_records(base_file))
        records.extend(read_jsonl_records(self.path))
        if dedupe:
            records = dedupe_records(records)
        write_jsonl_records(output_path, records)
        return records
