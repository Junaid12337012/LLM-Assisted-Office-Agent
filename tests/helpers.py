from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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



def build_runtime(temp_dir: Path) -> SimpleNamespace:
    root = Path(__file__).resolve().parents[1]
    logger = setup_logging()
    memory_store = MemoryStore(temp_dir / "memory.db")
    desktop_controller = WindowsDesktopController(dry_run=True)
    browser_controller = PlaywrightBrowserController(
        dry_run=True,
        default_download_dir=str(temp_dir / "downloads"),
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
        ErrorSignatureRegistry.from_file(root / "registry" / "error_signatures.json")
    )
    safety_gate = SafetyGate.from_file(root / "registry" / "policies.json")
    registry = CommandRegistry.from_file(root / "registry" / "commands.json")
    workflows = WorkflowRepository.from_directory(root / "workflows")
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
    return SimpleNamespace(
        root=root,
        registry=registry,
        workflows=workflows,
        engine=engine,
        memory_store=memory_store,
        safety_gate=safety_gate,
        recovery_engine=recovery_engine,
    )
