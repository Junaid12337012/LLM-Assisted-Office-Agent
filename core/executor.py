from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from image_pipeline.confidence import combine_confidence
from image_pipeline.cropper import crop_fixed_region
from image_pipeline.parser import extract_regex_value
from image_pipeline.preprocess import normalize_for_ocr
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

        if action.type == "image.crop_region":
            image_path = Path(str(args.get("image_path") or ""))
            output_path = Path(str(args.get("output_path") or ""))
            if not image_path.exists():
                return ActionResult(False, f"Image does not exist: {image_path}")
            data = crop_fixed_region(image_path, output_path)
            return ActionResult(True, f"Cropped image to {data['cropped_path']}.", data=data)

        if action.type == "image.preprocess_for_ocr":
            image_path = Path(str(args.get("image_path") or ""))
            output_path = Path(str(args.get("output_path") or ""))
            if not image_path.exists():
                return ActionResult(False, f"Image does not exist: {image_path}")
            data = normalize_for_ocr(image_path, output_path)
            return ActionResult(True, f"Prepared OCR image {data['preprocessed_path']}.", data=data)

        if action.type == "image.parse_regex":
            text = str(args.get("text") or "")
            pattern = str(args.get("pattern") or "")
            field_name = str(args.get("field_name") or "parsed_value")
            parsed = extract_regex_value(text, pattern, field_name)
            matched = bool(parsed.get(field_name))
            confidence = combine_confidence(float(args.get("ocr_confidence") or 0.95), matched)
            return ActionResult(
                matched,
                f"Parsed field '{field_name}'.",
                data={**parsed, "parsed_confidence": confidence},
                observations={"parsed_field": field_name, "matched": matched},
            )

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
