from __future__ import annotations

from pathlib import Path
from typing import Any
import webbrowser

from core.models import ActionResult
from core.utils import ensure_parent


class PlaywrightBrowserController:
    def __init__(self, dry_run: bool = True, default_download_dir: str | None = None) -> None:
        self._playwright_available = False
        try:
            import playwright  # noqa: F401

            self._playwright_available = True
        except Exception:
            self._playwright_available = False

        self.dry_run = dry_run
        self.default_download_dir = default_download_dir or "data/evidence/exports"
        self.state = {
            "current_url": "",
            "page_text": "Browser ready",
            "fields": {},
            "downloads": [],
            "uploaded_file": None,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_url": self.state["current_url"],
            "page_text": self.state["page_text"],
            "fields": dict(self.state["fields"]),
            "downloads": list(self.state["downloads"]),
            "uploaded_file": self.state["uploaded_file"],
            "dry_run": self.dry_run,
        }

    def perform(self, action_type: str, args: dict[str, Any]) -> ActionResult:
        if action_type == "browser.goto":
            url = str(args.get("url") or "")
            self.state["current_url"] = url
            if "reports" in url:
                self.state["page_text"] = "Daily report portal ready"
            elif "upload" in url:
                self.state["page_text"] = "Upload portal ready"
            else:
                self.state["page_text"] = "Workspace ready"
            if not self.dry_run:
                webbrowser.open(url, new=2)
            return ActionResult(True, f"Navigated to {url}.", data={"current_url": url})

        if action_type == "browser.click":
            selector = str(args.get("selector") or "")
            if selector == "#daily-report":
                self.state["page_text"] = "Daily report ready to download"
            elif selector == "#submit-upload":
                if self.state["uploaded_file"]:
                    self.state["page_text"] = "Upload successful"
                else:
                    return ActionResult(False, "No file queued for upload.")
            return ActionResult(True, f"Clicked {selector}.", data={"last_selector": selector})

        if action_type == "browser.fill":
            selector = str(args.get("selector") or "")
            value = str(args.get("value") or "")
            self.state["fields"][selector] = value
            return ActionResult(True, f"Filled {selector}.", data={"last_selector": selector})

        if action_type == "browser.wait_for":
            expected_text = str(args.get("text") or "")
            if expected_text and expected_text not in self.state["page_text"]:
                return ActionResult(False, f"Expected text '{expected_text}' was not found.")
            return ActionResult(True, "Browser wait condition satisfied.")

        if action_type == "browser.reload":
            if not self.dry_run and self.state["current_url"]:
                webbrowser.open(self.state["current_url"], new=2)
            return ActionResult(True, "Page reloaded.", data={"current_url": self.state["current_url"]})

        if action_type == "browser.download":
            download_dir = Path(str(args.get("download_dir") or self.default_download_dir))
            file_name = str(args.get("file_name") or "download.csv")
            target = ensure_parent(download_dir / file_name)
            target.write_text("id,value\n1,100\n2,200\n", encoding="utf-8")
            self.state["downloads"].append(str(target))
            self.state["page_text"] = "Download completed"
            return ActionResult(
                True,
                f"Downloaded file to {target}.",
                data={"download_path": str(target), "download_file_name": file_name},
            )

        if action_type == "browser.upload_file":
            selector = str(args.get("selector") or "")
            file_path = Path(str(args.get("file_path") or ""))
            if not file_path.exists():
                return ActionResult(False, f"Upload file not found: {file_path}")
            self.state["uploaded_file"] = str(file_path)
            self.state["page_text"] = "Upload ready"
            return ActionResult(True, f"Attached file to {selector}.", data={"uploaded_file": str(file_path)})

        return ActionResult(False, f"Unsupported browser action '{action_type}'.")
