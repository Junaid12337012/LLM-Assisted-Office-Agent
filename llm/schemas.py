from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PlannedCommand:
    tool_name: str
    command_name: str
    workflow_id: str
    raw_command: str
    inputs: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    risk: str = "low"
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "command_name": self.command_name,
            "workflow_id": self.workflow_id,
            "raw_command": self.raw_command,
            "inputs": dict(self.inputs),
            "reason": self.reason,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(slots=True)
class AssistantPlan:
    instruction: str
    normalized_instruction: str
    status: str
    confidence: float
    explanation: str
    commands: list[PlannedCommand] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    source: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "normalized_instruction": self.normalized_instruction,
            "status": self.status,
            "confidence": round(float(self.confidence), 3),
            "explanation": self.explanation,
            "warnings": list(self.warnings),
            "missing_parameters": list(self.missing_parameters),
            "requires_confirmation": self.requires_confirmation,
            "source": self.source,
            "commands": [command.to_dict() for command in self.commands],
        }


def plan_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "instruction",
            "normalized_instruction",
            "status",
            "confidence",
            "explanation",
            "requires_confirmation",
            "missing_parameters",
            "warnings",
            "commands",
        ],
        "properties": {
            "instruction": {"type": "string"},
            "normalized_instruction": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["ready", "needs_confirmation", "needs_clarification", "unmatched"],
            },
            "confidence": {"type": "number"},
            "explanation": {"type": "string"},
            "requires_confirmation": {"type": "boolean"},
            "missing_parameters": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "tool_name",
                        "command_name",
                        "workflow_id",
                        "raw_command",
                        "inputs",
                        "reason",
                        "risk",
                        "requires_confirmation",
                    ],
                    "properties": {
                        "tool_name": {"type": "string"},
                        "command_name": {"type": "string"},
                        "workflow_id": {"type": "string"},
                        "raw_command": {"type": "string"},
                        "inputs": {"type": "object"},
                        "reason": {"type": "string"},
                        "risk": {"type": "string"},
                        "requires_confirmation": {"type": "boolean"},
                    },
                },
            },
        },
    }
