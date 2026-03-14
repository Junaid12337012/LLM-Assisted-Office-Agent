from __future__ import annotations

import re
from typing import Any

from llm.confidence import ConfidencePolicy
from llm.schemas import AssistantPlan, PlannedCommand


class LocalAgentPlanner:
    def __init__(
        self,
        local_client: Any,
        tool_registry: Any,
        screen_collector: Any,
        *,
        fallback_planner: Any | None = None,
        confidence_policy: ConfidencePolicy | None = None,
    ) -> None:
        self.local_client = local_client
        self.tool_registry = tool_registry
        self.screen_collector = screen_collector
        self.fallback_planner = fallback_planner
        self.confidence_policy = confidence_policy or ConfidencePolicy()
        self.last_screen_context: dict[str, Any] | None = None

    def plan(
        self,
        instruction: str,
        *,
        include_screen: bool = False,
        force_screenshot: bool = False,
    ) -> AssistantPlan:
        self.last_screen_context = self.screen_collector.collect(
            include_screenshot=include_screen,
            force_screenshot=force_screenshot,
        )
        try:
            raw_plan = self.local_client.plan_json(
                system_prompt=self._build_system_prompt(),
                user_payload={
                    "instruction": instruction,
                    "screen_context": self.last_screen_context,
                },
            )
            local_plan = self._build_validated_plan(instruction, raw_plan)
            if self.fallback_planner is not None:
                fallback = self.fallback_planner.plan(instruction)
                if self._should_prefer_fallback(local_plan, fallback):
                    fallback.warnings.append(
                        "Local model output drifted from the approved workflow catalog, so the safer fallback plan was used."
                    )
                    fallback.source = "local-fallback"
                    return fallback
            return local_plan
        except Exception as exc:
            if self.fallback_planner is not None:
                fallback = self.fallback_planner.plan(instruction)
                fallback.warnings.append(f"Local model fallback used: {exc}")
                fallback.source = "local-fallback"
                return fallback
            return AssistantPlan(
                instruction=instruction,
                normalized_instruction=instruction.strip().lower(),
                status="unmatched",
                confidence=0.0,
                explanation=str(exc),
                warnings=[str(exc)],
                source="local-error",
            )

    def _build_validated_plan(self, instruction: str, raw_plan: dict[str, Any]) -> AssistantPlan:
        confidence = self._coerce_confidence(raw_plan.get("confidence"))
        warnings = [str(item) for item in raw_plan.get("warnings", [])]
        commands: list[PlannedCommand] = []
        missing_parameters: list[str] = []
        requires_confirmation = False

        for item in raw_plan.get("commands", []):
            normalized = self._normalize_command_item(item)
            command_name = str(normalized.get("command_name") or "")
            if not command_name or not self.tool_registry.has_command(command_name):
                raise RuntimeError(f"Local model proposed an unknown command: {command_name or '<empty>'}")

            provided_inputs = dict(normalized.get("inputs") or {})
            filled_inputs, missing = self.tool_registry.fill_defaults(command_name, provided_inputs)
            if missing:
                missing_parameters.extend(f"{command_name}.{name}" for name in missing)

            command = self.tool_registry.get_command(command_name)
            commands.append(
                PlannedCommand(
                    tool_name="run_workflow",
                    command_name=command.name,
                    workflow_id=command.workflow_id,
                    raw_command=self.tool_registry.build_raw_command(command_name, filled_inputs),
                    inputs=filled_inputs,
                    reason=str(normalized.get("reason") or "Planned by the local model."),
                    risk=command.risk,
                    requires_confirmation=command.requires_confirmation,
                )
            )
            requires_confirmation = requires_confirmation or command.requires_confirmation

        requested_status = self._normalize_status(raw_plan.get("status"))
        if requested_status == "unmatched":
            status = "unmatched"
        else:
            status = self.confidence_policy.classify(
                confidence,
                missing_parameters=missing_parameters,
                requires_confirmation=requires_confirmation,
            )

        if not commands and status != "unmatched":
            status = "needs_clarification"
            warnings.append("Local model did not return any approved commands.")

        return AssistantPlan(
            instruction=instruction,
            normalized_instruction=str(raw_plan.get("normalized_instruction") or instruction.strip().lower()),
            status=status,
            confidence=confidence,
            explanation=str(raw_plan.get("explanation") or "Planned by the local model."),
            commands=commands,
            warnings=warnings,
            missing_parameters=missing_parameters,
            requires_confirmation=requires_confirmation,
            source="local-openai",
        )

    def _normalize_command_item(self, item: Any) -> dict[str, Any]:
        if isinstance(item, str):
            return {
                "command_name": self._coerce_command_name(item),
                "inputs": {},
                "reason": "Mapped from the local model string command output.",
            }
        if isinstance(item, dict):
            command_name = item.get("command_name") or item.get("name") or item.get("command")
            return {
                "command_name": self._coerce_command_name(str(command_name or "")),
                "inputs": dict(item.get("inputs") or item.get("args") or {}),
                "reason": item.get("reason") or item.get("description") or "",
            }
        raise RuntimeError(f"Local model returned an unsupported command shape: {type(item).__name__}")

    def _coerce_command_name(self, raw_name: str) -> str:
        command_name = raw_name.strip()
        if self.tool_registry.has_command(command_name):
            return command_name

        normalized = re.sub(r"[^a-z0-9_.]+", "_", command_name.lower()).strip("_")
        if self.tool_registry.has_command(normalized):
            return normalized

        for prefix in ("desktop", "mvp", "workspace", "browser", "portal", "reports", "phase2"):
            candidate = f"{prefix}.{normalized}"
            if self.tool_registry.has_command(candidate):
                return candidate
        return normalized

    def _coerce_confidence(self, raw_confidence: Any) -> float:
        if isinstance(raw_confidence, str):
            lookup = {"low": 0.35, "medium": 0.65, "high": 0.9}
            if raw_confidence.strip().lower() in lookup:
                return lookup[raw_confidence.strip().lower()]
        try:
            return self.confidence_policy.clamp(float(raw_confidence or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_status(raw_status: Any) -> str:
        value = str(raw_status or "ready").strip().lower()
        if value in {"success", "ok"}:
            return "ready"
        return value

    @staticmethod
    def _command_names(plan: AssistantPlan) -> set[str]:
        return {command.command_name for command in plan.commands}

    def _should_prefer_fallback(self, local_plan: AssistantPlan, fallback_plan: AssistantPlan) -> bool:
        if fallback_plan.status == "unmatched" or not fallback_plan.commands:
            return False

        local_names = self._command_names(local_plan)
        fallback_names = self._command_names(fallback_plan)
        if not local_names:
            return True
        if fallback_plan.confidence >= 0.85 and local_names - fallback_names:
            return True
        if fallback_plan.confidence > local_plan.confidence and local_names != fallback_names:
            return True
        return False

    def _build_system_prompt(self) -> str:
        catalog_lines: list[str] = []
        for command in self.tool_registry.list_commands():
            parameters = ", ".join(parameter.name for parameter in command.parameters) or "no params"
            catalog_lines.append(
                f"- {command.name}: {command.description} | params: {parameters} | risk: {command.risk}"
            )
        catalog_text = "\n".join(catalog_lines)
        return (
            "You are a local planning model for a desktop agent.\n"
            "Return JSON only with keys: normalized_instruction, status, confidence, explanation, warnings, commands.\n"
            "Use only approved commands from the catalog below.\n"
            "Do not invent commands or unsafe free-form actions.\n"
            "If the screen context is unrelated or uncertain, lower confidence or ask for clarification.\n"
            "A screen screenshot is optional evidence, not a continuous stream.\n"
            "Each item in commands must be an object with command_name, inputs, and reason.\n"
            "Use the full command name exactly as written in the catalog.\n"
            "Example JSON:\n"
            "{\n"
            '  "normalized_instruction": "print all today voucher",\n'
            '  "status": "needs_confirmation",\n'
            '  "confidence": 0.92,\n'
            '  "explanation": "Matched the voucher-print workflow.",\n'
            '  "warnings": [],\n'
            '  "commands": [\n'
            "    {\n"
            '      "command_name": "desktop.print_today_vouchers",\n'
            '      "inputs": {"app_name": "voucher_app", "date_from": "today", "date_to": "today"},\n'
            '      "reason": "Print today\'s vouchers through the approved workflow."\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Approved command catalog:\n"
            f"{catalog_text}"
        )
