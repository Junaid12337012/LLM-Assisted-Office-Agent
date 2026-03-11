from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any


class ConfigurationError(ValueError):
    """Raised when registry or workflow configuration is invalid."""


class SafetyViolation(RuntimeError):
    """Raised when a command or action violates policy."""


class ExecutionFailure(RuntimeError):
    """Raised when workflow execution cannot continue safely."""


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 0
    backoff_ms: int = 0


@dataclass(slots=True)
class FailurePolicy:
    strategy: str = "abort"
    recover_with: str | None = None


@dataclass(slots=True)
class ActionDefinition:
    id: str
    type: str
    args: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 1_000
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    on_fail: FailurePolicy = field(default_factory=FailurePolicy)
    risk: str = "low"


@dataclass(slots=True)
class ValidationRule:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)
    on_fail: FailurePolicy = field(default_factory=FailurePolicy)


@dataclass(slots=True)
class BranchRule:
    if_rule: ValidationRule
    goto_step: str


@dataclass(slots=True)
class WorkflowStep:
    step_id: str
    action: ActionDefinition
    validate: list[ValidationRule] = field(default_factory=list)
    branch: list[BranchRule] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowDefinition:
    id: str
    version: str
    steps: list[WorkflowStep]
    success_criteria: list[ValidationRule] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CommandParameter:
    name: str
    type: str
    required: bool
    enum: list[str] | None = None


@dataclass(slots=True)
class CommandDefinition:
    name: str
    description: str
    workflow_id: str
    parameters: list[CommandParameter] = field(default_factory=list)
    risk: str = "low"
    allowed_targets: dict[str, list[str]] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass(slots=True)
class ActionResult:
    success: bool
    message: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    observations: dict[str, Any] = field(default_factory=dict)
    error_signature_candidate: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationResult:
    success: bool
    message: str = ""
    recover_with: str | None = None


@dataclass(slots=True)
class RecoveryResult:
    recovered: bool
    goto_step: str | None = None
    stop_run: bool = False
    message: str = ""


@dataclass(slots=True)
class RunOutcome:
    run_id: int | None
    status: str
    completed_steps: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None


@dataclass(slots=True)
class RunControl:
    stop_event: Event = field(default_factory=Event)
    pause_event: Event = field(default_factory=Event)

    def request_stop(self) -> None:
        self.stop_event.set()

    def request_pause(self) -> None:
        self.pause_event.set()

    def request_resume(self) -> None:
        self.pause_event.clear()

    def stop_requested(self) -> bool:
        return self.stop_event.is_set()

    def pause_requested(self) -> bool:
        return self.pause_event.is_set()
