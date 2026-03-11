from __future__ import annotations

import re
from typing import Any

from core.models import ActionResult, ValidationResult, ValidationRule
from core.utils import render_template


class Validator:
    def __init__(self, observer: Any, file_controller: Any) -> None:
        self.observer = observer
        self.file_controller = file_controller

    def evaluate_rules(
        self,
        rules: list[ValidationRule],
        context: dict[str, Any],
        result: ActionResult | None,
    ) -> list[ValidationResult]:
        return [self.evaluate_rule(rule, context, result) for rule in rules]

    def evaluate_rule(
        self,
        rule: ValidationRule,
        context: dict[str, Any],
        result: ActionResult | None,
    ) -> ValidationResult:
        snapshot = self.observer.snapshot(context)
        args = render_template(rule.args, context)
        kind = rule.kind

        if kind == "ui.has_text":
            expected_text = str(args.get("text") or "")
            haystacks: list[str] = []
            haystacks.extend(snapshot["desktop"].get("texts", []))
            haystacks.append(snapshot["browser"].get("page_text", ""))
            if result is not None:
                haystacks.append(result.message)
                haystacks.extend(str(value) for value in result.observations.values())
            if any(expected_text in haystack for haystack in haystacks):
                return ValidationResult(True, f"Found text '{expected_text}'.")
            return ValidationResult(False, f"Expected text '{expected_text}' was not found.", rule.on_fail.recover_with)

        if kind == "ui.control_exists":
            control = str(args.get("control") or "")
            controls = snapshot["desktop"].get("controls", [])
            if control in controls:
                return ValidationResult(True, f"Control '{control}' exists.")
            return ValidationResult(False, f"Control '{control}' does not exist.", rule.on_fail.recover_with)

        if kind == "browser.url_matches":
            pattern = str(args.get("pattern") or "")
            current_url = snapshot["browser"].get("current_url", "")
            if re.search(pattern, current_url):
                return ValidationResult(True, f"URL matched '{pattern}'.")
            return ValidationResult(False, f"URL '{current_url}' did not match '{pattern}'.", rule.on_fail.recover_with)

        if kind == "files.exists":
            path = str(args.get("path") or "")
            if self.file_controller.exists(path):
                return ValidationResult(True, f"File exists: {path}")
            return ValidationResult(False, f"File does not exist: {path}", rule.on_fail.recover_with)

        if kind == "data.regex_match":
            pattern = str(args.get("pattern") or "")
            value = str(args.get("value") or "")
            if re.search(pattern, value):
                return ValidationResult(True, f"Value '{value}' matched '{pattern}'.")
            return ValidationResult(False, f"Value '{value}' did not match '{pattern}'.", rule.on_fail.recover_with)

        if kind == "vision.ocr_confidence_min":
            minimum = float(args.get("min_confidence") or 0.0)
            confidence = 0.0
            if result is not None:
                confidence = float(result.data.get("ocr_confidence") or result.observations.get("confidence") or 0.0)
            if confidence >= minimum:
                return ValidationResult(True, f"OCR confidence {confidence} >= {minimum}.")
            return ValidationResult(False, f"OCR confidence {confidence} < {minimum}.", rule.on_fail.recover_with)

        return ValidationResult(False, f"Unsupported validation rule '{kind}'.", rule.on_fail.recover_with)
