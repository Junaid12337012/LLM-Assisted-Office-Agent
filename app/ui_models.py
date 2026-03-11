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


@dataclass(slots=True)
class RunViewModel:
    status: str = "Idle"
    last_command: str = ""
