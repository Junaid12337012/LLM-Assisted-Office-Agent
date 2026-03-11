from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from core.command_registry import CommandRegistry
from core.models import CommandDefinition

_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\"[^\"]*\"|'[^']*'|\S+)"
)


def _strip_quotes(raw_value: str) -> str:
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
        return raw_value[1:-1]
    return raw_value


def quote_command_value(value: Any) -> str:
    if value is None:
        return '""'
    text = str(value)
    if not text:
        return '""'
    if re.search(r"[\s=]", text):
        return '"' + text.replace('"', "'") + '"'
    return text


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
            "strict": True,
        }


class ToolRegistry:
    def __init__(self, command_registry: CommandRegistry, base_dir: Path | None = None) -> None:
        self.command_registry = command_registry
        self.base_dir = base_dir or Path.cwd()
        self._command_map = {
            command.name: command for command in self.command_registry.list_commands()
        }

    def list_commands(self) -> list[CommandDefinition]:
        return [self._command_map[name] for name in sorted(self._command_map)]

    def get_command(self, command_name: str) -> CommandDefinition:
        return self._command_map[command_name]

    def has_command(self, command_name: str) -> bool:
        return command_name in self._command_map

    def parse_assignments(self, raw_text: str) -> dict[str, str]:
        values: dict[str, str] = {}
        position = 0
        while position < len(raw_text):
            while position < len(raw_text) and raw_text[position].isspace():
                position += 1
            if position >= len(raw_text):
                break
            match = _ASSIGNMENT_PATTERN.match(raw_text, position)
            if match is None:
                break
            values[match.group("key")] = _strip_quotes(match.group("value"))
            position = match.end()
        return values

    def fill_defaults(
        self,
        command_name: str,
        provided_values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        command = self.get_command(command_name)
        values = {key: value for key, value in (provided_values or {}).items() if value not in {None, ""}}
        missing: list[str] = []
        for parameter in command.parameters:
            if parameter.name in values:
                continue
            default_value = self._get_parameter_default(command_name, parameter.name, values)
            if default_value not in {None, ""}:
                values[parameter.name] = default_value
            elif parameter.required:
                missing.append(parameter.name)
        return values, missing

    def build_raw_command(self, command_name: str, values: dict[str, Any] | None = None) -> str:
        command = self.get_command(command_name)
        ordered_parts = ["run", command.name]
        provided = values or {}
        used: set[str] = set()
        for parameter in command.parameters:
            if parameter.name not in provided:
                continue
            ordered_parts.append(f"{parameter.name}={quote_command_value(provided[parameter.name])}")
            used.add(parameter.name)
        for key in sorted(provided):
            if key in used:
                continue
            ordered_parts.append(f"{key}={quote_command_value(provided[key])}")
        return " ".join(ordered_parts)

    def function_tools(self) -> list[dict[str, Any]]:
        command_enum = sorted(self._command_map)
        return [
            ToolSpec(
                name="run_workflow",
                description="Run one approved workflow command from the automation registry.",
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["command_name", "inputs"],
                    "properties": {
                        "command_name": {"type": "string", "enum": command_enum},
                        "inputs": {"type": "object"},
                    },
                },
            ).to_dict(),
            ToolSpec(
                name="search_run_history",
                description="Search recent workflow runs for matching commands or failures.",
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "status": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                },
            ).to_dict(),
            ToolSpec(
                name="review_queue",
                description="Inspect pending review items before asking the user to resolve them.",
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "status": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                },
            ).to_dict(),
        ]

    def _get_parameter_default(
        self,
        command_name: str,
        parameter_name: str,
        existing_values: dict[str, Any],
    ) -> Any:
        today = str(existing_values.get("run_date") or date.today().isoformat())
        match f"{command_name}::{parameter_name}":
            case "mvp.start_day::run_date":
                return today
            case "mvp.start_day::note_path":
                return f"data/evidence/notes/start_day_{today}.md"
            case "mvp.note::run_date":
                return today
            case "mvp.note::note_title":
                return "Quick Note"
            case "mvp.note::note_path":
                return f"data/evidence/notes/quick_note_{today}.txt"
            case "mvp.download_report::run_date":
                return today
            case "mvp.download_report::download_dir":
                return "data/evidence/exports"
            case "mvp.download_report::export_dir":
                return "data/evidence/exports"
            case "browser.download_daily_report::download_dir":
                return "data/evidence/exports"
            case "browser.download_daily_report::export_dir":
                return "data/evidence/exports"
            case "browser.download_daily_report::run_date":
                return today
            case "reports.end_of_day_summary::run_date":
                return today
            case "reports.end_of_day_summary::export_path":
                return f"data/evidence/exports/summary_{today}.json"
            case "mvp.end_day::run_date":
                return today
            case "mvp.end_day::summary_output":
                return f"data/evidence/exports/end_of_day_{today}.json"
            case "portal.upload_latest_file::source_dir":
                return "data/evidence/exports"
            case "desktop.print_today_vouchers::app_name":
                return "voucher_app"
            case "desktop.print_today_vouchers::date_from":
                return "today"
            case "desktop.print_today_vouchers::date_to":
                return "today"
            case "phase2.read_invoice_id::result_path":
                image_path = existing_values.get("image_path")
                if not image_path:
                    return f"data/evidence/review/invoice_result_{today}.txt"
                stem = Path(str(image_path)).stem or "invoice"
                return f"data/evidence/review/{stem}_result.txt"
            case _:
                return None
