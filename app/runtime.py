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
from core.review_queue import ReviewQueue
from core.safety import SafetyGate
from core.state_contracts import ScreenContractRegistry
from core.state_detector import StateDetector
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
from training.screen_model import ScreenModel
from training.template_store import ScreenTemplateStore



def build_services(base_dir: Path | None = None) -> RuntimeServices:
    resolved_base = base_dir or Path(__file__).resolve().parent.parent
    logger = setup_logging()
    data_dir = resolved_base / "data"
    memory_store = MemoryStore(data_dir / "memory.db")
    review_queue = ReviewQueue(memory_store)
    state_contracts = ScreenContractRegistry.from_file(resolved_base / "registry" / "screen_contracts.json")
    state_detector = StateDetector(state_contracts)
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
    validator = Validator(observer, file_controller, state_detector)
    executor = Executor(
        desktop_controller,
        browser_controller,
        file_controller,
        memory_store,
        vision_capture_controller,
        vision_ocr_controller,
        state_detector,
    )
    recovery_engine = RecoveryEngine(
        ErrorSignatureRegistry.from_file(resolved_base / "registry" / "error_signatures.json")
    )
    safety_gate = SafetyGate.from_file(resolved_base / "registry" / "policies.json")
    registry = CommandRegistry.from_file(resolved_base / "registry" / "commands.json")
    tool_registry = ToolRegistry(registry, resolved_base)
    assistant = AssistantPlanner(
        InstructionInterpreter(tool_registry),
        tool_registry,
        confidence_policy=ConfidencePolicy(),
        memory_store=memory_store,
    )
    workflows = WorkflowRepository.from_directory(resolved_base / "workflows")
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
    training_store = ScreenTemplateStore(data_dir / "training")
    screen_model = ScreenModel()
    return RuntimeServices(
        base_dir=resolved_base,
        registry=registry,
        workflows=workflows,
        engine=engine,
        memory_store=memory_store,
        review_queue=review_queue,
        assistant=assistant,
        operator_session_manager=operator_session_manager,
        operator_exception_queue=operator_exception_queue,
        training_store=training_store,
        screen_model=screen_model,
        state_contracts=state_contracts,
        state_detector=state_detector,
    )

