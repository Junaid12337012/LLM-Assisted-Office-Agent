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
from core.review_queue import ReviewQueue
from core.safety import SafetyGate
from core.validator import Validator
from core.workflow_engine import WorkflowEngine, WorkflowRepository
from llm.confidence import ConfidencePolicy
from llm.interpreter import InstructionInterpreter
from llm.planner import AssistantPlanner
from llm.tool_registry import ToolRegistry
from operator_runtime.checkpoint_manager import CheckpointManager
from operator_runtime.exception_queue import OperatorExceptionQueue
from operator_runtime.session_manager import SessionManager
from operator_runtime.summary_manager import SummaryManager
from operator_runtime.task_queue import TaskQueue



def build_runtime(temp_dir: Path) -> SimpleNamespace:
    root = Path(__file__).resolve().parents[1]
    logger = setup_logging()
    memory_store = MemoryStore(temp_dir / "memory.db")
    review_queue = ReviewQueue(memory_store)
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
    tool_registry = ToolRegistry(registry, root)
    assistant = AssistantPlanner(
        InstructionInterpreter(tool_registry),
        tool_registry,
        confidence_policy=ConfidencePolicy(),
        memory_store=memory_store,
    )
    workflows = WorkflowRepository.from_directory(root / "workflows")
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
    operator_exception_queue = OperatorExceptionQueue(memory_store)
    operator_session_manager = SessionManager(
        memory_store,
        TaskQueue(memory_store),
        CheckpointManager(memory_store),
        operator_exception_queue,
        SummaryManager(),
        registry,
        engine,
        assistant,
    )
    return SimpleNamespace(
        root=root,
        base_dir=root,
        registry=registry,
        workflows=workflows,
        engine=engine,
        memory_store=memory_store,
        review_queue=review_queue,
        safety_gate=safety_gate,
        recovery_engine=recovery_engine,
        assistant=assistant,
        operator_session_manager=operator_session_manager,
        operator_exception_queue=operator_exception_queue,
    )
