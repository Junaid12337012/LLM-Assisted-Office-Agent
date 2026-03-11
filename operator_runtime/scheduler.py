from __future__ import annotations


_PRIORITY_ORDER = {
    "high": 0,
    "urgent": 0,
    "normal": 1,
    "medium": 1,
    "low": 2,
}


def sort_tasks(tasks: list[dict]) -> list[dict]:
    return sorted(
        tasks,
        key=lambda task: (
            _PRIORITY_ORDER.get(str(task.get("priority", "normal")).lower(), 1),
            int(task.get("position", 0)),
            int(task.get("id", 0)),
        ),
    )
