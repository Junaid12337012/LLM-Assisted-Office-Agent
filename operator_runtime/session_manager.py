from __future__ import annotations

from typing import Any

from operator_runtime.checkpoint_manager import CheckpointManager
from operator_runtime.exception_queue import OperatorExceptionQueue
from operator_runtime.summary_manager import SummaryManager
from operator_runtime.task_queue import TaskQueue


class SessionManager:
    def __init__(
        self,
        memory_store: Any,
        task_queue: TaskQueue,
        checkpoint_manager: CheckpointManager,
        exception_queue: OperatorExceptionQueue,
        summary_manager: SummaryManager,
        registry: Any,
        engine: Any,
        assistant: Any | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.task_queue = task_queue
        self.checkpoint_manager = checkpoint_manager
        self.exception_queue = exception_queue
        self.summary_manager = summary_manager
        self.registry = registry
        self.engine = engine
        self.assistant = assistant

    def create_session(
        self,
        name: str,
        tasks: list[dict[str, Any]],
        *,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = self.memory_store.create_operator_session(
            name,
            status="pending",
            source=source,
            metadata=metadata or {},
            summary={},
        )
        for index, task in enumerate(tasks, start=1):
            self.task_queue.create_task(
                session_id,
                position=index,
                title=task.get("title") or task["command_name"],
                command_name=task["command_name"],
                workflow_id=task["workflow_id"],
                inputs=task.get("inputs") or {},
                priority=task.get("priority", "normal"),
                max_retries=int(task.get("max_retries", 1)),
                requires_confirmation=bool(task.get("requires_confirmation", False)),
            )
        self.checkpoint_manager.save(
            session_id,
            "session_created",
            {"task_count": len(tasks), "source": source},
        )
        return self.get_session_details(session_id)

    def create_session_from_instruction(
        self,
        instruction: str,
        *,
        session_name: str | None = None,
    ) -> dict[str, Any]:
        if self.assistant is None:
            raise ValueError("Assistant planner is not available.")
        plan = self.assistant.plan(instruction)
        if plan.status in {"unmatched", "needs_clarification"}:
            raise ValueError(plan.explanation)
        tasks = [
            {
                "title": planned.reason or planned.command_name,
                "command_name": planned.command_name,
                "workflow_id": planned.workflow_id,
                "inputs": planned.inputs,
                "priority": "normal",
                "max_retries": 1,
                "requires_confirmation": planned.requires_confirmation,
            }
            for planned in plan.commands
        ]
        session_title = session_name or self._derive_session_name(instruction)
        created = self.create_session(
            session_title,
            tasks,
            source="instruction",
            metadata={
                "instruction": instruction,
                "plan": plan.to_dict(),
            },
        )
        return {"session": created["session"], "tasks": created["tasks"], "plan": plan.to_dict(), "exceptions": []}

    def list_sessions(self, *, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        return self.memory_store.list_operator_sessions(limit=limit, status=status)

    def get_session_details(self, session_id: int) -> dict[str, Any]:
        session = self.memory_store.get_operator_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} was not found.")
        tasks = self.memory_store.list_operator_tasks(session_id)
        exceptions = self.exception_queue.list(session_id=session_id, status="all", limit=100)
        latest_checkpoint = self.checkpoint_manager.latest(session_id)
        summary = self.summary_manager.build(
            session,
            tasks,
            exceptions,
            latest_checkpoint=latest_checkpoint,
        )
        self.memory_store.update_operator_session(session_id, summary=summary)
        refreshed = self.memory_store.get_operator_session(session_id)
        return {
            "session": refreshed,
            "tasks": tasks,
            "exceptions": exceptions,
            "checkpoints": self.checkpoint_manager.history(session_id),
            "summary": summary,
            "summary_text": self.summary_manager.render_text(summary),
        }

    def pause_session(self, session_id: int) -> dict[str, Any]:
        self.memory_store.update_operator_session(session_id, status="paused")
        self.checkpoint_manager.save(session_id, "session_paused", {})
        return self.get_session_details(session_id)

    def resolve_exception(self, exception_id: int, *, resolution: str, notes: str | None = None) -> dict[str, Any]:
        item = self.exception_queue.resolve(exception_id, resolution=resolution, notes=notes)
        if item is None:
            raise ValueError(f"Exception {exception_id} was not found.")
        if item["task_id"] is not None and resolution in {"approved", "retry", "requeue"}:
            self.memory_store.update_operator_task(
                item["task_id"],
                status="pending",
                blocked_reason="",
                last_error="",
            )
            self.checkpoint_manager.save(
                item["session_id"],
                "exception_resolved",
                {"exception_id": exception_id, "resolution": resolution},
                task_id=item["task_id"],
            )
            self._refresh_session_state(item["session_id"])
        return item

    def run_next_task(
        self,
        session_id: int,
        *,
        safe_mode: bool = False,
        confirm_risky: bool = False,
        confirm_plan: bool = False,
    ) -> dict[str, Any]:
        next_task = self.task_queue.get_next_task(session_id)
        if next_task is None:
            details = self.get_session_details(session_id)
            return {"status": "idle", "session": details["session"], "summary": details["summary"]}

        self.memory_store.update_operator_session(session_id, status="running")
        self.checkpoint_manager.save(
            session_id,
            "before_task",
            {"task_id": next_task["id"], "command_name": next_task["command_name"]},
            task_id=next_task["id"],
        )

        if next_task["requires_confirmation"] and not (confirm_risky or confirm_plan):
            message = f"{next_task['command_name']} requires approval before it can run."
            self.memory_store.update_operator_task(
                next_task["id"],
                status="blocked",
                blocked_reason="approval_required",
                last_error=message,
            )
            exception_id = self.exception_queue.create(
                session_id,
                task_id=next_task["id"],
                kind="approval_required",
                message=message,
                details={"command_name": next_task["command_name"]},
            )
            self.checkpoint_manager.save(
                session_id,
                "task_blocked",
                {"task_id": next_task["id"], "exception_id": exception_id},
                task_id=next_task["id"],
            )
            details = self._refresh_session_state(session_id)
            return {
                "status": "blocked",
                "task": self.memory_store.get_operator_task(next_task["id"]),
                "exception": self.memory_store.get_operator_exception(exception_id),
                "session": details["session"],
                "summary": details["summary"],
            }

        self.memory_store.update_operator_task(next_task["id"], status="running", blocked_reason="", last_error="")
        command = self.registry.get(next_task["command_name"])
        confirmation_handler = (lambda _message: True) if (confirm_risky or confirm_plan) else None
        outcome = self.engine.run(
            command,
            next_task["inputs"],
            safe_mode=safe_mode,
            confirmation_handler=confirmation_handler,
        )
        result_status = "completed"
        exception_payload: dict[str, Any] | None = None

        if outcome.status in {"completed", "stopped"}:
            self.memory_store.update_operator_task(
                next_task["id"],
                status="completed",
                run_id=outcome.run_id,
                last_error="",
                completed=True,
            )
        elif outcome.status == "needs_review":
            self.memory_store.update_operator_task(
                next_task["id"],
                status="needs_review",
                run_id=outcome.run_id,
                last_error=outcome.last_error or "Task requires manual review.",
                blocked_reason="needs_review",
            )
            exception_id = self.exception_queue.create(
                session_id,
                task_id=next_task["id"],
                kind="needs_review",
                message=outcome.last_error or "Task requires manual review.",
                details={"run_id": outcome.run_id, "summary": outcome.summary},
            )
            exception_payload = self.memory_store.get_operator_exception(exception_id)
            result_status = "needs_review"
        else:
            retry_count = next_task["retries"] + 1
            if retry_count <= next_task["max_retries"]:
                self.memory_store.update_operator_task(
                    next_task["id"],
                    status="retry",
                    retries=retry_count,
                    run_id=outcome.run_id,
                    last_error=outcome.last_error or f"{next_task['command_name']} failed.",
                )
                result_status = "retry"
            else:
                message = outcome.last_error or f"{next_task['command_name']} failed after retries."
                self.memory_store.update_operator_task(
                    next_task["id"],
                    status="blocked",
                    retries=retry_count,
                    run_id=outcome.run_id,
                    last_error=message,
                    blocked_reason="task_failed",
                )
                exception_id = self.exception_queue.create(
                    session_id,
                    task_id=next_task["id"],
                    kind="task_failed",
                    message=message,
                    details={"run_id": outcome.run_id, "summary": outcome.summary},
                )
                exception_payload = self.memory_store.get_operator_exception(exception_id)
                result_status = "failed"

        self.checkpoint_manager.save(
            session_id,
            "after_task",
            {"task_id": next_task["id"], "result_status": result_status, "run_id": outcome.run_id},
            task_id=next_task["id"],
        )
        details = self._refresh_session_state(session_id)
        return {
            "status": result_status,
            "task": self.memory_store.get_operator_task(next_task["id"]),
            "run_id": outcome.run_id,
            "exception": exception_payload,
            "session": details["session"],
            "summary": details["summary"],
        }

    def run_session(
        self,
        session_id: int,
        *,
        safe_mode: bool = False,
        confirm_risky: bool = False,
        confirm_plan: bool = False,
        max_tasks: int | None = None,
    ) -> dict[str, Any]:
        executions: list[dict[str, Any]] = []
        processed = 0
        while max_tasks is None or processed < max_tasks:
            current = self.task_queue.get_next_task(session_id)
            if current is None:
                break
            result = self.run_next_task(
                session_id,
                safe_mode=safe_mode,
                confirm_risky=confirm_risky,
                confirm_plan=confirm_plan,
            )
            executions.append(result)
            processed += 1
        details = self._refresh_session_state(session_id)
        return {
            "session": details["session"],
            "tasks": details["tasks"],
            "exceptions": details["exceptions"],
            "checkpoints": details["checkpoints"],
            "summary": details["summary"],
            "summary_text": details["summary_text"],
            "executions": executions,
        }

    def dashboard(self, *, limit: int = 10) -> dict[str, Any]:
        return self.memory_store.operator_dashboard_snapshot(limit=limit)

    def _refresh_session_state(self, session_id: int) -> dict[str, Any]:
        session = self.memory_store.get_operator_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} was not found.")
        tasks = self.memory_store.list_operator_tasks(session_id)
        exceptions = self.exception_queue.list(session_id=session_id, status="all", limit=100)
        counts: dict[str, int] = {}
        for task in tasks:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        pending = counts.get("pending", 0) + counts.get("retry", 0)
        running = counts.get("running", 0)
        blocked = counts.get("blocked", 0) + counts.get("needs_review", 0)
        failed = counts.get("failed", 0)
        completed = counts.get("completed", 0)
        total = len(tasks)

        if running > 0:
            next_status = "running"
        elif total > 0 and completed == total:
            next_status = "completed"
        elif pending > 0:
            next_status = "pending"
        elif blocked > 0 and completed > 0:
            next_status = "partial"
        elif blocked > 0:
            next_status = "blocked"
        elif failed > 0 and completed > 0:
            next_status = "partial"
        elif failed > 0:
            next_status = "failed"
        else:
            next_status = session["status"]

        latest_checkpoint = self.checkpoint_manager.latest(session_id)
        summary = self.summary_manager.build(
            {**session, "status": next_status},
            tasks,
            exceptions,
            latest_checkpoint=latest_checkpoint,
        )
        finish = next_status in {"completed", "partial", "failed"}
        self.memory_store.update_operator_session(session_id, status=next_status, summary=summary, finish=finish)
        return self.get_session_details(session_id)

    @staticmethod
    def _derive_session_name(instruction: str) -> str:
        words = " ".join(instruction.strip().split())
        if len(words) <= 48:
            return words
        return words[:45] + "..."
