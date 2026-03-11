from __future__ import annotations

from pathlib import Path

from app.ui_models import RuntimeServices
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
from core.safety import SafetyGate
from core.validator import Validator
from core.workflow_engine import WorkflowEngine, WorkflowRepository



def build_services(base_dir: Path | None = None) -> RuntimeServices:
    resolved_base = base_dir or Path(__file__).resolve().parent.parent
    logger = setup_logging()
    data_dir = resolved_base / "data"
    memory_store = MemoryStore(data_dir / "memory.db")
    desktop_controller = WindowsDesktopController(dry_run=False)
    browser_controller = PlaywrightBrowserController(
        dry_run=False,
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
        ErrorSignatureRegistry.from_file(resolved_base / "registry" / "error_signatures.json")
    )
    safety_gate = SafetyGate.from_file(resolved_base / "registry" / "policies.json")
    registry = CommandRegistry.from_file(resolved_base / "registry" / "commands.json")
    workflows = WorkflowRepository.from_directory(resolved_base / "workflows")
    engine = WorkflowEngine(
        workflows,
        executor,
        validator,
        observer,
        recovery_engine,
        safety_gate,
        memory_store,
        logger,
    )
    return RuntimeServices(resolved_base, registry, workflows, engine, memory_store)

