from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from core.models import ActionDefinition, FailurePolicy, RecoveryResult
from core.utils import load_json

ConfirmationHandler = Callable[[str], bool]


class ErrorSignatureRegistry:
    def __init__(self, signatures: list[dict[str, Any]]) -> None:
        self.signatures = signatures

    @classmethod
    def from_file(cls, path: str | Path) -> "ErrorSignatureRegistry":
        payload = load_json(path)
        return cls(list(payload.get("error_signatures", [])))

    def get(self, signature_id: str) -> dict[str, Any] | None:
        for signature in self.signatures:
            if signature.get("id") == signature_id:
                return signature
        return None

    def match(self, candidate: str | None, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        if not candidate:
            return None

        browser_host = urlparse(snapshot.get("browser", {}).get("current_url", "")).netloc
        active_window = snapshot.get("desktop", {}).get("active_window", "")
        normalized = candidate.lower()

        for signature in self.signatures:
            matcher = signature.get("match", {})
            scope = signature.get("scope", {})
            if scope.get("app") and scope.get("app") != active_window:
                continue
            if scope.get("domain") and scope.get("domain") != browser_host:
                continue

            match_type = matcher.get("type")
            value = str(matcher.get("value") or "")
            if match_type == "ui.text_contains" and value.lower() in normalized:
                return signature
            if match_type == "ui.text_regex" and re.search(value, candidate, re.IGNORECASE):
                return signature
        return None


class RecoveryEngine:
    def __init__(self, signature_registry: ErrorSignatureRegistry) -> None:
        self.signature_registry = signature_registry

    def plan_for_failure(
        self,
        failure_policy: FailurePolicy,
        candidate: str | None,
        snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        signature = None
        if failure_policy.recover_with:
            signature = self.signature_registry.get(failure_policy.recover_with)
        if signature is None:
            signature = self.signature_registry.match(candidate, snapshot)
        if signature is None:
            return []
        return list(signature.get("recovery_plan", []))

    def attempt_recovery(
        self,
        plan: list[dict[str, Any]],
        executor: Any,
        context: dict[str, Any],
        memory_store: Any,
        run_id: int,
        confirmation_handler: ConfirmationHandler | None = None,
    ) -> RecoveryResult:
        if not plan:
            return RecoveryResult(False, message="No recovery plan available.")

        goto_step: str | None = None
        for item in plan:
            action_type = str(item.get("type") or "")
            args = dict(item.get("args") or {})

            if action_type == "workflow.goto_step":
                goto_step = str(args.get("step_id") or "")
                continue

            if action_type == "escalate.user_confirm":
                message = str(args.get("message") or "Confirm recovery.")
                if confirmation_handler is None or not confirmation_handler(message):
                    return RecoveryResult(False, stop_run=True, message=message)
                memory_store.log_event("warning", "Recovery confirmed by user.", {"message": message}, run_id)
                continue

            recovery_action = ActionDefinition(
                id=f"recovery::{action_type}",
                type=action_type,
                args=args,
                on_fail=FailurePolicy(strategy="abort"),
            )
            result = executor.execute(recovery_action, context)
            memory_store.log_event(
                "warning",
                "Recovery action executed.",
                {"action_type": action_type, "success": result.success, "message": result.message},
                run_id,
            )
            if not result.success:
                return RecoveryResult(False, message=result.message)
            context.update(result.data)

        return RecoveryResult(True, goto_step=goto_step, message="Recovery completed.")
