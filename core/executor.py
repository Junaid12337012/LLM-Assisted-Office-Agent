from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.models import ActionDefinition, ActionResult
from core.utils import render_template


class Executor:
    def __init__(
        self,
        desktop_controller: Any,
        browser_controller: Any,
        file_controller: Any,
        memory_store: Any,
        vision_capture_controller: Any | None = None,
        vision_ocr_controller: Any | None = None,
    ) -> None:
        self.desktop_controller = desktop_controller
        self.browser_controller = browser_controller
        self.file_controller = file_controller
        self.memory_store = memory_store
        self.vision_capture_controller = vision_capture_controller
        self.vision_ocr_controller = vision_ocr_controller

    def resolve_args(self, action: ActionDefinition, context: dict[str, Any]) -> dict[str, Any]:
        return dict(render_template(action.args, context))

    def execute(
        self,
        action: ActionDefinition,
        context: dict[str, Any],
        resolved_args: dict[str, Any] | None = None,
    ) -> ActionResult:
        args = resolved_args or self.resolve_args(action, context)

        if action.type.startswith("desktop."):
            return self.desktop_controller.perform(action.type, args)

        if action.type.startswith("browser."):
            return self.browser_controller.perform(action.type, args)

        if action.type.startswith("files."):
            return self.file_controller.perform(action.type, args)

        if action.type == "vision.capture_screenshot" and self.vision_capture_controller is not None:
            return self.vision_capture_controller.perform(action.type, args)

        if action.type == "vision.ocr_region" and self.vision_ocr_controller is not None:
            return self.vision_ocr_controller.perform(action.type, args)

        if action.type == "reports.export_summary":
            run_date = str(args.get("run_date") or "")
            export_path = Path(str(args.get("export_path") or "data/evidence/exports/end_of_day_summary.json"))
            summary = self.memory_store.summary_for_date(run_date)
            payload = json.dumps(summary, indent=2)
            write_result = self.file_controller.write_text(export_path, payload)
            if not write_result.success:
                return write_result
            summary["summary_path"] = str(export_path)
            return ActionResult(True, f"Exported summary to {export_path}.", data=summary)

        return ActionResult(False, f"Unsupported action type '{action.type}'.")
