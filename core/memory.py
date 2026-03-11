from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Any

from core.utils import ensure_parent, utc_now_iso


class MemoryStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = ensure_parent(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_name TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    summary_json TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS step_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs (id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs (id)
                );

                CREATE TABLE IF NOT EXISTS review_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    suggested_value TEXT,
                    corrected_value TEXT,
                    evidence_path TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs (id)
                );

                CREATE TABLE IF NOT EXISTS operator_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operator_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    command_name TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    retries INTEGER NOT NULL,
                    max_retries INTEGER NOT NULL,
                    run_id INTEGER,
                    last_error TEXT,
                    blocked_reason TEXT,
                    requires_confirmation INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES operator_sessions (id),
                    FOREIGN KEY (run_id) REFERENCES runs (id)
                );

                CREATE TABLE IF NOT EXISTS operator_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    task_id INTEGER,
                    checkpoint_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES operator_sessions (id),
                    FOREIGN KEY (task_id) REFERENCES operator_tasks (id)
                );

                CREATE TABLE IF NOT EXISTS operator_exceptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    task_id INTEGER,
                    status TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES operator_sessions (id),
                    FOREIGN KEY (task_id) REFERENCES operator_tasks (id)
                );
                """
            )
            connection.commit()

    def create_run(self, command_name: str, workflow_id: str, inputs: dict[str, Any]) -> int:
        started_at = utc_now_iso()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO runs (command_name, workflow_id, status, inputs_json, started_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (command_name, workflow_id, "running", json.dumps(inputs), started_at),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def log_step(
        self,
        run_id: int,
        step_id: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO step_logs (run_id, step_id, status, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, step_id, status, message, json.dumps(payload or {}), utc_now_iso()),
            )
            connection.commit()

    def log_event(
        self,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO events (run_id, level, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, level, message, json.dumps(payload or {}), utc_now_iso()),
            )
            connection.commit()

    def finish_run(self, run_id: int, status: str, summary: dict[str, Any] | None = None) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, summary_json = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(summary or {}), utc_now_iso(), run_id),
            )
            connection.commit()

    def list_runs(
        self,
        limit: int = 20,
        status: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status and status.lower() != "all":
            clauses.append("status = ?")
            params.append(status)
        if query:
            like_value = f"%{query}%"
            clauses.append("(command_name LIKE ? OR workflow_id LIKE ? OR inputs_json LIKE ? OR summary_json LIKE ?)")
            params.extend([like_value, like_value, like_value, like_value])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, command_name, workflow_id, status, inputs_json, summary_json, started_at, finished_at
                FROM runs
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._serialize_run_row(row) for row in rows]

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, command_name, workflow_id, status, inputs_json, summary_json, started_at, finished_at
                FROM runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._serialize_run_row(row) if row is not None else None

    def list_step_logs(self, run_id: int) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, run_id, step_id, status, message, payload_json, created_at
                FROM step_logs
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "run_id": int(row["run_id"]),
                "step_id": row["step_id"],
                "status": row["status"],
                "message": row["message"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def summary_for_date(self, run_date: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*)
                FROM runs
                WHERE started_at LIKE ?
                GROUP BY status
                """,
                (f"{run_date}%",),
            ).fetchall()
        status_counts = {row[0]: row[1] for row in rows}
        return {"date": run_date, "total_runs": sum(status_counts.values()), "status_counts": status_counts}

    def dashboard_snapshot(self, limit: int = 30) -> dict[str, Any]:
        runs = self.list_runs(limit=limit)
        status_counts: dict[str, int] = {}
        for run in runs:
            status_counts[run["status"]] = status_counts.get(run["status"], 0) + 1
        latest_run = runs[0] if runs else None
        failed_runs = [run for run in runs if run["status"] == "failed"]
        return {
            "total_runs": len(runs),
            "status_counts": status_counts,
            "latest_run": latest_run,
            "failed_runs": failed_runs[:5],
        }

    def create_review_item(
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
        timestamp = utc_now_iso()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO review_queue (
                    run_id, workflow_id, step_id, status, reason, suggested_value,
                    corrected_value, evidence_path, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    step_id,
                    "pending",
                    reason,
                    suggested_value,
                    corrected_value,
                    evidence_path,
                    json.dumps(metadata or {}),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_review_items(self, status: str = "pending", limit: int = 50) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if status and status.lower() != "all":
            clauses.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, run_id, workflow_id, step_id, status, reason, suggested_value,
                       corrected_value, evidence_path, metadata_json, created_at, updated_at
                FROM review_queue
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._serialize_review_row(row) for row in rows]

    def resolve_review_item(
        self,
        review_id: int,
        resolution: str,
        corrected_value: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM review_queue WHERE id = ?",
                (review_id,),
            ).fetchone()
            if row is None:
                return None
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata["resolution_notes"] = notes or ""
            connection.execute(
                """
                UPDATE review_queue
                SET status = ?, corrected_value = ?, updated_at = ?, metadata_json = ?
                WHERE id = ?
                """,
                (resolution, corrected_value, utc_now_iso(), json.dumps(metadata), review_id),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, run_id, workflow_id, step_id, status, reason, suggested_value,
                       corrected_value, evidence_path, metadata_json, created_at, updated_at
                FROM review_queue
                WHERE id = ?
                """,
                (review_id,),
            ).fetchone()
        return self._serialize_review_row(row) if row is not None else None

    def create_operator_session(
        self,
        name: str,
        *,
        status: str = "pending",
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
    ) -> int:
        timestamp = utc_now_iso()
        started_at = timestamp if status == "running" else None
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO operator_sessions (
                    name, status, source, metadata_json, summary_json, created_at, started_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    status,
                    source,
                    json.dumps(metadata or {}),
                    json.dumps(summary or {}),
                    timestamp,
                    started_at,
                    timestamp,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_operator_sessions(self, *, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_sql = ""
        if status and status.lower() != "all":
            where_sql = "WHERE status = ?"
            params.append(status)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, name, status, source, metadata_json, summary_json, created_at, started_at, finished_at, updated_at
                FROM operator_sessions
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._serialize_operator_session(row) for row in rows]

    def get_operator_session(self, session_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, name, status, source, metadata_json, summary_json, created_at, started_at, finished_at, updated_at
                FROM operator_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        return self._serialize_operator_session(row) if row is not None else None

    def update_operator_session(
        self,
        session_id: int,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
        finish: bool = False,
    ) -> dict[str, Any] | None:
        current = self.get_operator_session(session_id)
        if current is None:
            return None
        next_status = status or current["status"]
        next_metadata = dict(current["metadata"])
        if metadata:
            next_metadata.update(metadata)
        next_summary = dict(current["summary"])
        if summary:
            next_summary.update(summary)
        timestamp = utc_now_iso()
        started_at = current["started_at"] or (timestamp if next_status == "running" else None)
        finished_at = timestamp if finish else current["finished_at"]
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE operator_sessions
                SET status = ?, metadata_json = ?, summary_json = ?, started_at = ?, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_status,
                    json.dumps(next_metadata),
                    json.dumps(next_summary),
                    started_at,
                    finished_at,
                    timestamp,
                    session_id,
                ),
            )
            connection.commit()
        return self.get_operator_session(session_id)

    def create_operator_task(
        self,
        session_id: int,
        *,
        position: int,
        title: str,
        command_name: str,
        workflow_id: str,
        inputs: dict[str, Any] | None = None,
        priority: str = "normal",
        max_retries: int = 1,
        requires_confirmation: bool = False,
    ) -> int:
        timestamp = utc_now_iso()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO operator_tasks (
                    session_id, position, title, command_name, workflow_id, status, priority,
                    inputs_json, retries, max_retries, requires_confirmation, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    position,
                    title,
                    command_name,
                    workflow_id,
                    "pending",
                    priority,
                    json.dumps(inputs or {}),
                    0,
                    max_retries,
                    1 if requires_confirmation else 0,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_operator_tasks(
        self,
        session_id: int,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [session_id]
        where_sql = "WHERE session_id = ?"
        if status and status.lower() != "all":
            where_sql += " AND status = ?"
            params.append(status)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, session_id, position, title, command_name, workflow_id, status, priority,
                       inputs_json, retries, max_retries, run_id, last_error, blocked_reason,
                       requires_confirmation, created_at, updated_at, completed_at
                FROM operator_tasks
                {where_sql}
                ORDER BY position ASC, id ASC
                """,
                params,
            ).fetchall()
        return [self._serialize_operator_task(row) for row in rows]

    def get_operator_task(self, task_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, session_id, position, title, command_name, workflow_id, status, priority,
                       inputs_json, retries, max_retries, run_id, last_error, blocked_reason,
                       requires_confirmation, created_at, updated_at, completed_at
                FROM operator_tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        return self._serialize_operator_task(row) if row is not None else None

    def update_operator_task(
        self,
        task_id: int,
        *,
        status: str | None = None,
        inputs: dict[str, Any] | None = None,
        retries: int | None = None,
        run_id: int | None = None,
        last_error: str | None = None,
        blocked_reason: str | None = None,
        completed: bool = False,
    ) -> dict[str, Any] | None:
        current = self.get_operator_task(task_id)
        if current is None:
            return None
        timestamp = utc_now_iso()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE operator_tasks
                SET status = ?, inputs_json = ?, retries = ?, run_id = ?, last_error = ?, blocked_reason = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status or current["status"],
                    json.dumps(inputs if inputs is not None else current["inputs"]),
                    current["retries"] if retries is None else retries,
                    run_id if run_id is not None else current["run_id"],
                    last_error if last_error is not None else current["last_error"],
                    blocked_reason if blocked_reason is not None else current["blocked_reason"],
                    timestamp,
                    timestamp if completed else current["completed_at"],
                    task_id,
                ),
            )
            connection.commit()
        return self.get_operator_task(task_id)

    def create_operator_checkpoint(
        self,
        session_id: int,
        *,
        checkpoint_key: str,
        payload: dict[str, Any] | None = None,
        task_id: int | None = None,
    ) -> int:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO operator_checkpoints (session_id, task_id, checkpoint_key, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, task_id, checkpoint_key, json.dumps(payload or {}), utc_now_iso()),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_operator_checkpoints(
        self,
        session_id: int,
        *,
        task_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [session_id]
        where_sql = "WHERE session_id = ?"
        if task_id is not None:
            where_sql += " AND task_id = ?"
            params.append(task_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, session_id, task_id, checkpoint_key, payload_json, created_at
                FROM operator_checkpoints
                {where_sql}
                ORDER BY id DESC
                """,
                params,
            ).fetchall()
        return [self._serialize_operator_checkpoint(row) for row in rows]

    def get_latest_operator_checkpoint(
        self,
        session_id: int,
        *,
        task_id: int | None = None,
    ) -> dict[str, Any] | None:
        items = self.list_operator_checkpoints(session_id, task_id=task_id)
        return items[0] if items else None

    def create_operator_exception(
        self,
        session_id: int,
        *,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        task_id: int | None = None,
        status: str = "open",
    ) -> int:
        timestamp = utc_now_iso()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO operator_exceptions (
                    session_id, task_id, status, kind, message, details_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    status,
                    kind,
                    message,
                    json.dumps(details or {}),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_operator_exceptions(
        self,
        *,
        session_id: int | None = None,
        status: str | None = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status and status.lower() != "all":
            clauses.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, session_id, task_id, status, kind, message, details_json, created_at, updated_at
                FROM operator_exceptions
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._serialize_operator_exception(row) for row in rows]

    def get_operator_exception(self, exception_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, session_id, task_id, status, kind, message, details_json, created_at, updated_at
                FROM operator_exceptions
                WHERE id = ?
                """,
                (exception_id,),
            ).fetchone()
        return self._serialize_operator_exception(row) if row is not None else None

    def resolve_operator_exception(
        self,
        exception_id: int,
        *,
        resolution: str,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_operator_exception(exception_id)
        if current is None:
            return None
        details = dict(current["details"])
        details["resolution"] = resolution
        details["resolution_notes"] = notes or ""
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE operator_exceptions
                SET status = ?, details_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (resolution, json.dumps(details), utc_now_iso(), exception_id),
            )
            connection.commit()
        return self.get_operator_exception(exception_id)

    def operator_dashboard_snapshot(self, *, limit: int = 10) -> dict[str, Any]:
        sessions = self.list_operator_sessions(limit=limit)
        open_exceptions = self.list_operator_exceptions(status="open", limit=limit)
        active_session = next(
            (
                session
                for session in sessions
                if session["status"] in {"pending", "running", "paused", "blocked"}
            ),
            None,
        )
        blocked_tasks: list[dict[str, Any]] = []
        if active_session is not None:
            blocked_tasks = [
                task
                for task in self.list_operator_tasks(active_session["id"])
                if task["status"] in {"blocked", "needs_review"}
            ][:5]
        return {
            "sessions": sessions,
            "active_session": active_session,
            "open_exceptions": open_exceptions,
            "open_exception_count": len(open_exceptions),
            "blocked_tasks": blocked_tasks,
        }

    @staticmethod
    def _serialize_run_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "command_name": row["command_name"],
            "workflow_id": row["workflow_id"],
            "status": row["status"],
            "inputs": json.loads(row["inputs_json"] or "{}"),
            "summary": json.loads(row["summary_json"] or "{}"),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _serialize_review_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
            "workflow_id": row["workflow_id"],
            "step_id": row["step_id"],
            "status": row["status"],
            "reason": row["reason"],
            "suggested_value": row["suggested_value"],
            "corrected_value": row["corrected_value"],
            "evidence_path": row["evidence_path"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _serialize_operator_session(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "status": row["status"],
            "source": row["source"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "summary": json.loads(row["summary_json"] or "{}"),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _serialize_operator_task(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_id": int(row["session_id"]),
            "position": int(row["position"]),
            "title": row["title"],
            "command_name": row["command_name"],
            "workflow_id": row["workflow_id"],
            "status": row["status"],
            "priority": row["priority"],
            "inputs": json.loads(row["inputs_json"] or "{}"),
            "retries": int(row["retries"]),
            "max_retries": int(row["max_retries"]),
            "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
            "last_error": row["last_error"],
            "blocked_reason": row["blocked_reason"],
            "requires_confirmation": bool(row["requires_confirmation"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    @staticmethod
    def _serialize_operator_checkpoint(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_id": int(row["session_id"]),
            "task_id": int(row["task_id"]) if row["task_id"] is not None else None,
            "checkpoint_key": row["checkpoint_key"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _serialize_operator_exception(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_id": int(row["session_id"]),
            "task_id": int(row["task_id"]) if row["task_id"] is not None else None,
            "status": row["status"],
            "kind": row["kind"],
            "message": row["message"],
            "details": json.loads(row["details_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
