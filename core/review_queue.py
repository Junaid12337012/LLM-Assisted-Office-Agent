from __future__ import annotations

from typing import Any


class ReviewQueue:
    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    def enqueue(
        self,
        workflow_id: str,
        step_id: str,
        reason: str,
        suggested_value: str | None = None,
        corrected_value: str | None = None,
        evidence_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> int:
        return self.memory_store.create_review_item(
            workflow_id=workflow_id,
            step_id=step_id,
            reason=reason,
            suggested_value=suggested_value,
            corrected_value=corrected_value,
            evidence_path=evidence_path,
            metadata=metadata,
            run_id=run_id,
        )

    def list_items(self, status: str = "pending", limit: int = 50) -> list[dict[str, Any]]:
        return self.memory_store.list_review_items(status=status, limit=limit)

    def resolve(
        self,
        review_id: int,
        resolution: str,
        corrected_value: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        return self.memory_store.resolve_review_item(
            review_id=review_id,
            resolution=resolution,
            corrected_value=corrected_value,
            notes=notes,
        )
