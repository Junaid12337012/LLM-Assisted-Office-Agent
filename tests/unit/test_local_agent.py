from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.models import ActionResult
from llm.dataset_validator import validate_jsonl_file
from llm.local_agent import LocalAgentPlanner
from llm.screen_context import ScreenContextCollector
from tests.helpers import build_runtime


class _FakeLocalClient:
    def __init__(self, payload: dict | None = None, *, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error

    def plan_json(self, *, system_prompt: str, user_payload: dict) -> dict:
        if self.error is not None:
            raise self.error
        assert "Approved command catalog" in system_prompt
        assert "instruction" in user_payload
        return self.payload


class _FakeDesktopController:
    def __init__(self) -> None:
        self.snapshot_calls = 0

    def snapshot(self) -> dict:
        self.snapshot_calls += 1
        return {
            "active_window": "Voucher List",
            "controls": ["From Date", "To Date", "PrintButton"],
            "texts": ["Voucher", "Print"],
            "source": "simulated",
        }


class _FakeCaptureController:
    def __init__(self) -> None:
        self.calls = 0

    def perform(self, action_type: str, args: dict) -> ActionResult:
        self.calls += 1
        return ActionResult(
            True,
            "captured",
            data={"screenshot_path": str(args["path"])},
        )


class LocalAgentTests(unittest.TestCase):
    def test_local_agent_builds_validated_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))
            planner = LocalAgentPlanner(
                _FakeLocalClient(
                    {
                        "normalized_instruction": "print all today voucher",
                        "status": "ready",
                        "confidence": 0.94,
                        "explanation": "Matched voucher printing.",
                        "warnings": [],
                        "commands": [
                            {
                                "command_name": "desktop.print_today_vouchers",
                                "inputs": {
                                    "app_name": "voucher_app",
                                    "date_from": "today",
                                    "date_to": "today",
                                },
                                "reason": "Print today's vouchers.",
                            }
                        ],
                    }
                ),
                runtime.assistant.tool_registry,
                ScreenContextCollector(runtime.engine.executor.desktop_controller, None, base_dir=Path(temp_dir)),
                fallback_planner=runtime.assistant,
            )

            plan = planner.plan("print all today voucher")

            self.assertEqual("needs_confirmation", plan.status)
            self.assertEqual("desktop.print_today_vouchers", plan.commands[0].command_name)
            self.assertEqual("local-openai", plan.source)

    def test_local_agent_falls_back_when_local_endpoint_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))
            planner = LocalAgentPlanner(
                _FakeLocalClient(error=RuntimeError("endpoint down")),
                runtime.assistant.tool_registry,
                ScreenContextCollector(runtime.engine.executor.desktop_controller, None, base_dir=Path(temp_dir)),
                fallback_planner=runtime.assistant,
            )

            plan = planner.plan("start today's office work")

            self.assertEqual("local-fallback", plan.source)
            self.assertTrue(any("endpoint down" in warning for warning in plan.warnings))
            self.assertGreaterEqual(len(plan.commands), 1)

    def test_local_agent_prefers_safe_fallback_when_small_model_drifts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))
            planner = LocalAgentPlanner(
                _FakeLocalClient(
                    {
                        "normalized_instruction": "print all today voucher",
                        "status": "success",
                        "confidence": "high",
                        "explanation": "The user wants to print all today's vouchers.",
                        "warnings": [],
                        "commands": [
                            "portal.upload_latest_file",
                            "workspace.open_all",
                            "print_today_vouchers",
                        ],
                    }
                ),
                runtime.assistant.tool_registry,
                ScreenContextCollector(runtime.engine.executor.desktop_controller, None, base_dir=Path(temp_dir)),
                fallback_planner=runtime.assistant,
            )

            plan = planner.plan("print all today voucher")

            self.assertEqual("local-fallback", plan.source)
            self.assertEqual("desktop.print_today_vouchers", plan.commands[0].command_name)
            self.assertTrue(any("safer fallback plan" in warning for warning in plan.warnings))

    def test_screen_context_skips_duplicate_capture_until_screen_changes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            desktop = _FakeDesktopController()
            capture = _FakeCaptureController()
            collector = ScreenContextCollector(desktop, capture, base_dir=Path(temp_dir))

            first = collector.collect(include_screenshot=True)
            second = collector.collect(include_screenshot=True)

            self.assertTrue(first["captured_new_screenshot"])
            self.assertFalse(second["captured_new_screenshot"])
            self.assertEqual(1, capture.calls)

    def test_sample_local_agent_datasets_validate(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]

        train_errors = validate_jsonl_file(repo_root / "datasets" / "local_agent_train.jsonl")
        eval_errors = validate_jsonl_file(repo_root / "datasets" / "local_agent_eval.jsonl")

        self.assertEqual([], train_errors)
        self.assertEqual([], eval_errors)


if __name__ == "__main__":
    unittest.main()
