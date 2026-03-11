from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ConfidencePolicy:
    auto_run_threshold: float = 0.9
    confirm_threshold: float = 0.65

    def clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def classify(
        self,
        confidence: float,
        *,
        missing_parameters: list[str] | None = None,
        requires_confirmation: bool = False,
    ) -> str:
        if missing_parameters:
            return "needs_clarification"
        if requires_confirmation:
            return "needs_confirmation"
        if confidence >= self.auto_run_threshold:
            return "ready"
        if confidence >= self.confirm_threshold:
            return "needs_confirmation"
        return "needs_clarification"
