from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from core.utils import ensure_parent, utc_now_iso


def _slugify(value: str) -> str:
    collapsed = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower()
    return collapsed or "template"


class ScreenTemplateStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.templates_dir = self.base_dir / "templates"
        self.captures_dir = self.base_dir / "captures"
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def build_capture_path(self, app_name: str, screen_name: str) -> Path:
        timestamp = utc_now_iso().replace(":", "-")
        filename = f"{_slugify(app_name)}_{_slugify(screen_name)}_{timestamp}.png"
        return ensure_parent(self.captures_dir / filename)

    def save_template(
        self,
        *,
        app_name: str,
        screen_name: str,
        window_title: str = "",
        capture_path: str = "",
        regions: list[dict[str, Any]] | None = None,
        expected_controls: list[str] | None = None,
        expected_texts: list[str] | None = None,
        notes: str = "",
        template_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_capture = self._copy_capture(capture_path) if capture_path else ""
        timestamp = utc_now_iso()
        identifier = template_id or f"{_slugify(app_name)}_{_slugify(screen_name)}"
        template = {
            "template_id": identifier,
            "app_name": app_name,
            "screen_name": screen_name,
            "window_title": window_title,
            "capture_path": resolved_capture,
            "regions": regions or [],
            "expected_controls": expected_controls or [],
            "expected_texts": expected_texts or [],
            "notes": notes,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        path = self.templates_dir / f"{identifier}.json"
        path.write_text(json.dumps(template, indent=2), encoding="utf-8")
        return template

    def list_templates(self, *, app_name: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.templates_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if app_name and payload.get("app_name") != app_name:
                continue
            items.append(payload)
        return items

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        path = self.templates_dir / f"{template_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _copy_capture(self, capture_path: str) -> str:
        source = Path(capture_path)
        if not source.exists():
            return str(source)
        if source.parent == self.captures_dir:
            return str(source)
        destination = ensure_parent(self.captures_dir / source.name)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return str(destination)
