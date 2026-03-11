from __future__ import annotations

from typing import Any

from core.state_contracts import ScreenContract, ScreenContractRegistry


class StateDetector:
    def __init__(self, registry: ScreenContractRegistry) -> None:
        self.registry = registry

    def detect(self, snapshot: dict[str, Any], *, app_name: str | None = None) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        active_window = str(snapshot.get("active_window") or "")
        controls = self._extract_control_tokens(snapshot)
        texts = self._extract_text_tokens(snapshot)

        for contract in self.registry.list(app_name=app_name):
            candidate = self._score_contract(contract, active_window, controls, texts)
            candidates.append(candidate)

        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        best = candidates[0] if candidates else None
        matched = best is not None and best["confidence"] >= 0.45
        return {
            "status": "matched" if matched else "unmatched",
            "current_screen_id": best["screen_id"] if matched else "",
            "current_screen_confidence": best["confidence"] if best else 0.0,
            "current_screen_title": active_window,
            "available_actions": best["actions"] if best else [],
            "transitions": best["transitions"] if best else {},
            "best_match": best,
            "candidates": candidates[:5],
        }

    def _score_contract(
        self,
        contract: ScreenContract,
        active_window: str,
        controls: set[str],
        texts: list[str],
    ) -> dict[str, Any]:
        score = 0.0
        reasons: list[str] = []
        active_lower = active_window.lower()

        if contract.window_title_contains:
            title_matches = sum(1 for value in contract.window_title_contains if value.lower() in active_lower)
            if title_matches > 0:
                title_score = min(0.35, 0.18 * title_matches)
                score += title_score
                reasons.append(f"Matched {title_matches} window title tokens.")

        if contract.required_controls:
            matched_controls = 0
            for control in contract.required_controls:
                candidates = {
                    token.lower()
                    for token in (control.name, control.type, control.automation_id)
                    if token
                }
                if candidates and candidates & controls:
                    matched_controls += 1
            if matched_controls > 0:
                control_score = min(0.45, 0.45 * (matched_controls / max(1, len(contract.required_controls))))
                score += control_score
                reasons.append(f"Matched {matched_controls} required controls.")

        if contract.required_texts:
            matched_texts = 0
            for expected in contract.required_texts:
                expected_lower = expected.lower()
                if any(expected_lower in text for text in texts):
                    matched_texts += 1
            if matched_texts > 0:
                text_score = min(0.2, 0.2 * (matched_texts / max(1, len(contract.required_texts))))
                score += text_score
                reasons.append(f"Matched {matched_texts} required texts.")

        score += 0.05
        return {
            "app_name": contract.app_name,
            "screen_id": contract.screen_id,
            "confidence": round(min(score, 1.0), 3),
            "actions": list(contract.actions),
            "transitions": dict(contract.transitions),
            "reasons": reasons,
        }

    @staticmethod
    def _extract_control_tokens(snapshot: dict[str, Any]) -> set[str]:
        tokens: set[str] = set()
        for item in snapshot.get("controls", []):
            if isinstance(item, dict):
                for key in ("name", "type", "automation_id", "class_name"):
                    value = str(item.get(key) or "").strip().lower()
                    if value:
                        tokens.add(value)
            else:
                value = str(item).strip().lower()
                if value:
                    tokens.add(value)
        for item in snapshot.get("control_details", []):
            if not isinstance(item, dict):
                continue
            for key in ("name", "type", "automation_id", "class_name"):
                value = str(item.get(key) or "").strip().lower()
                if value:
                    tokens.add(value)
        return tokens

    @staticmethod
    def _extract_text_tokens(snapshot: dict[str, Any]) -> list[str]:
        return [str(item).lower() for item in snapshot.get("texts", []) if str(item).strip()]
