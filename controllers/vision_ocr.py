from __future__ import annotations

from pathlib import Path
from typing import Any

from core.models import ActionResult


class VisionOcrController:
    def snapshot(self) -> dict[str, Any]:
        return {"available": True}

    def perform(self, action_type: str, args: dict[str, Any]) -> ActionResult:
        if action_type != "vision.ocr_region":
            return ActionResult(False, f"Unsupported OCR action '{action_type}'.")
        path = Path(str(args.get("image_path") or ""))
        extracted_text = args.get("mock_text") or ""
        if not extracted_text and path.exists():
            try:
                extracted_text = path.read_text(encoding="utf-8").strip()
            except Exception:
                extracted_text = ""
        extracted_text = extracted_text or path.stem
        confidence = float(args.get("confidence") or 0.95)
        return ActionResult(
            True,
            f"OCR completed for {path}.",
            observations={"text": extracted_text, "confidence": confidence},
            data={"ocr_text": extracted_text, "ocr_confidence": confidence},
        )
