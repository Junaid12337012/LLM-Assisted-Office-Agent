from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from core.models import ActionResult
from core.utils import ensure_parent


class LocalFileController:
    def snapshot(self) -> dict[str, Any]:
        return {"cwd": str(Path.cwd())}

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def write_text(self, path: str | Path, content: str) -> ActionResult:
        target = ensure_parent(path)
        target.write_text(content, encoding="utf-8")
        return ActionResult(True, f"Wrote text file {target}.", data={"written_path": str(target)})

    def perform(self, action_type: str, args: dict[str, Any]) -> ActionResult:
        if action_type == "files.move":
            source = Path(str(args.get("source") or ""))
            destination = ensure_parent(str(args.get("destination") or ""))
            if not source.exists():
                return ActionResult(False, f"Source file does not exist: {source}")
            shutil.move(str(source), str(destination))
            return ActionResult(True, f"Moved file to {destination}.", data={"destination_path": str(destination)})

        if action_type == "files.rename":
            source = Path(str(args.get("source") or ""))
            destination = ensure_parent(str(args.get("destination") or ""))
            if not source.exists():
                return ActionResult(False, f"Source file does not exist: {source}")
            source.rename(destination)
            return ActionResult(True, f"Renamed file to {destination}.", data={"destination_path": str(destination)})

        if action_type == "files.exists":
            path = Path(str(args.get("path") or ""))
            exists = path.exists()
            return ActionResult(exists, f"Checked file existence for {path}.", data={"path": str(path), "exists": exists})

        if action_type == "files.find_latest":
            directory = Path(str(args.get("directory") or ""))
            pattern = str(args.get("pattern") or "*")
            if not directory.exists():
                return ActionResult(False, f"Directory does not exist: {directory}")
            matches = sorted(directory.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
            if not matches:
                return ActionResult(False, f"No files matching '{pattern}' in {directory}")
            latest = matches[0]
            return ActionResult(True, f"Found latest file {latest}.", data={"latest_file": str(latest)})

        if action_type == "files.write_text":
            path = str(args.get("path") or "")
            content = str(args.get("content") or "")
            return self.write_text(path, content)

        return ActionResult(False, f"Unsupported file action '{action_type}'.")
