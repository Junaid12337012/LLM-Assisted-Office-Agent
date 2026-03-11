from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.models import (
    ActionDefinition,
    BranchRule,
    CommandDefinition,
    ConfigurationError,
    FailurePolicy,
    RetryPolicy,
    RunControl,
    RunOutcome,
    ValidationRule,
    WorkflowDefinition,
    WorkflowStep,
)
from core.utils import load_json, sleep_backoff


class WorkflowRepository:
    def __init__(self, workflows: dict[str, WorkflowDefinition]) -> None:
        self._workflows = workflows

    @classmethod
    def from_directory(cls, directory: str | Path) -> "WorkflowRepository":
        workflows: dict[str, WorkflowDefinition] = {}
        for path in sorted(Path(directory).glob("*.json")):
            workflow = _parse_workflow(load_json(path))
            workflows[workflow.id] = workflow
        return cls(workflows)

    def get(self, workflow_id: str) -> WorkflowDefinition:
        try:
            return self._workflows[workflow_id]
        except KeyError as exc:
            known = ", ".join(sorted(self._workflows))
            raise ConfigurationError(f"Unknown workflow '{workflow_id}'. Known workflows: {known}") from exc


class WorkflowEngine:
    def __init__(
        self,
        workflow_repository: WorkflowRepository,
        executor: Any,
        validator: Any,
        observer: Any,
        recovery_engine: Any,
        safety_gate: Any,
        memory_store: Any,
        review_queue: Any | None,
        logger: Any,
    ) -> None:
        self.workflow_repository = workflow_repository
        self.executor = executor
        self.validator = validator
        self.observer = observer
        self.recovery_engine = recovery_engine
        self.safety_gate = safety_gate
        self.memory_store = memory_store
        self.review_queue = review_queue
        self.logger = logger

    def run(
        self,
        command: CommandDefinition,
        inputs: dict[str, Any],
        safe_mode: bool = False,
        confirmation_handler: Any | None = None,
        control: RunControl | None = None,
    ) -> RunOutcome:
        workflow = self.workflow_repository.get(command.workflow_id)
        control = control or RunControl()
        context = dict(workflow.inputs)
        context.update(inputs)
        context["command_name"] = command.name
        context["workflow_id"] = workflow.id

        run_id = self.memory_store.create_run(command.name, workflow.id, context)
        completed_steps: list[str] = []
        step_lookup = {step.step_id: index for index, step in enumerate(workflow.steps)}

        try:
            self.safety_gate.authorize_command(command, safe_mode, confirmation_handler)
            index = 0
            while index < len(workflow.steps):
                self._wait_if_paused(control)
                if control.stop_requested():
                    summary = {"completed_steps": completed_steps}
                    self.memory_store.finish_run(run_id, "stopped", summary)
                    return RunOutcome(run_id, "stopped", completed_steps, summary)

                step = workflow.steps[index]
                status = self._run_step(
                    step=step,
                    command=command,
                    context=context,
                    run_id=run_id,
                    safe_mode=safe_mode,
                    confirmation_handler=confirmation_handler,
                )
                if status["status"] == "failed":
                    summary = {"completed_steps": completed_steps, "error": status["error"]}
                    self.memory_store.finish_run(run_id, "failed", summary)
                    return RunOutcome(run_id, "failed", completed_steps, summary, status["error"])
                if status["status"] == "needs_review":
                    summary = {
                        "completed_steps": completed_steps,
                        "review_item_id": status.get("review_item_id"),
                        "evidence_path": status.get("evidence_path"),
                        "reason": status.get("reason"),
                    }
                    self.memory_store.finish_run(run_id, "needs_review", summary)
                    return RunOutcome(run_id, "needs_review", completed_steps, summary, status.get("reason"))
                if status["status"] == "goto":
                    target = status["goto_step"]
                    if target not in step_lookup:
                        error = f"Recovery requested unknown step '{target}'."
                        self.memory_store.finish_run(run_id, "failed", {"error": error})
                        return RunOutcome(run_id, "failed", completed_steps, {"error": error}, error)
                    index = step_lookup[target]
                    continue
                completed_steps.append(step.step_id)
                index += 1

            success_checks = self.validator.evaluate_rules(workflow.success_criteria, context, None)
            failures = [result.message for result in success_checks if not result.success]
            if failures:
                summary = {"completed_steps": completed_steps, "error": failures[0]}
                self.memory_store.finish_run(run_id, "failed", summary)
                return RunOutcome(run_id, "failed", completed_steps, summary, failures[0])

            summary = {"completed_steps": completed_steps, "workflow_id": workflow.id}
            self.memory_store.finish_run(run_id, "completed", summary)
            return RunOutcome(run_id, "completed", completed_steps, summary)
        except Exception as exc:
            summary = {"completed_steps": completed_steps, "error": str(exc)}
            self.memory_store.finish_run(run_id, "failed", summary)
            return RunOutcome(run_id, "failed", completed_steps, summary, str(exc))

    def _run_step(
        self,
        step: WorkflowStep,
        command: CommandDefinition,
        context: dict[str, Any],
        run_id: int,
        safe_mode: bool,
        confirmation_handler: Any | None,
    ) -> dict[str, Any]:
        recovery_used = False
        while True:
            result = self._execute_action_with_retry(
                step=step,
                command=command,
                context=context,
                run_id=run_id,
                safe_mode=safe_mode,
                confirmation_handler=confirmation_handler,
            )
            if not result.success:
                failure = self._handle_failure(
                    policy=step.action.on_fail,
                    candidate=result.error_signature_candidate or result.message,
                    context=context,
                    run_id=run_id,
                    workflow_id=command.workflow_id,
                    step_id=step.step_id,
                    confirmation_handler=confirmation_handler,
                )
                if failure.goto_step:
                    return {"status": "goto", "goto_step": failure.goto_step}
                if getattr(failure, "stop_run", False):
                    return {
                        "status": "needs_review",
                        "reason": failure.message,
                        "review_item_id": getattr(failure, "review_item_id", None),
                        "evidence_path": getattr(failure, "evidence_path", None),
                    }
                if failure.recovered and not recovery_used:
                    recovery_used = True
                    continue
                error = failure.message or result.message
                return {"status": "failed", "error": error}

            self._update_context(context, step, result)

            validation_results = self.validator.evaluate_rules(step.validate, context, result)
            first_failure = next((item for item in validation_results if not item.success), None)
            if first_failure is not None:
                self.memory_store.log_step(
                    run_id,
                    step.step_id,
                    "validation_failed",
                    first_failure.message,
                    {"step_id": step.step_id},
                )
                failure_policy = next(
                    rule.on_fail for rule, state in zip(step.validate, validation_results) if not state.success
                )
                failure = self._handle_failure(
                    policy=failure_policy,
                    candidate=first_failure.message,
                    context=context,
                    run_id=run_id,
                    workflow_id=command.workflow_id,
                    step_id=step.step_id,
                    confirmation_handler=confirmation_handler,
                )
                if failure.goto_step:
                    return {"status": "goto", "goto_step": failure.goto_step}
                if getattr(failure, "stop_run", False):
                    return {
                        "status": "needs_review",
                        "reason": failure.message,
                        "review_item_id": getattr(failure, "review_item_id", None),
                        "evidence_path": getattr(failure, "evidence_path", None),
                    }
                if failure.recovered and not recovery_used:
                    recovery_used = True
                    continue
                error = failure.message or first_failure.message
                return {"status": "failed", "error": error}

            for branch in step.branch:
                branch_result = self.validator.evaluate_rule(branch.if_rule, context, result)
                if branch_result.success:
                    return {"status": "goto", "goto_step": branch.goto_step}
            return {"status": "completed"}

    def _execute_action_with_retry(
        self,
        step: WorkflowStep,
        command: CommandDefinition,
        context: dict[str, Any],
        run_id: int,
        safe_mode: bool,
        confirmation_handler: Any | None,
    ) -> Any:
        attempts = max(1, step.action.retry.max_attempts + 1)
        last_result = None
        for attempt in range(1, attempts + 1):
            resolved_args = self.executor.resolve_args(step.action, context)
            self.safety_gate.authorize_action(
                command,
                step.action,
                resolved_args,
                safe_mode,
                confirmation_handler,
            )
            result = self.executor.execute(step.action, context, resolved_args)
            last_result = result
            self.memory_store.log_step(
                run_id,
                step.step_id,
                "succeeded" if result.success else "failed",
                result.message,
                {
                    "action_type": step.action.type,
                    "args": resolved_args,
                    "attempt": attempt,
                    "data": result.data,
                    "observations": result.observations,
                },
            )
            if result.success:
                return result
            if attempt < attempts:
                sleep_backoff(step.action.retry.backoff_ms)
        return last_result

    def _handle_failure(
        self,
        policy: FailurePolicy,
        candidate: str | None,
        context: dict[str, Any],
        run_id: int,
        workflow_id: str,
        step_id: str,
        confirmation_handler: Any | None,
    ) -> Any:
        evidence_path = self._capture_failure_evidence(run_id, step_id)
        if evidence_path:
            self.memory_store.log_event(
                "warning",
                "Failure evidence captured.",
                {"step_id": step_id, "evidence_path": evidence_path, "candidate": candidate},
                run_id,
            )

        if policy.strategy == "abort":
            return _failure(False, None, candidate or "Aborted.", evidence_path=evidence_path)

        if policy.strategy == "escalate":
            if confirmation_handler is None:
                return _failure(False, None, candidate or "Escalation required.", evidence_path=evidence_path)
            approved = confirmation_handler(candidate or "Resume execution?")
            return _failure(approved, None, candidate or "Escalated.", evidence_path=evidence_path)

        if policy.strategy == "recover":
            snapshot = self.observer.snapshot(context)
            plan = self.recovery_engine.plan_for_failure(policy, candidate, snapshot)
            return self.recovery_engine.attempt_recovery(
                plan,
                self.executor,
                context,
                self.memory_store,
                run_id,
                confirmation_handler,
            )

        if policy.strategy == "review":
            if self.review_queue is None:
                return _failure(False, None, candidate or "Manual review required.", stop_run=True, evidence_path=evidence_path)
            suggested_value = str(context.get("ocr_text") or context.get("last_action", {}).get("ocr_text") or "")
            review_item_id = self.review_queue.enqueue(
                workflow_id=workflow_id,
                step_id=step_id,
                reason=candidate or "Manual review required.",
                suggested_value=suggested_value or None,
                evidence_path=evidence_path,
                metadata={"context": context, "step_id": step_id},
                run_id=run_id,
            )
            self.memory_store.log_event(
                "warning",
                "Queued item for manual review.",
                {"review_item_id": review_item_id, "step_id": step_id},
                run_id,
            )
            return _failure(
                False,
                None,
                candidate or "Queued for manual review.",
                stop_run=True,
                review_item_id=review_item_id,
                evidence_path=evidence_path,
            )

        if policy.strategy == "retry":
            return _failure(True, None, "Retry requested.", evidence_path=evidence_path)

        return _failure(False, None, candidate or "Unknown failure strategy.", evidence_path=evidence_path)

    def _capture_failure_evidence(self, run_id: int, step_id: str) -> str | None:
        controller = getattr(self.executor, "vision_capture_controller", None)
        if controller is None:
            return None
        evidence_root = Path(self.memory_store.database_path).parent / "evidence" / "screenshots"
        capture_path = evidence_root / f"run_{run_id}_{step_id}.png"
        result = controller.perform("vision.capture_screenshot", {"path": str(capture_path)})
        if result.success:
            return str(result.data.get("screenshot_path") or capture_path)
        return None

    @staticmethod
    def _update_context(context: dict[str, Any], step: WorkflowStep, result: Any) -> None:
        merged = dict(result.observations)
        merged.update(result.data)
        merged["message"] = result.message
        merged["success"] = result.success
        context[step.step_id] = merged
        context["last_action"] = merged
        for key, value in result.data.items():
            context[key] = value

    @staticmethod
    def _wait_if_paused(control: RunControl) -> None:
        while control.pause_requested() and not control.stop_requested():
            time.sleep(0.1)



def _failure(
    recovered: bool,
    goto_step: str | None,
    message: str,
    stop_run: bool = False,
    review_item_id: int | None = None,
    evidence_path: str | None = None,
):
    return type(
        "Failure",
        (),
        {
            "recovered": recovered,
            "goto_step": goto_step,
            "message": message,
            "stop_run": stop_run,
            "review_item_id": review_item_id,
            "evidence_path": evidence_path,
        },
    )()



def _parse_workflow(item: dict[str, Any]) -> WorkflowDefinition:
    required_fields = {"id", "version", "steps", "success_criteria"}
    missing = sorted(required_fields.difference(item))
    if missing:
        raise ConfigurationError(f"Workflow definition missing fields: {missing}")

    steps = [_parse_step(step) for step in item["steps"]]
    success_criteria = [_parse_validation(rule) for rule in item.get("success_criteria", [])]
    return WorkflowDefinition(
        id=item["id"],
        version=item["version"],
        steps=steps,
        success_criteria=success_criteria,
        inputs=dict(item.get("inputs", {})),
        preconditions=list(item.get("preconditions", [])),
    )



def _parse_step(item: dict[str, Any]) -> WorkflowStep:
    if "step_id" not in item or "action" not in item:
        raise ConfigurationError("Workflow step requires 'step_id' and 'action'.")

    step_id = item["step_id"]
    action = _parse_action(item["action"], step_id)
    validations = [_parse_validation(rule) for rule in item.get("validate", [])]
    branches = [_parse_branch(rule) for rule in item.get("branch", [])]
    return WorkflowStep(step_id=step_id, action=action, validate=validations, branch=branches)



def _parse_action(item: dict[str, Any], step_id: str) -> ActionDefinition:
    if "type" not in item or "args" not in item:
        raise ConfigurationError(f"Action for step '{step_id}' requires 'type' and 'args'.")

    return ActionDefinition(
        id=item.get("id", step_id),
        type=item["type"],
        args=dict(item.get("args", {})),
        timeout_ms=int(item.get("timeout_ms", 1_000)),
        retry=_parse_retry(item.get("retry", {})),
        on_fail=_parse_failure_policy(item.get("on_fail", {"strategy": "abort"})),
        risk=str(item.get("risk", "low")),
    )



def _parse_validation(item: dict[str, Any]) -> ValidationRule:
    if "kind" not in item or "args" not in item:
        raise ConfigurationError("Validation rule requires 'kind' and 'args'.")
    return ValidationRule(
        kind=item["kind"],
        args=dict(item.get("args", {})),
        on_fail=_parse_failure_policy(item.get("on_fail", {"strategy": "abort"})),
    )



def _parse_branch(item: dict[str, Any]) -> BranchRule:
    if "if" not in item or "goto_step" not in item:
        raise ConfigurationError("Branch rule requires 'if' and 'goto_step'.")
    return BranchRule(if_rule=_parse_validation(item["if"]), goto_step=item["goto_step"])



def _parse_retry(item: dict[str, Any]) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=int(item.get("max_attempts", 0)),
        backoff_ms=int(item.get("backoff_ms", 0)),
    )



def _parse_failure_policy(item: dict[str, Any]) -> FailurePolicy:
    if "strategy" not in item:
        raise ConfigurationError("Failure policy requires 'strategy'.")
    return FailurePolicy(strategy=item["strategy"], recover_with=item.get("recover_with"))
