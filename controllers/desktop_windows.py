from __future__ import annotations

import ctypes
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
        self.screen_routes = {
            "dashboard": "Entry Manager",
            "voucher_list": "Voucher List",
            "print_dialog": "Print Dialog",
            "print_success": "Print Success",
            "print_error": "Print Error",
        }
        self.state = {
            "active_window": "Entry Manager",
            "filters": {"date_from": "", "date_to": ""},
            "windows": {
                "Entry Manager": {
                    "controls": ["EntriesGrid", "ValidateButton", "UploadButton", "VoucherMenu"],
                    "texts": ["Entries ready", "Workspace loaded", "Voucher"],
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
                "Voucher List": {
                    "controls": ["From Date", "To Date", "LoadButton", "PrintButton", "VoucherGrid"],
                    "texts": ["Voucher", "Print", "From Date", "To Date"],
                    "entries": [
                        {"id": "V-001", "fields": {"amount": "450", "reference": "TODAY-001"}},
                        {"id": "V-002", "fields": {"amount": "225", "reference": "TODAY-002"}},
                        {"id": "V-003", "fields": {"amount": "119", "reference": "TODAY-003"}},
                    ],
                },
                "Print Dialog": {
                    "controls": ["ConfirmPrintButton", "CancelPrintButton"],
                    "texts": ["Print vouchers", "Confirm"],
                    "entries": [],
                },
                "Print Success": {
                    "controls": ["CloseButton"],
                    "texts": ["Printed successfully"],
                    "entries": [],
                },
                "Print Error": {
                    "controls": ["RetryButton", "CancelButton"],
                    "texts": ["Print failed"],
                    "entries": [],
                },
                "Report Viewer": {
                    "controls": ["OpenButton", "RefreshButton"],
                    "texts": ["Report viewer ready"],
                    "entries": [],
                },
            },
        }

    def snapshot(self) -> dict[str, Any]:
        if not self.dry_run:
            live_snapshot = self._snapshot_live()
            if live_snapshot is not None:
                return live_snapshot

        active_window = self.state["active_window"]
        window_state = self.state["windows"].get(active_window, {})
        return {
            "active_window": active_window,
            "controls": list(window_state.get("controls", [])),
            "texts": list(window_state.get("texts", [])),
            "entries": list(window_state.get("entries", [])),
            "filters": dict(self.state.get("filters", {})),
            "dry_run": self.dry_run,
            "source": "simulated",
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

        if action_type == "desktop.goto_screen":
            screen_id = str(args.get("screen_id") or "")
            window_name = self.screen_routes.get(screen_id)
            if not window_name:
                return ActionResult(False, f"Unknown target screen '{screen_id}'.")
            self.state["active_window"] = window_name
            return ActionResult(
                True,
                f"Moved to screen '{screen_id}'.",
                data={"current_screen_id": screen_id, "active_window": window_name},
            )

        if action_type == "desktop.set_date_range":
            if self.state["active_window"] != "Voucher List":
                return ActionResult(False, "Date range can only be set from the voucher list screen.")
            date_from = str(args.get("date_from") or "")
            date_to = str(args.get("date_to") or "")
            self.state["filters"] = {"date_from": date_from, "date_to": date_to}
            return ActionResult(
                True,
                f"Applied voucher date range {date_from} to {date_to}.",
                data={
                    "applied_date_from": date_from,
                    "applied_date_to": date_to,
                    "current_screen_id": "voucher_list",
                },
            )

        if action_type == "desktop.load_vouchers":
            if self.state["active_window"] != "Voucher List":
                return ActionResult(False, "Voucher rows can only be loaded from the voucher list screen.")
            filters = self.state.get("filters", {})
            date_from = str(filters.get("date_from") or "")
            date_to = str(filters.get("date_to") or "")
            row_count = 3 if date_from and date_to else 0
            return ActionResult(
                row_count > 0,
                f"Loaded {row_count} vouchers.",
                data={
                    "voucher_row_count": row_count,
                    "current_screen_id": "voucher_list",
                    "applied_date_from": date_from,
                    "applied_date_to": date_to,
                },
            )

        if action_type == "desktop.click_named_control":
            target = str(args.get("target") or "")
            if target == "print_button" and self.state["active_window"] == "Voucher List":
                self.state["active_window"] = "Print Dialog"
                return ActionResult(
                    True,
                    "Opened the print dialog.",
                    data={"current_screen_id": "print_dialog", "clicked_target": target},
                )
            if target == "confirm_print_button" and self.state["active_window"] == "Print Dialog":
                self.state["active_window"] = "Print Success"
                return ActionResult(
                    True,
                    "Confirmed voucher printing.",
                    data={"current_screen_id": "print_success", "clicked_target": target},
                )
            return ActionResult(False, f"Target '{target}' is not available on the current screen.")

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

    def _snapshot_live(self) -> dict[str, Any] | None:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return {
                "active_window": "",
                "controls": [],
                "texts": [],
                "entries": [],
                "dry_run": self.dry_run,
                "source": "live-empty",
            }

        title = self._get_window_title(hwnd)
        controls: list[str] = []
        control_details: list[dict[str, str]] = []
        texts: list[str] = []
        source = "live-basic"
        if self._pywinauto_available:
            try:
                live_details = self._collect_live_controls(hwnd)
                controls = live_details["controls"]
                control_details = live_details["control_details"]
                texts = live_details["texts"]
                source = live_details["source"]
            except Exception:
                controls = []
                control_details = []
                texts = []
                source = "live-title-only"

        return {
            "active_window": title,
            "controls": controls,
            "control_details": control_details,
            "texts": texts,
            "entries": [],
            "dry_run": self.dry_run,
            "source": source,
            "hwnd": int(hwnd),
        }

    @staticmethod
    def _get_window_title(hwnd: int) -> str:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _collect_live_controls(self, hwnd: int) -> dict[str, Any]:
        from pywinauto import Desktop

        identifiers: list[str] = []
        control_details: list[dict[str, str]] = []
        texts: list[str] = []
        seen_identifiers: set[str] = set()
        seen_texts: set[str] = set()

        window = Desktop(backend="uia").window(handle=hwnd)
        elements = [window] + list(window.descendants())
        for element in elements[:250]:
            info = getattr(element, "element_info", None)
            if info is None:
                continue

            detail = {
                "name": str(getattr(info, "name", "") or "").strip(),
                "type": str(getattr(info, "control_type", "") or "").strip(),
                "automation_id": str(getattr(info, "automation_id", "") or "").strip(),
                "class_name": str(getattr(info, "class_name", "") or "").strip(),
            }
            if any(detail.values()):
                control_details.append(detail)

            candidate_identifiers = [
                detail["automation_id"],
                detail["type"],
                detail["class_name"],
                detail["name"],
            ]
            for candidate in candidate_identifiers:
                normalized = candidate.strip()
                if not normalized:
                    continue
                lowered = normalized.lower()
                if lowered in seen_identifiers:
                    continue
                seen_identifiers.add(lowered)
                identifiers.append(normalized)

            visible_text = str(getattr(info, "name", "") or "").strip()
            if visible_text:
                lowered_text = visible_text.lower()
                if lowered_text not in seen_texts:
                    seen_texts.add(lowered_text)
                    texts.append(visible_text)

        return {
            "controls": identifiers[:120],
            "control_details": control_details[:120],
            "texts": texts[:120],
            "source": "live-uia",
        }
