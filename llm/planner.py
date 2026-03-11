from __future__ import annotations

from typing import Any

from llm.confidence import ConfidencePolicy
from llm.interpreter import InstructionInterpreter
from llm.schemas import AssistantPlan, PlannedCommand
from llm.tool_registry import ToolRegistry


class AssistantPlanner:
    def __init__(
        self,
        interpreter: InstructionInterpreter,
        tool_registry: ToolRegistry,
        *,
        confidence_policy: ConfidencePolicy | None = None,
        memory_store: Any | None = None,
    ) -> None:
        self.interpreter = interpreter
        self.tool_registry = tool_registry
        self.confidence_policy = confidence_policy or ConfidencePolicy()
        self.memory_store = memory_store

    def plan(self, instruction: str) -> AssistantPlan:
        repeat_plan = self._maybe_repeat_last(instruction)
        if repeat_plan is not None:
            repeat_plan.confidence = self.confidence_policy.clamp(repeat_plan.confidence)
            if repeat_plan.status != "unmatched":
                repeat_plan.status = self.confidence_policy.classify(
                    repeat_plan.confidence,
                    missing_parameters=repeat_plan.missing_parameters,
                    requires_confirmation=repeat_plan.requires_confirmation,
                )
            return repeat_plan

        plan = self.interpreter.interpret(instruction)
        plan.confidence = self.confidence_policy.clamp(plan.confidence)
        if plan.status != "unmatched":
            plan.status = self.confidence_policy.classify(
                plan.confidence,
                missing_parameters=plan.missing_parameters,
                requires_confirmation=plan.requires_confirmation,
            )
        if plan.status == "needs_confirmation" and not plan.requires_confirmation:
            plan.warnings.append("Review the suggested plan before running it automatically.")
        elif plan.status == "needs_clarification" and not plan.missing_parameters:
            plan.warnings.append("The instruction was not specific enough for a safe automatic run.")
        return plan

    def _maybe_repeat_last(self, instruction: str) -> AssistantPlan | None:
        normalized = " ".join(instruction.lower().split())
        if not any(token in normalized for token in ("repeat", "again", "rerun")):
            return None
        if self.memory_store is None:
            return None

        recent_runs = self.memory_store.list_runs(limit=10, status="completed")
        if not recent_runs:
            return None

        latest = recent_runs[0]
        command_name = latest["command_name"]
        if not self.tool_registry.has_command(command_name):
            return None

        values, missing = self.tool_registry.fill_defaults(command_name, latest["inputs"])
        command = self.tool_registry.get_command(command_name)
        return AssistantPlan(
            instruction=instruction,
            normalized_instruction=normalized,
            status="ready",
            confidence=0.94,
            explanation=f"Reused the latest successful run of {command_name} from history.",
            commands=[
                PlannedCommand(
                    tool_name="run_workflow",
                    command_name=command.name,
                    workflow_id=command.workflow_id,
                    raw_command=self.tool_registry.build_raw_command(command_name, values),
                    inputs=values,
                    reason="Repeat the most recent successful workflow execution.",
                    risk=command.risk,
                    requires_confirmation=command.requires_confirmation,
                )
            ],
            warnings=[],
            missing_parameters=[f"{command_name}.{name}" for name in missing],
            requires_confirmation=command.requires_confirmation,
            source="history",
        )
