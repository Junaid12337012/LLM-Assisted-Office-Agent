from __future__ import annotations

from typing import Any


class OperatorExceptionQueue:
    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    def create(
        self,
        session_id: int,
        *,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        task_id: int | None = None,
        status: str = "open",
    ) -> int:
        return self.memory_store.create_operator_exception(
            session_id,
            kind=kind,
            message=message,
            details=details,
            task_id=task_id,
            status=status,
        )

    def list(
        self,
        *,
        session_id: int | None = None,
        status: str | None = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.memory_store.list_operator_exceptions(
            session_id=session_id,
            status=status,
            limit=limit,
        )

    def resolve(self, exception_id: int, *, resolution: str, notes: str | None = None) -> dict[str, Any] | None:
        return self.memory_store.resolve_operator_exception(
            exception_id,
            resolution=resolution,
            notes=notes,
        )
