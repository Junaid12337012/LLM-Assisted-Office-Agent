from __future__ import annotations

from pathlib import Path
from threading import Event, Thread, current_thread, main_thread
import tkinter as tk
from tkinter import messagebox, ttk

from app.ui_models import RuntimeServices, RunViewModel
from controllers.browser_playwright import PlaywrightBrowserController
from controllers.desktop_windows import WindowsDesktopController
from controllers.files_local import LocalFileController
from controllers.vision_capture import VisionCaptureController
from controllers.vision_ocr import VisionOcrController
from core.command_registry import CommandRegistry
from core.executor import Executor
from core.logging_setup import setup_logging
from core.memory import MemoryStore
from core.observer import Observer
from core.recovery import ErrorSignatureRegistry, RecoveryEngine
from core.review_queue import ReviewQueue
from core.safety import SafetyGate
from core.validator import Validator
from core.workflow_engine import WorkflowEngine, WorkflowRepository
from core.models import RunControl


class OfficeAgentTkApp:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.services = self._build_services(self.base_dir)
        self.view_model = RunViewModel()
        self.current_control: RunControl | None = None

        self.root = tk.Tk()
        self.root.title("Office Automation Platform")
        self.root.geometry("980x620")

        self.command_var = tk.StringVar()
        self.safe_mode_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Idle")

        self._build_layout()
        self._load_commands()

    @staticmethod
    def _build_services(base_dir: Path) -> RuntimeServices:
        logger = setup_logging()
        data_dir = base_dir / "data"
        memory_store = MemoryStore(data_dir / "memory.db")
        review_queue = ReviewQueue(memory_store)
        desktop_controller = WindowsDesktopController(dry_run=True)
        browser_controller = PlaywrightBrowserController(
            dry_run=True,
            default_download_dir=str(data_dir / "evidence" / "exports"),
        )
        file_controller = LocalFileController()
        vision_capture_controller = VisionCaptureController()
        vision_ocr_controller = VisionOcrController()
        observer = Observer(
            desktop_controller,
            browser_controller,
            file_controller,
            vision_capture_controller,
            vision_ocr_controller,
        )
        validator = Validator(observer, file_controller)
        executor = Executor(
            desktop_controller,
            browser_controller,
            file_controller,
            memory_store,
            vision_capture_controller,
            vision_ocr_controller,
        )
        recovery_engine = RecoveryEngine(
            ErrorSignatureRegistry.from_file(base_dir / "registry" / "error_signatures.json")
        )
        safety_gate = SafetyGate.from_file(base_dir / "registry" / "policies.json")
        registry = CommandRegistry.from_file(base_dir / "registry" / "commands.json")
        workflows = WorkflowRepository.from_directory(base_dir / "workflows")
        engine = WorkflowEngine(
            workflows,
            executor,
            validator,
            observer,
            recovery_engine,
            safety_gate,
            memory_store,
            review_queue,
            logger,
        )
        return RuntimeServices(base_dir, registry, workflows, engine, memory_store, review_queue)

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(container)
        left.pack(side=tk.LEFT, fill=tk.Y)

        right = ttk.Frame(container)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Commands").pack(anchor=tk.W)
        self.command_list = tk.Listbox(left, width=36, height=14)
        self.command_list.pack(fill=tk.Y, expand=False, pady=(8, 12))
        self.command_list.bind("<<ListboxSelect>>", self._on_command_selected)

        ttk.Label(right, text="Command Input").pack(anchor=tk.W)
        entry = ttk.Entry(right, textvariable=self.command_var)
        entry.pack(fill=tk.X, pady=(8, 12))
        entry.insert(0, "run browser.download_daily_report download_dir=data/evidence/exports export_dir=data/evidence/exports run_date=2026-03-11")

        controls = ttk.Frame(right)
        controls.pack(fill=tk.X, pady=(0, 12))

        ttk.Button(controls, text="Run", command=self._run_command).pack(side=tk.LEFT)
        ttk.Button(controls, text="Pause", command=self._pause).pack(side=tk.LEFT, padx=6)
        ttk.Button(controls, text="Resume", command=self._resume).pack(side=tk.LEFT)
        ttk.Button(controls, text="Stop", command=self._stop).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(controls, text="Safe mode", variable=self.safe_mode_var).pack(side=tk.LEFT, padx=12)

        ttk.Label(right, textvariable=self.status_var).pack(anchor=tk.W)

        ttk.Label(right, text="Run Log").pack(anchor=tk.W, pady=(12, 4))
        self.log_text = tk.Text(right, wrap=tk.WORD, height=24)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(state=tk.DISABLED)

    def _load_commands(self) -> None:
        for command in self.services.registry.list_commands():
            self.command_list.insert(tk.END, command.name)

    def _on_command_selected(self, _event: object) -> None:
        selection = self.command_list.curselection()
        if not selection:
            return
        command_name = self.command_list.get(selection[0])
        self.command_var.set(f"run {command_name}")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_status(self, value: str) -> None:
        self.status_var.set(value)
        self.view_model.status = value

    def _confirm(self, message: str) -> bool:
        if current_thread() is main_thread():
            return bool(messagebox.askyesno("Confirmation Required", message, parent=self.root))

        answered = Event()
        decision = {"value": False}

        def prompt() -> None:
            decision["value"] = bool(messagebox.askyesno("Confirmation Required", message, parent=self.root))
            answered.set()

        self.root.after(0, prompt)
        answered.wait()
        return decision["value"]

    def _run_command(self) -> None:
        raw_command = self.command_var.get().strip()
        if not raw_command:
            messagebox.showerror("Missing command", "Enter a command to run.", parent=self.root)
            return

        self.current_control = RunControl()
        self._set_status("Running")
        self._append_log(f"> {raw_command}")

        def worker() -> None:
            try:
                command, inputs = self.services.registry.parse_invocation(raw_command)
                outcome = self.services.engine.run(
                    command,
                    inputs,
                    safe_mode=self.safe_mode_var.get(),
                    confirmation_handler=self._confirm,
                    control=self.current_control,
                )
                self.root.after(0, lambda: self._on_run_complete(outcome.status, outcome.summary))
            except Exception as exc:
                self.root.after(0, lambda: self._on_run_complete("failed", {"error": str(exc)}))

        Thread(target=worker, daemon=True).start()

    def _on_run_complete(self, status: str, summary: dict[str, object]) -> None:
        self._set_status(status.capitalize())
        self._append_log(f"Status: {status}")
        self._append_log(f"Summary: {summary}")

    def _pause(self) -> None:
        if self.current_control is not None:
            self.current_control.request_pause()
            self._set_status("Paused")
            self._append_log("Execution paused.")

    def _resume(self) -> None:
        if self.current_control is not None:
            self.current_control.request_resume()
            self._set_status("Running")
            self._append_log("Execution resumed.")

    def _stop(self) -> None:
        if self.current_control is not None:
            self.current_control.request_stop()
            self._set_status("Stopping")
            self._append_log("Stop requested.")

    def run(self) -> None:
        self.root.mainloop()

