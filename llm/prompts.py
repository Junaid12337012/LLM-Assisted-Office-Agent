from __future__ import annotations

import json

from llm.schemas import plan_response_schema
from llm.tool_registry import ToolRegistry


def build_interpreter_prompt(tool_registry: ToolRegistry) -> str:
    command_lines = []
    for command in tool_registry.list_commands():
        parameter_names = ", ".join(parameter.name for parameter in command.parameters) or "no parameters"
        command_lines.append(
            f"- {command.name}: {command.description} | risk={command.risk} | params={parameter_names}"
        )
    schema_text = json.dumps(plan_response_schema(), indent=2)
    return (
        "You map desktop-office instructions to the user's approved workflow catalog. "
        "Only choose registered commands. Fill obvious defaults such as today's date or the "
        "default exports folder. If confidence is low or required values are missing, do not "
        "invent steps; return a clarification request.\n\n"
        "Approved workflows:\n"
        + "\n".join(command_lines)
        + "\n\nReturn JSON that matches this schema:\n"
        + schema_text
    )


def build_planner_prompt() -> str:
    return (
        "Plan only with approved workflow tools. Prefer deterministic commands over free-form "
        "actions, require confirmation for risky or low-confidence work, and explain why each "
        "workflow step was chosen."
    )
