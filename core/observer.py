from __future__ import annotations

from typing import Any


class Observer:
    def __init__(
        self,
        desktop_controller: Any,
        browser_controller: Any,
        file_controller: Any,
        vision_capture_controller: Any | None = None,
        vision_ocr_controller: Any | None = None,
    ) -> None:
        self.desktop_controller = desktop_controller
        self.browser_controller = browser_controller
        self.file_controller = file_controller
        self.vision_capture_controller = vision_capture_controller
        self.vision_ocr_controller = vision_ocr_controller

    def snapshot(self, _context: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = {
            "desktop": self.desktop_controller.snapshot(),
            "browser": self.browser_controller.snapshot(),
            "files": self.file_controller.snapshot(),
        }
        if self.vision_capture_controller is not None:
            snapshot["vision_capture"] = self.vision_capture_controller.snapshot()
        if self.vision_ocr_controller is not None:
            snapshot["vision_ocr"] = self.vision_ocr_controller.snapshot()
        return snapshot
