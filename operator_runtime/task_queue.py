from __future__ import annotations

from typing import Any

from operator_runtime.scheduler import sort_tasks


class TaskQueue:
    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    def create_task(self, session_id: int, **task_kwargs: Any) -> int:
        return self.memory_store.create_operator_task(session_id, **task_kwargs)

    def list_tasks(self, session_id: int, status: str | None = None) -> list[dict[str, Any]]:
        return self.memory_store.list_operator_tasks(session_id, status=status)

    def get_next_task(self, session_id: int) -> dict[str, Any] | None:
        tasks = self.list_tasks(session_id)
        runnable = [
            task
            for task in tasks
            if task["status"] in {"pending", "retry"}
        ]
        ordered = sort_tasks(runnable)
        return ordered[0] if ordered else None
