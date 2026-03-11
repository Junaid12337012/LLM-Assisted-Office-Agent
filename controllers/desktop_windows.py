from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from core.models import ActionResult


class WindowsDesktopController:
    def __init__(self, dry_run: bool = True) -> None:
        self._pywinauto_available = False
        try:
            import pywinauto  # noqa: F401

            self._pywinauto_available = True
        except Exception:
            self._pywinauto_available = False

        self.dry_run = dry_run
        self.state = {
            "active_window": "Entry Manager",
            "windows": {
                "Entry Manager": {
                    "controls": ["EntriesGrid", "ValidateButton", "UploadButton"],
                    "texts": ["Entries ready", "Workspace loaded"],
                    "entries": [
                        {
                            "id": "A-100",
                            "fields": {"amount": "120", "reference": "INV-001"},
                        },
                        {
                            "id": "A-101",
                            "fields": {"amount": "240", "reference": "INV-002"},
                        },
                    ],
                },
                "Report Viewer": {
                    "controls": ["OpenButton", "RefreshButton"],
                    "texts": ["Report viewer ready"],
                    "entries": [],
                },
            },
        }

    def snapshot(self) -> dict[str, Any]:
        active_window = self.state["active_window"]
        window_state = self.state["windows"].get(active_window, {})
        return {
            "active_window": active_window,
            "controls": list(window_state.get("controls", [])),
            "texts": list(window_state.get("texts", [])),
            "entries": list(window_state.get("entries", [])),
            "dry_run": self.dry_run,
        }

    def perform(self, action_type: str, args: dict[str, Any]) -> ActionResult:
        if action_type == "desktop.focus_window":
            title = str(args.get("window_title") or args.get("app") or "")
            if title in self.state["windows"]:
                self.state["active_window"] = title
                return ActionResult(True, f"Focused window '{title}'.", data={"active_window": title})
            return ActionResult(False, f"Window '{title}' not found.")

        if action_type == "desktop.open_path":
            target = Path(str(args.get("path") or ""))
            if not target.exists():
                return ActionResult(False, f"Path does not exist: {target}")
            if not self.dry_run:
                os.startfile(str(target))
            return ActionResult(True, f"Opened path '{target}'.", data={"opened_path": str(target)})

        if action_type == "desktop.launch_app":
            command = str(args.get("command") or "")
            if not command:
                return ActionResult(False, "No command provided for desktop.launch_app.")
            launched_pid = None
            if not self.dry_run:
                argv = [part.strip('"') for part in shlex.split(command, posix=False)]
                process = subprocess.Popen(argv, shell=False)
                launched_pid = process.pid
            data = {"launched_app": command}
            if launched_pid is not None:
                data["launched_pid"] = launched_pid
            return ActionResult(True, f"Launched '{command}'.", data=data)

        if action_type in {"desktop.click_control", "desktop.wait_for_control"}:
            snapshot = self.snapshot()
            control = str(args.get("control") or "")
            if control in snapshot["controls"]:
                return ActionResult(True, f"Control '{control}' is available.", data={"control": control})
            return ActionResult(False, f"Control '{control}' not found on active window.")

        if action_type == "desktop.send_keys":
            keys = str(args.get("keys") or "")
            return ActionResult(True, f"Sent keys '{keys}'.", data={"keys": keys})

        if action_type == "desktop.inspect_entries":
            snapshot = self.snapshot()
            required_fields = list(args.get("required_fields", ["amount", "reference"]))
            exceptions: list[str] = []
            for entry in snapshot["entries"]:
                missing = [field for field in required_fields if not entry["fields"].get(field)]
                if missing:
                    exceptions.append(f"{entry['id']}: missing {', '.join(missing)}")
            data = {
                "exception_count": str(len(exceptions)),
                "entry_count": len(snapshot["entries"]),
                "entry_summary": "; ".join(exceptions) if exceptions else "No exceptions found",
            }
            return ActionResult(True, "Entries inspected.", observations=data, data=data)

        return ActionResult(False, f"Unsupported desktop action '{action_type}'.")
