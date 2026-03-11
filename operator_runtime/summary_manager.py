from __future__ import annotations

from typing import Any


class SummaryManager:
    def build(
        self,
        session: dict[str, Any],
        tasks: list[dict[str, Any]],
        exceptions: list[dict[str, Any]],
        *,
        latest_checkpoint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        for task in tasks:
            status_counts[task["status"]] = status_counts.get(task["status"], 0) + 1
        completed = status_counts.get("completed", 0)
        blocked = status_counts.get("blocked", 0) + status_counts.get("needs_review", 0)
        pending = status_counts.get("pending", 0) + status_counts.get("retry", 0)
        failed = status_counts.get("failed", 0)
        return {
            "session_name": session["name"],
            "session_status": session["status"],
            "total_tasks": len(tasks),
            "completed_tasks": completed,
            "pending_tasks": pending,
            "blocked_tasks": blocked,
            "failed_tasks": failed,
            "open_exceptions": len([item for item in exceptions if item["status"] == "open"]),
            "latest_checkpoint": latest_checkpoint,
            "status_counts": status_counts,
        }

    def render_text(self, summary: dict[str, Any]) -> str:
        checkpoint_text = "none"
        latest_checkpoint = summary.get("latest_checkpoint")
        if latest_checkpoint:
            checkpoint_text = f"{latest_checkpoint['checkpoint_key']} @ {latest_checkpoint['created_at']}"
        return (
            f"Session: {summary['session_name']}\n"
            f"Status: {summary['session_status']}\n"
            f"Completed: {summary['completed_tasks']} / {summary['total_tasks']}\n"
            f"Pending: {summary['pending_tasks']}\n"
            f"Blocked: {summary['blocked_tasks']}\n"
            f"Failed: {summary['failed_tasks']}\n"
            f"Open exceptions: {summary['open_exceptions']}\n"
            f"Latest checkpoint: {checkpoint_text}"
        )
