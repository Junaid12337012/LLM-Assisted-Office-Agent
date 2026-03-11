from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from desktop_backend import execute_assistant_plan
from tests.helpers import build_runtime


class PhaseThreeAssistantTests(unittest.TestCase):
    def test_morning_instruction_maps_to_multi_workflow_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            plan = runtime.assistant.plan("start today's office work")

            self.assertEqual("ready", plan.status)
            self.assertEqual(3, len(plan.commands))
            self.assertEqual("mvp.start_day", plan.commands[0].command_name)
            self.assertEqual("mvp.download_report", plan.commands[1].command_name)
            self.assertEqual("desktop.check_entries", plan.commands[2].command_name)

    def test_note_instruction_extracts_note_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            plan = runtime.assistant.plan("note call the vendor before lunch")

            self.assertEqual("ready", plan.status)
            self.assertEqual("mvp.note", plan.commands[0].command_name)
            self.assertEqual("call the vendor before lunch", plan.commands[0].inputs["note_text"])

    def test_upload_sequence_requires_confirmation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            plan = runtime.assistant.plan("download the latest report and upload it")

            self.assertEqual("needs_confirmation", plan.status)
            self.assertEqual("portal.upload_latest_file", plan.commands[1].command_name)

    def test_invoice_instruction_without_path_needs_clarification(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            plan = runtime.assistant.plan("read the invoice id from the image")

            self.assertEqual("needs_clarification", plan.status)
            self.assertIn("phase2.read_invoice_id.image_path", plan.missing_parameters)

    def test_print_today_voucher_instruction_maps_to_state_machine_workflow(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            plan = runtime.assistant.plan("print all today voucher")

            self.assertEqual("needs_confirmation", plan.status)
            self.assertEqual("desktop.print_today_vouchers", plan.commands[0].command_name)
            self.assertEqual("today", plan.commands[0].inputs["date_from"])
            self.assertEqual("today", plan.commands[0].inputs["date_to"])

    def test_execute_assistant_plan_runs_multi_step_sequence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime = build_runtime(temp_path)
            workspace_dir = temp_path / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)

            plan = runtime.assistant.plan("start today's office work")
            payload = execute_assistant_plan(runtime, plan, safe_mode=False)

            self.assertEqual("completed", payload["outcome"]["status"])
            self.assertEqual(3, len(payload["runs"]))
            self.assertTrue((temp_path / "memory.db").exists())


if __name__ == "__main__":
    unittest.main()
