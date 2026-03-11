from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.helpers import build_runtime


class PhaseFourOperatorTests(unittest.TestCase):
    def test_operator_session_runs_multi_task_queue(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            created = runtime.operator_session_manager.create_session_from_instruction(
                "start today's office work"
            )
            result = runtime.operator_session_manager.run_session(
                created["session"]["id"],
                safe_mode=False,
            )

            self.assertEqual("completed", result["session"]["status"])
            self.assertEqual(3, result["summary"]["completed_tasks"])
            self.assertEqual(0, result["summary"]["open_exceptions"])

    def test_operator_session_resume_after_partial_progress(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            created = runtime.operator_session_manager.create_session_from_instruction(
                "start today's office work"
            )
            first_pass = runtime.operator_session_manager.run_session(
                created["session"]["id"],
                safe_mode=False,
                max_tasks=1,
            )
            self.assertEqual("pending", first_pass["session"]["status"])
            resumed = runtime.operator_session_manager.run_session(
                created["session"]["id"],
                safe_mode=False,
            )

            self.assertEqual("completed", resumed["session"]["status"])
            checkpoints = runtime.memory_store.list_operator_checkpoints(created["session"]["id"])
            self.assertGreaterEqual(len(checkpoints), 3)

    def test_operator_session_blocks_risky_task_until_approved(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))

            created = runtime.operator_session_manager.create_session_from_instruction(
                "download the latest report and upload it"
            )
            first_run = runtime.operator_session_manager.run_session(
                created["session"]["id"],
                safe_mode=False,
                confirm_risky=False,
            )

            self.assertEqual("partial", first_run["session"]["status"])
            self.assertEqual(1, len(first_run["exceptions"]))
            exception_id = first_run["exceptions"][0]["id"]

            runtime.operator_session_manager.resolve_exception(exception_id, resolution="approved")
            resumed = runtime.operator_session_manager.run_session(
                created["session"]["id"],
                safe_mode=False,
                confirm_risky=True,
            )

            self.assertEqual("completed", resumed["session"]["status"])
            self.assertEqual(0, resumed["summary"]["open_exceptions"])


if __name__ == "__main__":
    unittest.main()
