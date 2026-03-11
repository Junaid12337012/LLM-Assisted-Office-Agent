from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.models import CommandDefinition, CommandParameter, ConfigurationError
from core.utils import load_json

ALLOWED_PARAM_TYPES = {"string", "int", "date", "path", "enum", "bool"}
ALLOWED_RISKS = {"low", "medium", "high"}
_PARAMETER_PATTERN = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\"[^\"]*\"|'[^']*'|\S+)"
)



def _strip_quotes(raw_value: str) -> str:
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
        return raw_value[1:-1]
    return raw_value



def _coerce_value(parameter: CommandParameter, raw_value: str) -> Any:
    raw_value = _strip_quotes(raw_value)
    if parameter.type in {"string", "date", "path"}:
        value: Any = raw_value
    elif parameter.type == "int":
        value = int(raw_value)
    elif parameter.type == "bool":
        lowered = raw_value.lower()
        if lowered not in {"true", "false", "1", "0", "yes", "no"}:
            raise ConfigurationError(
                f"Parameter '{parameter.name}' expects a boolean, got '{raw_value}'."
            )
        value = lowered in {"true", "1", "yes"}
    elif parameter.type == "enum":
        value = raw_value
    else:
        raise ConfigurationError(f"Unsupported parameter type '{parameter.type}'.")

    if parameter.enum and str(value) not in parameter.enum:
        raise ConfigurationError(
            f"Parameter '{parameter.name}' must be one of {parameter.enum}, got '{value}'."
        )
    return value



def _split_invocation(raw_command: str) -> tuple[str, list[tuple[str, str]]]:
    trimmed = raw_command.strip()
    if not trimmed:
        raise ConfigurationError("Command input is empty.")

    if trimmed.lower().startswith("run "):
        trimmed = trimmed[4:].strip()
    if not trimmed:
        raise ConfigurationError("Command name is missing.")

    parts = trimmed.split(None, 1)
    command_name = parts[0]
    remainder = parts[1] if len(parts) > 1 else ""
    assignments: list[tuple[str, str]] = []
    position = 0

    while position < len(remainder):
        while position < len(remainder) and remainder[position].isspace():
            position += 1
        if position >= len(remainder):
            break

        match = _PARAMETER_PATTERN.match(remainder, position)
        if match is None:
            invalid = remainder[position:].split(None, 1)[0]
            raise ConfigurationError(
                f"Arguments must use key=value format. Invalid token: '{invalid}'."
            )
        assignments.append((match.group("key"), match.group("value")))
        position = match.end()

    return command_name, assignments


class CommandRegistry:
    def __init__(self, commands: dict[str, CommandDefinition]) -> None:
        self._commands = commands

    @classmethod
    def from_file(cls, path: str | Path) -> "CommandRegistry":
        payload = load_json(path)
        if not isinstance(payload, dict) or "commands" not in payload:
            raise ConfigurationError("Command registry must contain a top-level 'commands' list.")

        commands: dict[str, CommandDefinition] = {}
        for item in payload["commands"]:
            command = _parse_command(item)
            commands[command.name] = command
        return cls(commands)

    def get(self, name: str) -> CommandDefinition:
        try:
            return self._commands[name]
        except KeyError as exc:
            known = ", ".join(sorted(self._commands))
            raise ConfigurationError(f"Unknown command '{name}'. Known commands: {known}") from exc

    def list_commands(self) -> list[CommandDefinition]:
        return [self._commands[name] for name in sorted(self._commands)]

    def parse_invocation(self, raw_command: str) -> tuple[CommandDefinition, dict[str, Any]]:
        command_name, assignments = _split_invocation(raw_command)
        command = self.get(command_name)
        values: dict[str, Any] = {}
        parameter_map = {parameter.name: parameter for parameter in command.parameters}

        for key, raw_value in assignments:
            if key not in parameter_map:
                raise ConfigurationError(
                    f"Unknown parameter '{key}' for command '{command.name}'."
                )
            values[key] = _coerce_value(parameter_map[key], raw_value)

        for parameter in command.parameters:
            if parameter.required and parameter.name not in values:
                raise ConfigurationError(
                    f"Missing required parameter '{parameter.name}' for '{command.name}'."
                )
        return command, values



def _parse_command(item: dict[str, Any]) -> CommandDefinition:
    required_fields = {
        "name",
        "description",
        "workflow_id",
        "risk",
        "allowed_targets",
    }
    missing = sorted(required_fields.difference(item))
    if missing:
        raise ConfigurationError(f"Command definition missing fields: {missing}")

    risk = item["risk"]
    if risk not in ALLOWED_RISKS:
        raise ConfigurationError(f"Unsupported risk level '{risk}'.")

    parameters = [_parse_parameter(parameter) for parameter in item.get("parameters", [])]
    allowed_targets = item["allowed_targets"]
    if not isinstance(allowed_targets, dict):
        raise ConfigurationError("allowed_targets must be an object.")

    return CommandDefinition(
        name=item["name"],
        description=item["description"],
        workflow_id=item["workflow_id"],
        parameters=parameters,
        risk=risk,
        allowed_targets={
            key: list(value) for key, value in allowed_targets.items() if isinstance(value, list)
        },
        requires_confirmation=bool(item.get("requires_confirmation", False)),
    )



def _parse_parameter(item: dict[str, Any]) -> CommandParameter:
    required_fields = {"name", "type", "required"}
    missing = sorted(required_fields.difference(item))
    if missing:
        raise ConfigurationError(f"Command parameter missing fields: {missing}")

    parameter_type = item["type"]
    if parameter_type not in ALLOWED_PARAM_TYPES:
        raise ConfigurationError(f"Unsupported parameter type '{parameter_type}'.")

    enum_values = item.get("enum")
    if enum_values is not None and not isinstance(enum_values, list):
        raise ConfigurationError("Parameter enum must be a list when provided.")

    return CommandParameter(
        name=item["name"],
        type=parameter_type,
        required=bool(item["required"]),
        enum=[str(value) for value in enum_values] if enum_values else None,
    )
