from __future__ import annotations

from pathlib import Path
from typing import Any

from core.models import ActionResult
from core.utils import ensure_parent


class VisionCaptureController:
    def snapshot(self) -> dict[str, Any]:
        return {"available": True}

    def perform(self, action_type: str, args: dict[str, Any]) -> ActionResult:
        if action_type != "vision.capture_screenshot":
            return ActionResult(False, f"Unsupported vision capture action '{action_type}'.")
        path = ensure_parent(Path(str(args.get("path") or "data/evidence/screenshots/capture.png")))
        path.write_bytes(b"")
        return ActionResult(True, f"Captured placeholder screenshot {path}.", data={"screenshot_path": str(path)})
