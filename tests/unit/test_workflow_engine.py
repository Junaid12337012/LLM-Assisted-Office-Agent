from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.helpers import build_runtime


class WorkflowEngineTests(unittest.TestCase):
    def test_download_workflow_creates_export_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            command = runtime.registry.get("browser.download_daily_report")
            export_dir = temp_path / "exports"
            outcome = runtime.engine.run(
                command,
                {
                    "download_dir": str(temp_path / "downloads"),
                    "export_dir": str(export_dir),
                    "run_date": "2026-03-11",
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "completed")
            self.assertTrue((export_dir / "daily_report_2026-03-11.csv").exists())

    def test_notepad_demo_workflow_creates_demo_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            command = runtime.registry.get("desktop.demo_notepad")
            note_path = temp_path / "notepad_demo.txt"
            outcome = runtime.engine.run(
                command,
                {
                    "note_path": str(note_path),
                    "note_content": "Desktop demo note from test",
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "completed")
            self.assertTrue(note_path.exists())
            self.assertIn("Desktop demo note from test", note_path.read_text(encoding="utf-8"))

    def test_paint_demo_workflow_completes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            command = runtime.registry.get("desktop.demo_paint")
            outcome = runtime.engine.run(
                command,
                {
                    "paint_command": "mspaint.exe",
                    "paint_path": "C:/Windows/System32/mspaint.exe",
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "completed")

    def test_start_day_workflow_writes_daily_note(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            command = runtime.registry.get("mvp.start_day")
            note_path = temp_path / "start_day_2026-03-11.md"
            workspace_folder = temp_path / "workspace"
            workspace_folder.mkdir(parents=True, exist_ok=True)
            outcome = runtime.engine.run(
                command,
                {
                    "run_date": "2026-03-11",
                    "note_path": str(note_path),
                    "workspace_folder": str(workspace_folder),
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "completed")
            self.assertTrue(note_path.exists())
            self.assertIn("2026-03-11", note_path.read_text(encoding="utf-8"))

    def test_mvp_note_workflow_writes_note(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            command = runtime.registry.get("mvp.note")
            note_path = temp_path / "quick_note.txt"
            outcome = runtime.engine.run(
                command,
                {
                    "run_date": "2026-03-11",
                    "note_text": "Call the vendor before lunch",
                    "note_title": "Priority Note",
                    "note_path": str(note_path),
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "completed")
            self.assertTrue(note_path.exists())
            contents = note_path.read_text(encoding="utf-8")
            self.assertIn("Priority Note", contents)
            self.assertIn("Call the vendor before lunch", contents)

    def test_end_of_day_summary_exports_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            current_date = datetime.utcnow().date().isoformat()
            download_command = runtime.registry.get("browser.download_daily_report")
            runtime.engine.run(
                download_command,
                {
                    "download_dir": str(temp_path / "downloads"),
                    "export_dir": str(temp_path / "exports"),
                    "run_date": current_date,
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            summary_command = runtime.registry.get("reports.end_of_day_summary")
            summary_path = temp_path / "summary.json"
            summary_outcome = runtime.engine.run(
                summary_command,
                {"run_date": current_date, "export_path": str(summary_path)},
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(summary_outcome.status, "completed")
            self.assertTrue(summary_path.exists())

    def test_mvp_end_day_exports_and_opens_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            current_date = datetime.utcnow().date().isoformat()
            command = runtime.registry.get("mvp.end_day")
            summary_path = temp_path / "end_day.json"
            outcome = runtime.engine.run(
                command,
                {
                    "run_date": current_date,
                    "summary_output": str(summary_path),
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "completed")
            self.assertTrue(summary_path.exists())

    def test_phase2_invoice_workflow_extracts_invoice_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            image_path = temp_path / "invoice_input.txt"
            image_path.write_text("INV-2931", encoding="utf-8")
            result_path = temp_path / "invoice_result.txt"
            command = runtime.registry.get("phase2.read_invoice_id")
            outcome = runtime.engine.run(
                command,
                {
                    "image_path": str(image_path),
                    "result_path": str(result_path),
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "completed")
            self.assertTrue(result_path.exists())
            self.assertIn("INV-2931", result_path.read_text(encoding="utf-8"))

    def test_phase2_invoice_workflow_queues_manual_review_for_invalid_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            image_path = temp_path / "invoice_bad.txt"
            image_path.write_text("UNKNOWN", encoding="utf-8")
            command = runtime.registry.get("phase2.read_invoice_id")
            outcome = runtime.engine.run(
                command,
                {
                    "image_path": str(image_path),
                    "result_path": str(temp_path / "invoice_review.txt"),
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )
            self.assertEqual(outcome.status, "needs_review")
            self.assertIn("review_item_id", outcome.summary)
            items = runtime.review_queue.list_items(status="pending")
            self.assertEqual(1, len(items))
            self.assertEqual("phase2_read_invoice_id", items[0]["workflow_id"])
            self.assertTrue(items[0]["evidence_path"])

    def test_print_today_vouchers_workflow_runs_through_state_machine(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            command = runtime.registry.get("desktop.print_today_vouchers")

            outcome = runtime.engine.run(
                command,
                {
                    "app_name": "voucher_app",
                    "date_from": "today",
                    "date_to": "today",
                },
                safe_mode=False,
                confirmation_handler=lambda _message: True,
            )

            self.assertEqual(outcome.status, "completed")
            run = runtime.memory_store.get_run(outcome.run_id)
            self.assertEqual("desktop.print_today_vouchers", run["command_name"])
            self.assertIn("confirm_print_dialog", outcome.completed_steps)


if __name__ == "__main__":
    unittest.main()
