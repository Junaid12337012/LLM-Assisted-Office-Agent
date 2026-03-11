from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RuntimeServices:
    base_dir: Path
    registry: Any
    workflows: Any
    engine: Any
    memory_store: Any
    review_queue: Any | None = None
    assistant: Any | None = None
    operator_session_manager: Any | None = None
    operator_exception_queue: Any | None = None
    training_store: Any | None = None
    screen_model: Any | None = None
    state_contracts: Any | None = None
    state_detector: Any | None = None


@dataclass(slots=True)
class RunViewModel:
    status: str = "Idle"
    last_command: str = ""
