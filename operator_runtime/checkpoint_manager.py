from __future__ import annotations

from typing import Any


class CheckpointManager:
    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    def save(
        self,
        session_id: int,
        checkpoint_key: str,
        payload: dict[str, Any] | None = None,
        *,
        task_id: int | None = None,
    ) -> int:
        return self.memory_store.create_operator_checkpoint(
            session_id,
            checkpoint_key=checkpoint_key,
            payload=payload,
            task_id=task_id,
        )

    def latest(self, session_id: int, *, task_id: int | None = None) -> dict[str, Any] | None:
        return self.memory_store.get_latest_operator_checkpoint(session_id, task_id=task_id)

    def history(self, session_id: int, *, task_id: int | None = None) -> list[dict[str, Any]]:
        return self.memory_store.list_operator_checkpoints(session_id, task_id=task_id)
