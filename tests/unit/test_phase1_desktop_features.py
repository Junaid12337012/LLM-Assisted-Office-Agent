from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.memory import MemoryStore
from desktop_backend import _extract_artifacts


class MemoryStorePhaseOneFeatureTests(unittest.TestCase):
    def test_list_runs_supports_status_and_query_filters(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir) / "memory.db")
            completed_run = store.create_run("mvp.start_day", "mvp_start_day", {"note_path": "data/evidence/notes/start.md"})
            failed_run = store.create_run("desktop.demo_notepad", "demo_notepad", {"note_path": "data/evidence/notes/demo.txt"})
            store.finish_run(completed_run, "completed", {"workflow_id": "mvp_start_day"})
            store.finish_run(failed_run, "failed", {"error": "launch failed"})

            failed_runs = store.list_runs(limit=10, status="failed")
            self.assertEqual(1, len(failed_runs))
            self.assertEqual("desktop.demo_notepad", failed_runs[0]["command_name"])

            queried_runs = store.list_runs(limit=10, query="start")
            self.assertEqual(1, len(queried_runs))
            self.assertEqual("mvp.start_day", queried_runs[0]["command_name"])

    def test_dashboard_snapshot_reports_recent_status_counts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = MemoryStore(Path(temp_dir) / "memory.db")
            run_one = store.create_run("mvp.start_day", "mvp_start_day", {})
            run_two = store.create_run("mvp.end_day", "mvp_end_day", {})
            store.finish_run(run_one, "completed", {"workflow_id": "mvp_start_day"})
            store.finish_run(run_two, "failed", {"error": "summary failed"})

            snapshot = store.dashboard_snapshot(limit=10)

            self.assertEqual(2, snapshot["total_runs"])
            self.assertEqual(1, snapshot["status_counts"]["completed"])
            self.assertEqual(1, snapshot["status_counts"]["failed"])
            self.assertEqual("mvp.end_day", snapshot["latest_run"]["command_name"])
            self.assertEqual(1, len(snapshot["failed_runs"]))


class DesktopBackendArtifactTests(unittest.TestCase):
    def test_extract_artifacts_returns_existing_files_and_folders(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            note_path = root / "data" / "evidence" / "notes" / "artifact.txt"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text("artifact", encoding="utf-8")

            steps = [
                {
                    "step_id": "write_note",
                    "payload": {
                        "data": {"written_path": "data/evidence/notes/artifact.txt"},
                        "args": {"path": "data/evidence/notes/artifact.txt"},
                        "observations": {},
                    },
                }
            ]

            artifacts = _extract_artifacts(root, steps)

            self.assertEqual(1, len(artifacts))
            self.assertTrue(artifacts[0]["exists"])
            self.assertEqual(str(note_path), artifacts[0]["path"])


if __name__ == "__main__":
    unittest.main()
