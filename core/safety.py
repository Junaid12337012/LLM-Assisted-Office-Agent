from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from core.models import ActionDefinition, CommandDefinition, ConfigurationError, SafetyViolation
from core.utils import load_json

ConfirmationHandler = Callable[[str], bool]


class SafetyGate:
    def __init__(
        self,
        allowed_apps: list[str],
        allowed_domains: list[str],
        default_confirm_risks: list[str],
        safe_mode_confirm_risks: list[str],
    ) -> None:
        self.allowed_apps = allowed_apps
        self.allowed_domains = allowed_domains
        self.default_confirm_risks = set(default_confirm_risks)
        self.safe_mode_confirm_risks = set(safe_mode_confirm_risks)

    @classmethod
    def from_file(cls, path: str | Path) -> "SafetyGate":
        payload = load_json(path)
        if not isinstance(payload, dict):
            raise ConfigurationError("Safety policy file must contain a JSON object.")
        return cls(
            allowed_apps=list(payload.get("allowed_apps", [])),
            allowed_domains=list(payload.get("allowed_domains", [])),
            default_confirm_risks=list(payload.get("default_confirm_risks", ["high"])),
            safe_mode_confirm_risks=list(
                payload.get("safe_mode_confirm_risks", ["medium", "high"])
            ),
        )

    def authorize_command(
        self,
        command: CommandDefinition,
        safe_mode: bool = False,
        confirmation_handler: ConfirmationHandler | None = None,
    ) -> None:
        risks_requiring_confirmation = (
            self.safe_mode_confirm_risks if safe_mode else self.default_confirm_risks
        )
        if command.requires_confirmation or command.risk in risks_requiring_confirmation:
            self._require_confirmation(
                f"Confirm command '{command.name}' (risk={command.risk}).",
                confirmation_handler,
            )

    def authorize_action(
        self,
        command: CommandDefinition,
        action: ActionDefinition,
        resolved_args: dict[str, Any],
        safe_mode: bool = False,
        confirmation_handler: ConfirmationHandler | None = None,
    ) -> None:
        self._check_target_allowlists(command, action, resolved_args)
        risks_requiring_confirmation = (
            self.safe_mode_confirm_risks if safe_mode else self.default_confirm_risks
        )
        if action.risk in risks_requiring_confirmation:
            self._require_confirmation(
                f"Confirm action '{action.id}' ({action.type}, risk={action.risk}).",
                confirmation_handler,
            )

    def _check_target_allowlists(
        self,
        command: CommandDefinition,
        action: ActionDefinition,
        resolved_args: dict[str, Any],
    ) -> None:
        allowed_apps = command.allowed_targets.get("apps") or self.allowed_apps
        allowed_domains = command.allowed_targets.get("domains") or self.allowed_domains

        if action.type.startswith("desktop."):
            window_title = str(
                resolved_args.get("window_title")
                or resolved_args.get("app")
                or resolved_args.get("target")
                or ""
            )
            if allowed_apps and window_title and window_title not in allowed_apps:
                raise SafetyViolation(
                    f"Action '{action.id}' targets window '{window_title}' outside the allowlist."
                )

        if action.type.startswith("browser."):
            url = str(resolved_args.get("url") or "")
            if url:
                host = urlparse(url).netloc
                if allowed_domains and host and host not in allowed_domains:
                    raise SafetyViolation(
                        f"Action '{action.id}' targets domain '{host}' outside the allowlist."
                    )

    @staticmethod
    def _require_confirmation(
        message: str,
        confirmation_handler: ConfirmationHandler | None,
    ) -> None:
        if confirmation_handler is None:
            raise SafetyViolation(message)
        if not confirmation_handler(message):
            raise SafetyViolation(f"User declined: {message}")
