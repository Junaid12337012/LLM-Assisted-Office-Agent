from __future__ import annotations

from typing import Any


class ScreenModel:
    def analyze(
        self,
        snapshot: dict[str, Any],
        templates: list[dict[str, Any]],
        *,
        app_name: str | None = None,
    ) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        active_window = str(snapshot.get("active_window") or "")
        controls = {str(item).lower() for item in snapshot.get("controls", [])}
        texts = [str(item).lower() for item in snapshot.get("texts", [])]

        for template in templates:
            if app_name and template.get("app_name") != app_name:
                continue
            score = 0.0
            reasons: list[str] = []
            window_title = str(template.get("window_title") or "")
            if window_title:
                lowered = window_title.lower()
                active_lowered = active_window.lower()
                if lowered == active_lowered:
                    score += 0.45
                    reasons.append("Window title exact match.")
                elif lowered in active_lowered or active_lowered in lowered:
                    score += 0.3
                    reasons.append("Window title partial match.")

            expected_controls = {str(item).lower() for item in template.get("expected_controls", [])}
            if expected_controls:
                overlap = len(expected_controls & controls)
                if overlap > 0:
                    control_score = min(0.35, 0.35 * (overlap / max(1, len(expected_controls))))
                    score += control_score
                    reasons.append(f"Matched {overlap} expected controls.")

            expected_texts = [str(item).lower() for item in template.get("expected_texts", [])]
            matched_texts = 0
            for expected_text in expected_texts:
                if any(expected_text in text for text in texts):
                    matched_texts += 1
            if matched_texts > 0:
                text_score = min(0.2, 0.2 * (matched_texts / max(1, len(expected_texts))))
                score += text_score
                reasons.append(f"Matched {matched_texts} expected texts.")

            if app_name and template.get("app_name") == app_name:
                score += 0.05

            candidates.append(
                {
                    "template_id": template.get("template_id"),
                    "app_name": template.get("app_name"),
                    "screen_name": template.get("screen_name"),
                    "confidence": round(min(score, 1.0), 3),
                    "reasons": reasons,
                    "capture_path": template.get("capture_path"),
                    "region_count": len(template.get("regions", [])),
                }
            )

        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        best = candidates[0] if candidates else None
        status = "matched" if best and best["confidence"] >= 0.45 else "unmatched"
        return {
            "status": status,
            "best_match": best,
            "candidates": candidates[:5],
            "snapshot": snapshot,
        }
