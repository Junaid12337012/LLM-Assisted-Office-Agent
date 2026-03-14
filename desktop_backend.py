from __future__ import annotations

import argparse
import json
import os
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


def _serialize_plan(plan: Any) -> dict[str, Any]:
    return plan.to_dict() if hasattr(plan, "to_dict") else dict(plan)


def _assistant_outcome(
    status: str,
    summary: dict[str, Any] | None = None,
    *,
    last_error: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary or {},
        "last_error": last_error,
    }


def _parse_json_arg(raw_value: str, *, default: Any) -> Any:
    if not raw_value:
        return default
    return json.loads(raw_value)


def _read_bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _serialize_session_payload(details: dict[str, Any]) -> dict[str, Any]:
    return {
        "session": details["session"],
        "tasks": details["tasks"],
        "exceptions": details["exceptions"],
        "checkpoints": details.get("checkpoints", []),
        "summary": details["summary"],
        "summary_text": details["summary_text"],
    }


def _manual_session_tasks(services: Any, raw_commands: list[str]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index, raw_command in enumerate(raw_commands, start=1):
        command, inputs = services.registry.parse_invocation(raw_command)
        tasks.append(
            {
                "title": f"Task {index}: {command.name}",
                "command_name": command.name,
                "workflow_id": command.workflow_id,
                "inputs": inputs,
                "priority": "normal",
                "max_retries": 1,
                "requires_confirmation": command.requires_confirmation,
            }
        )
    return tasks


def execute_assistant_plan(
    services: Any,
    plan: Any,
    *,
    safe_mode: bool = False,
    confirm_risky: bool = False,
    confirm_plan: bool = False,
) -> dict[str, Any]:
    if plan.status == "unmatched":
        return {
            "plan": _serialize_plan(plan),
            "outcome": _assistant_outcome(
                "unmatched",
                {"message": plan.explanation},
                last_error=plan.explanation,
            ),
            "runs": [],
        }

    if plan.status == "needs_clarification":
        return {
            "plan": _serialize_plan(plan),
            "outcome": _assistant_outcome(
                "needs_clarification",
                {"missing_parameters": plan.missing_parameters, "warnings": plan.warnings},
                last_error=plan.explanation,
            ),
            "runs": [],
        }

    if plan.status == "needs_confirmation" and not confirm_plan:
        return {
            "plan": _serialize_plan(plan),
            "outcome": _assistant_outcome(
                "needs_confirmation",
                {"warnings": plan.warnings, "message": plan.explanation},
                last_error=plan.explanation,
            ),
            "runs": [],
        }

    run_payloads: list[dict[str, Any]] = []
    aggregate_status = "completed"
    completed_commands = 0
    last_error: str | None = None
    confirmation_handler = (lambda _message: True) if (confirm_risky or confirm_plan) else None

    for planned_command in plan.commands:
        command, inputs = services.registry.parse_invocation(planned_command.raw_command)
        outcome = services.engine.run(
            command,
            inputs,
            safe_mode=safe_mode,
            confirmation_handler=confirmation_handler,
        )
        payload = _serialize_run_payload(services, outcome)
        run_payloads.append(payload)
        if outcome.status in {"completed", "stopped"}:
            completed_commands += 1
            continue
        aggregate_status = "failed" if completed_commands == 0 else "partial"
        last_error = outcome.last_error or f"{planned_command.command_name} ended with {outcome.status}."
        break

    return {
        "plan": _serialize_plan(plan),
        "outcome": _assistant_outcome(
            aggregate_status,
            {
                "planned_commands": [command.raw_command for command in plan.commands],
                "completed_commands": completed_commands,
                "total_commands": len(plan.commands),
                "warnings": plan.warnings,
            },
            last_error=last_error,
        ),
        "runs": run_payloads,
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


def command_review_list(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    return {
        "items": services.review_queue.list_items(status=args.status, limit=args.limit) if services.review_queue else [],
    }


def command_review_resolve(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.review_queue is None:
        raise SystemExit("Review queue is not available.")
    item = services.review_queue.resolve(
        review_id=args.review_id,
        resolution=args.resolution,
        corrected_value=args.corrected_value,
        notes=args.notes,
    )
    if item is None:
        raise SystemExit(f"Review item {args.review_id} was not found.")
    return {"item": item}


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


def command_plan_instruction(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if getattr(args, "local_model", False) or _read_bool_env("PREFER_LOCAL_AGENT"):
        local_agent = _build_local_agent(services)
        plan = local_agent.plan(
            args.instruction,
            include_screen=getattr(args, "with_screen", False) or _read_bool_env("LOCAL_AGENT_WITH_SCREEN"),
            force_screenshot=getattr(args, "force_screenshot", False),
        )
        return {"plan": _serialize_plan(plan), "screen_context": local_agent.last_screen_context}

    if services.assistant is None:
        raise SystemExit("Assistant planner is not available.")
    plan = services.assistant.plan(args.instruction)
    return {"plan": _serialize_plan(plan)}


def command_run_instruction(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if getattr(args, "local_model", False) or _read_bool_env("PREFER_LOCAL_AGENT"):
        local_agent = _build_local_agent(services)
        plan = local_agent.plan(
            args.instruction,
            include_screen=getattr(args, "with_screen", False) or _read_bool_env("LOCAL_AGENT_WITH_SCREEN"),
            force_screenshot=getattr(args, "force_screenshot", False),
        )
        payload = execute_assistant_plan(
            services,
            plan,
            safe_mode=args.safe_mode,
            confirm_risky=args.confirm_risky,
            confirm_plan=args.confirm_plan,
        )
        payload["screen_context"] = local_agent.last_screen_context
        return payload

    if services.assistant is None:
        raise SystemExit("Assistant planner is not available.")
    plan = services.assistant.plan(args.instruction)
    return execute_assistant_plan(
        services,
        plan,
        safe_mode=args.safe_mode,
        confirm_risky=args.confirm_risky,
        confirm_plan=args.confirm_plan,
    )


def _build_local_agent(services: Any) -> Any:
    if services.assistant is None:
        raise SystemExit("Assistant planner is not available.")
    from llm.local_agent import LocalAgentPlanner
    from llm.local_openai_client import LocalOpenAICompatibleClient
    from llm.screen_context import ScreenContextCollector

    tool_registry = services.assistant.tool_registry
    screen_collector = ScreenContextCollector(
        services.engine.executor.desktop_controller,
        services.engine.executor.vision_capture_controller,
        base_dir=services.base_dir,
    )
    return LocalAgentPlanner(
        LocalOpenAICompatibleClient.from_env(),
        tool_registry,
        screen_collector,
        fallback_planner=services.assistant,
    )


def command_local_agent_plan(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    local_agent = _build_local_agent(services)
    plan = local_agent.plan(
        args.instruction,
        include_screen=args.with_screen,
        force_screenshot=args.force_screenshot,
    )
    return {
        "plan": _serialize_plan(plan),
        "screen_context": local_agent.last_screen_context,
    }


def command_local_agent_run(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    local_agent = _build_local_agent(services)
    plan = local_agent.plan(
        args.instruction,
        include_screen=args.with_screen,
        force_screenshot=args.force_screenshot,
    )
    payload = execute_assistant_plan(
        services,
        plan,
        safe_mode=args.safe_mode,
        confirm_risky=args.confirm_risky,
        confirm_plan=args.confirm_plan,
    )
    payload["screen_context"] = local_agent.last_screen_context
    return payload


def command_operator_dashboard(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    return {"dashboard": services.operator_session_manager.dashboard(limit=args.limit)}


def command_operator_list_sessions(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    return {
        "sessions": services.operator_session_manager.list_sessions(limit=args.limit, status=args.status)
    }


def command_operator_create_session(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    if args.instruction:
        details = services.operator_session_manager.create_session_from_instruction(
            args.instruction,
            session_name=args.name,
        )
        return {
            "session": details["session"],
            "tasks": details["tasks"],
            "exceptions": details["exceptions"],
            "plan": details.get("plan"),
        }
    if args.raw_command:
        tasks = _manual_session_tasks(services, args.raw_command)
        details = services.operator_session_manager.create_session(
            args.name or "Manual operator session",
            tasks,
            source="manual",
            metadata={"raw_commands": args.raw_command},
        )
        return _serialize_session_payload(details)
    raise SystemExit("Provide --instruction or at least one --raw-command.")


def command_operator_session_details(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    return _serialize_session_payload(
        services.operator_session_manager.get_session_details(args.session_id)
    )


def command_operator_run_next(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    return {
        "result": services.operator_session_manager.run_next_task(
            args.session_id,
            safe_mode=args.safe_mode,
            confirm_risky=args.confirm_risky,
            confirm_plan=args.confirm_plan,
        )
    }


def command_operator_run_session(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    details = services.operator_session_manager.run_session(
        args.session_id,
        safe_mode=args.safe_mode,
        confirm_risky=args.confirm_risky,
        confirm_plan=args.confirm_plan,
        max_tasks=args.max_tasks,
    )
    payload = _serialize_session_payload(details)
    payload["executions"] = details["executions"]
    return payload


def command_operator_pause_session(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    return _serialize_session_payload(services.operator_session_manager.pause_session(args.session_id))


def command_operator_list_exceptions(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_exception_queue is None:
        raise SystemExit("Operator exception queue is not available.")
    return {
        "exceptions": services.operator_exception_queue.list(
            session_id=args.session_id,
            status=args.status,
            limit=args.limit,
        )
    }


def command_operator_resolve_exception(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.operator_session_manager is None:
        raise SystemExit("Operator session manager is not available.")
    item = services.operator_session_manager.resolve_exception(
        args.exception_id,
        resolution=args.resolution,
        notes=args.notes,
    )
    return {"exception": item}


def command_training_capture(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.training_store is None:
        raise SystemExit("Training store is not available.")
    controller = getattr(services.engine.executor, "vision_capture_controller", None)
    if controller is None:
        raise SystemExit("Vision capture controller is not available.")
    capture_path = args.path or str(
        services.training_store.build_capture_path(
            args.app_name or "desktop_app",
            args.screen_name or "screen",
        )
    )
    result = controller.perform(
        "vision.capture_screenshot",
        {
            "path": capture_path,
            "left": args.left,
            "top": args.top,
            "width": args.width,
            "height": args.height,
        },
    )
    return {
        "capture": {
            "success": result.success,
            "message": result.message,
            "path": result.data.get("screenshot_path"),
            "capture_area": result.data.get("capture_area"),
        }
    }


def command_training_save_template(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.training_store is None:
        raise SystemExit("Training store is not available.")
    template = services.training_store.save_template(
        app_name=args.app_name,
        screen_name=args.screen_name,
        window_title=args.window_title,
        capture_path=args.capture_path,
        regions=_parse_json_arg(args.regions_json, default=[]),
        expected_controls=_parse_json_arg(args.expected_controls_json, default=[]),
        expected_texts=_parse_json_arg(args.expected_texts_json, default=[]),
        notes=args.notes,
        template_id=args.template_id or None,
    )
    return {"template": template}


def command_training_list_templates(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.training_store is None:
        raise SystemExit("Training store is not available.")
    return {"templates": services.training_store.list_templates(app_name=args.app_name or None)}


def command_training_get_template(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.training_store is None:
        raise SystemExit("Training store is not available.")
    template = services.training_store.get_template(args.template_id)
    if template is None:
        raise SystemExit(f"Template {args.template_id} was not found.")
    return {"template": template}


def command_training_analyze_screen(args: argparse.Namespace) -> dict[str, Any]:
    services = build_services()
    if services.training_store is None or services.screen_model is None:
        raise SystemExit("Training analyzer is not available.")
    templates = services.training_store.list_templates(app_name=args.app_name or None)
    snapshot = services.engine.executor.desktop_controller.snapshot()
    analysis = services.screen_model.analyze(snapshot, templates, app_name=args.app_name or None)
    return {"analysis": analysis}


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

    review_list_parser = subparsers.add_parser("list-review-items", help="List pending or resolved review items.")
    review_list_parser.add_argument("--status", default="pending")
    review_list_parser.add_argument("--limit", type=int, default=50)
    review_list_parser.set_defaults(handler=command_review_list)

    review_resolve_parser = subparsers.add_parser("resolve-review-item", help="Resolve a review queue item.")
    review_resolve_parser.add_argument("--review-id", type=int, required=True)
    review_resolve_parser.add_argument("--resolution", required=True)
    review_resolve_parser.add_argument("--corrected-value", default=None)
    review_resolve_parser.add_argument("--notes", default="")
    review_resolve_parser.set_defaults(handler=command_review_resolve)

    run_details_parser = subparsers.add_parser("run-details", help="Show details for a specific run.")
    run_details_parser.add_argument("--run-id", type=int, required=True)
    run_details_parser.set_defaults(handler=command_run_details)

    run_parser = subparsers.add_parser("run-command", help="Execute a command through the workflow engine.")
    run_parser.add_argument("--raw-command", required=True)
    run_parser.add_argument("--safe-mode", action="store_true")
    run_parser.add_argument("--confirm-risky", action="store_true")
    run_parser.set_defaults(handler=command_run)

    plan_parser = subparsers.add_parser("plan-instruction", help="Map a natural-language instruction to safe workflow commands.")
    plan_parser.add_argument("--instruction", required=True)
    plan_parser.add_argument("--local-model", action="store_true")
    plan_parser.add_argument("--with-screen", action="store_true")
    plan_parser.add_argument("--force-screenshot", action="store_true")
    plan_parser.set_defaults(handler=command_plan_instruction)

    run_instruction_parser = subparsers.add_parser("run-instruction", help="Plan and run a natural-language instruction safely.")
    run_instruction_parser.add_argument("--instruction", required=True)
    run_instruction_parser.add_argument("--local-model", action="store_true")
    run_instruction_parser.add_argument("--with-screen", action="store_true")
    run_instruction_parser.add_argument("--force-screenshot", action="store_true")
    run_instruction_parser.add_argument("--safe-mode", action="store_true")
    run_instruction_parser.add_argument("--confirm-risky", action="store_true")
    run_instruction_parser.add_argument("--confirm-plan", action="store_true")
    run_instruction_parser.set_defaults(handler=command_run_instruction)

    local_plan_parser = subparsers.add_parser("local-agent-plan", help="Plan an instruction with a local OpenAI-compatible model.")
    local_plan_parser.add_argument("--instruction", required=True)
    local_plan_parser.add_argument("--with-screen", action="store_true")
    local_plan_parser.add_argument("--force-screenshot", action="store_true")
    local_plan_parser.set_defaults(handler=command_local_agent_plan)

    local_run_parser = subparsers.add_parser("local-agent-run", help="Plan and run an instruction with a local OpenAI-compatible model.")
    local_run_parser.add_argument("--instruction", required=True)
    local_run_parser.add_argument("--with-screen", action="store_true")
    local_run_parser.add_argument("--force-screenshot", action="store_true")
    local_run_parser.add_argument("--safe-mode", action="store_true")
    local_run_parser.add_argument("--confirm-risky", action="store_true")
    local_run_parser.add_argument("--confirm-plan", action="store_true")
    local_run_parser.set_defaults(handler=command_local_agent_run)

    operator_dashboard_parser = subparsers.add_parser("operator-dashboard", help="Return operator-mode dashboard data.")
    operator_dashboard_parser.add_argument("--limit", type=int, default=10)
    operator_dashboard_parser.set_defaults(handler=command_operator_dashboard)

    operator_sessions_parser = subparsers.add_parser("operator-list-sessions", help="List operator sessions.")
    operator_sessions_parser.add_argument("--status", default="all")
    operator_sessions_parser.add_argument("--limit", type=int, default=25)
    operator_sessions_parser.set_defaults(handler=command_operator_list_sessions)

    operator_create_parser = subparsers.add_parser("operator-create-session", help="Create an operator session from an instruction or manual commands.")
    operator_create_parser.add_argument("--name", default="")
    operator_create_parser.add_argument("--instruction", default="")
    operator_create_parser.add_argument("--raw-command", action="append", default=[])
    operator_create_parser.set_defaults(handler=command_operator_create_session)

    operator_details_parser = subparsers.add_parser("operator-session-details", help="Show details for one operator session.")
    operator_details_parser.add_argument("--session-id", type=int, required=True)
    operator_details_parser.set_defaults(handler=command_operator_session_details)

    operator_run_next_parser = subparsers.add_parser("operator-run-next", help="Run the next queued task in an operator session.")
    operator_run_next_parser.add_argument("--session-id", type=int, required=True)
    operator_run_next_parser.add_argument("--safe-mode", action="store_true")
    operator_run_next_parser.add_argument("--confirm-risky", action="store_true")
    operator_run_next_parser.add_argument("--confirm-plan", action="store_true")
    operator_run_next_parser.set_defaults(handler=command_operator_run_next)

    operator_run_session_parser = subparsers.add_parser("operator-run-session", help="Process pending tasks in an operator session.")
    operator_run_session_parser.add_argument("--session-id", type=int, required=True)
    operator_run_session_parser.add_argument("--safe-mode", action="store_true")
    operator_run_session_parser.add_argument("--confirm-risky", action="store_true")
    operator_run_session_parser.add_argument("--confirm-plan", action="store_true")
    operator_run_session_parser.add_argument("--max-tasks", type=int, default=None)
    operator_run_session_parser.set_defaults(handler=command_operator_run_session)

    operator_pause_parser = subparsers.add_parser("operator-pause-session", help="Pause an operator session between tasks.")
    operator_pause_parser.add_argument("--session-id", type=int, required=True)
    operator_pause_parser.set_defaults(handler=command_operator_pause_session)

    operator_exceptions_parser = subparsers.add_parser("operator-list-exceptions", help="List operator exceptions.")
    operator_exceptions_parser.add_argument("--session-id", type=int, default=None)
    operator_exceptions_parser.add_argument("--status", default="open")
    operator_exceptions_parser.add_argument("--limit", type=int, default=50)
    operator_exceptions_parser.set_defaults(handler=command_operator_list_exceptions)

    operator_resolve_parser = subparsers.add_parser("operator-resolve-exception", help="Resolve an operator exception.")
    operator_resolve_parser.add_argument("--exception-id", type=int, required=True)
    operator_resolve_parser.add_argument("--resolution", required=True)
    operator_resolve_parser.add_argument("--notes", default="")
    operator_resolve_parser.set_defaults(handler=command_operator_resolve_exception)

    training_capture_parser = subparsers.add_parser("training-capture-screen", help="Capture a real desktop screenshot for screen training.")
    training_capture_parser.add_argument("--app-name", default="desktop_app")
    training_capture_parser.add_argument("--screen-name", default="screen")
    training_capture_parser.add_argument("--path", default="")
    training_capture_parser.add_argument("--left", type=int, default=0)
    training_capture_parser.add_argument("--top", type=int, default=0)
    training_capture_parser.add_argument("--width", type=int, default=0)
    training_capture_parser.add_argument("--height", type=int, default=0)
    training_capture_parser.set_defaults(handler=command_training_capture)

    training_save_parser = subparsers.add_parser("training-save-template", help="Save a labeled screen template.")
    training_save_parser.add_argument("--template-id", default="")
    training_save_parser.add_argument("--app-name", required=True)
    training_save_parser.add_argument("--screen-name", required=True)
    training_save_parser.add_argument("--window-title", default="")
    training_save_parser.add_argument("--capture-path", default="")
    training_save_parser.add_argument("--regions-json", default="[]")
    training_save_parser.add_argument("--expected-controls-json", default="[]")
    training_save_parser.add_argument("--expected-texts-json", default="[]")
    training_save_parser.add_argument("--notes", default="")
    training_save_parser.set_defaults(handler=command_training_save_template)

    training_list_parser = subparsers.add_parser("training-list-templates", help="List saved screen templates.")
    training_list_parser.add_argument("--app-name", default="")
    training_list_parser.set_defaults(handler=command_training_list_templates)

    training_get_parser = subparsers.add_parser("training-get-template", help="Load one saved screen template.")
    training_get_parser.add_argument("--template-id", required=True)
    training_get_parser.set_defaults(handler=command_training_get_template)

    training_analyze_parser = subparsers.add_parser("training-analyze-screen", help="Analyze the current desktop snapshot against taught templates.")
    training_analyze_parser.add_argument("--app-name", default="")
    training_analyze_parser.set_defaults(handler=command_training_analyze_screen)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = args.handler(args)
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
