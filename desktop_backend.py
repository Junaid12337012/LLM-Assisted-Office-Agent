from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.runtime import build_services


ARTIFACT_KEYWORDS = (
    "path",
    "file",
    "directory",
    "folder",
)


def _resolve_local_path(base_dir: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (base_dir / candidate)


def _looks_like_artifact_key(key: str) -> bool:
    lowered = key.lower()
    return any(keyword in lowered for keyword in ARTIFACT_KEYWORDS)


def _looks_like_local_path(value: str) -> bool:
    if value.startswith(("http://", "https://")):
        return False
    return any(token in value for token in ("\\", "/", ":")) or value.startswith("data")


def _extract_artifacts(base_dir: Path, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for step in steps:
        payload = step.get("payload") or {}
        for section_name in ("data", "args", "observations"):
            section = payload.get(section_name)
            if not isinstance(section, dict):
                continue
            for key, value in section.items():
                if not isinstance(value, str) or not _looks_like_artifact_key(key) or not _looks_like_local_path(value):
                    continue
                resolved = _resolve_local_path(base_dir, value)
                dedupe_key = (step["step_id"], str(resolved).lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                exists = resolved.exists()
                artifacts.append(
                    {
                        "step_id": step["step_id"],
                        "key": key,
                        "label": f"{step['step_id']}: {key}",
                        "path": str(resolved),
                        "exists": exists,
                        "kind": "directory" if exists and resolved.is_dir() else "file",
                    }
                )
    return artifacts


def _command_to_dict(command: Any) -> dict[str, Any]:
    parameters = []
    for parameter in command.parameters:
        parameters.append(
            {
                "name": parameter.name,
                "type": parameter.type,
                "required": parameter.required,
                "enum": parameter.enum or [],
            }
        )

    example_parts = [f"run {command.name}"]
    for parameter in command.parameters:
        placeholder = f"<{parameter.name}>"
        if parameter.type == "date":
            placeholder = "2026-03-11"
        elif parameter.type == "path":
            placeholder = f"data/{parameter.name}"
        example_parts.append(f"{parameter.name}={placeholder}")

    return {
        "name": command.name,
        "description": command.description,
        "workflow_id": command.workflow_id,
        "risk": command.risk,
        "requires_confirmation": command.requires_confirmation,
        "parameters": parameters,
        "example": " ".join(example_parts),
    }


def _serialize_run_payload(services: Any, outcome: Any) -> dict[str, Any]:
    run = services.memory_store.get_run(outcome.run_id) if outcome.run_id else None
    steps = services.memory_store.list_step_logs(outcome.run_id) if outcome.run_id else []
    return {
        "outcome": {
            "run_id": outcome.run_id,
            "status": outcome.status,
            "completed_steps": outcome.completed_steps,
            "summary": outcome.summary,
            "last_error": outcome.last_error,
        },
        "run": run,
        "steps": steps,
        "artifacts": _extract_artifacts(services.base_dir, steps),
    }


def command_list(_args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    return {
        "commands": [_command_to_dict(command) for command in services.registry.list_commands()],
    }


def command_runs(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    return {
        "runs": services.memory_store.list_runs(limit=args.limit, status=args.status, query=args.query),
    }


def command_run_details(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    run = services.memory_store.get_run(args.run_id)
    if run is None:
        raise SystemExit(f"Run {args.run_id} was not found.")
    steps = services.memory_store.list_step_logs(args.run_id)
    return {
        "run": run,
        "steps": steps,
        "artifacts": _extract_artifacts(services.base_dir, steps),
    }


def command_dashboard(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    return {
        "dashboard": services.memory_store.dashboard_snapshot(limit=args.limit),
    }


def command_run(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    command, inputs = services.registry.parse_invocation(args.raw_command)
    outcome = services.engine.run(
        command,
        inputs,
        safe_mode=args.safe_mode,
        confirmation_handler=(lambda _message: True) if args.confirm_risky else None,
    )
    return _serialize_run_payload(services, outcome)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Desktop backend bridge for the office automation platform.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    list_commands_parser = subparsers.add_parser("list-commands", help="List registered commands.")
    list_commands_parser.set_defaults(handler=command_list)

    list_runs_parser = subparsers.add_parser("list-runs", help="List recent workflow runs.")
    list_runs_parser.add_argument("--limit", type=int, default=20)
    list_runs_parser.add_argument("--status", default="all")
    list_runs_parser.add_argument("--query", default="")
    list_runs_parser.set_defaults(handler=command_runs)

    dashboard_parser = subparsers.add_parser("dashboard", help="Return dashboard summary data for the desktop UI.")
    dashboard_parser.add_argument("--limit", type=int, default=30)
    dashboard_parser.set_defaults(handler=command_dashboard)

    run_details_parser = subparsers.add_parser("run-details", help="Show details for a specific run.")
    run_details_parser.add_argument("--run-id", type=int, required=True)
    run_details_parser.set_defaults(handler=command_run_details)

    run_parser = subparsers.add_parser("run-command", help="Execute a command through the workflow engine.")
    run_parser.add_argument("--raw-command", required=True)
    run_parser.add_argument("--safe-mode", action="store_true")
    run_parser.add_argument("--confirm-risky", action="store_true")
    run_parser.set_defaults(handler=command_run)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = args.handler(args)
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
