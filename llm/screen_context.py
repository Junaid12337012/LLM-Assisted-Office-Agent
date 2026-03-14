from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.utils import ensure_parent, utc_now_iso


class ScreenContextCollector:
    def __init__(
        self,
        desktop_controller: Any,
        vision_capture_controller: Any | None = None,
        *,
        base_dir: str | Path | None = None,
    ) -> None:
        self.desktop_controller = desktop_controller
        self.vision_capture_controller = vision_capture_controller
        self.base_dir = Path(base_dir or Path.cwd())
        self._last_fingerprint = ""

    def collect(
        self,
        *,
        include_screenshot: bool = False,
        force_screenshot: bool = False,
        max_controls: int = 40,
        max_texts: int = 40,
    ) -> dict[str, Any]:
        snapshot = self.desktop_controller.snapshot()
        compact = {
            "active_window": str(snapshot.get("active_window") or ""),
            "source": str(snapshot.get("source") or ""),
            "controls": [str(item) for item in snapshot.get("controls", [])[:max_controls]],
            "texts": [str(item) for item in snapshot.get("texts", [])[:max_texts]],
        }
        compact["fingerprint"] = self._fingerprint(compact)

        should_capture = (
            include_screenshot
            and self.vision_capture_controller is not None
            and (force_screenshot or compact["fingerprint"] != self._last_fingerprint)
        )
        screenshot_path = ""
        if should_capture:
            target = ensure_parent(
                self.base_dir
                / "data"
                / "local_agent"
                / "screens"
                / f"screen_{utc_now_iso().replace(':', '-')}.png"
            )
            result = self.vision_capture_controller.perform(
                "vision.capture_screenshot",
                {"path": str(target)},
            )
            if result.success:
                screenshot_path = str(result.data.get("screenshot_path") or target)

        self._last_fingerprint = compact["fingerprint"]
        compact["screenshot_path"] = screenshot_path
        compact["captured_new_screenshot"] = bool(screenshot_path)
        return compact

    @staticmethod
    def _fingerprint(snapshot: dict[str, Any]) -> str:
        payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha1(payload).hexdigest()
