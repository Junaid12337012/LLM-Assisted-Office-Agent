from __future__ import annotations

from pathlib import Path
import subprocess
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
        capture_area = {
            "left": int(args.get("left") or 0),
            "top": int(args.get("top") or 0),
            "width": int(args.get("width") or 0),
            "height": int(args.get("height") or 0),
        }
        error_message = self._capture_png(path, capture_area)
        if error_message is None:
            return ActionResult(
                True,
                f"Captured screenshot {path}.",
                data={"screenshot_path": str(path), "capture_area": capture_area},
            )

        path.write_bytes(b"")
        return ActionResult(
            False,
            f"Failed to capture screenshot with PowerShell: {error_message}",
            data={"screenshot_path": str(path), "capture_area": capture_area},
        )

    @staticmethod
    def _capture_png(path: Path, capture_area: dict[str, int]) -> str | None:
        escaped_path = str(path).replace("'", "''")
        left = capture_area["left"]
        top = capture_area["top"]
        width = capture_area["width"]
        height = capture_area["height"]
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$path = '{escaped_path}'
if ({width} -gt 0 -and {height} -gt 0) {{
    $bounds = New-Object System.Drawing.Rectangle({left}, {top}, {width}, {height})
}}
else {{
    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
}}
$bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
"""
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return None
        return (completed.stderr or completed.stdout or "unknown error").strip()
