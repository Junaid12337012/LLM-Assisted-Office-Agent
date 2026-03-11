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
                (
                    run_id,
                    step_id,
                    status,
                    message,
                    json.dumps(payload or {}),
                    utc_now_iso(),
                ),
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

    def finish_run(
        self,
        run_id: int,
        status: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
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
        return {
            "date": run_date,
            "total_runs": sum(status_counts.values()),
            "status_counts": status_counts,
        }

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
