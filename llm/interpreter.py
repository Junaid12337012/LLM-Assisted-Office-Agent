from __future__ import annotations

import re
from dataclasses import dataclass

from llm.schemas import AssistantPlan, PlannedCommand
from llm.tool_registry import ToolRegistry

_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_PATH_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/][^\s\"]+|\.?[\\/][^\s\"]+|data[\\/][^\s\"]+))"
)


@dataclass(slots=True)
class _Candidate:
    command_name: str
    confidence: float
    reason: str
    provided_values: dict[str, str]


class InstructionInterpreter:
    def __init__(self, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry
        self._command_keywords = {
            "mvp.start_day": {"start", "begin", "morning", "office", "work", "day"},
            "mvp.note": {"note", "remember", "memo", "write", "quick"},
            "mvp.download_report": {"download", "report", "reports", "latest", "daily"},
            "mvp.end_day": {"end", "finish", "close", "summary", "final", "report"},
            "workspace.open_all": {"workspace", "open", "portal", "home"},
            "desktop.demo_notepad": {"notepad", "editor", "text"},
            "desktop.demo_paint": {"paint", "drawing", "demo"},
            "browser.download_daily_report": {"browser", "download", "report", "daily"},
            "portal.upload_latest_file": {"upload", "portal", "latest", "file", "submit"},
            "desktop.check_entries": {"check", "entry", "entries", "pending", "exceptions"},
            "desktop.print_today_vouchers": {"print", "voucher", "vouchers", "today", "date"},
            "reports.end_of_day_summary": {"summary", "export", "report", "day"},
            "phase2.read_invoice_id": {"invoice", "ocr", "image", "read", "extract", "document"},
        }

    def interpret(self, instruction: str) -> AssistantPlan:
        raw_instruction = instruction.strip()
        if not raw_instruction:
            return AssistantPlan(
                instruction=instruction,
                normalized_instruction="",
                status="needs_clarification",
                confidence=0.0,
                explanation="Type a natural instruction or a direct workflow command.",
            )

        normalized = self._normalize(raw_instruction)
        for resolver in (
            self._maybe_direct_command,
            self._maybe_bundle,
            self._maybe_note,
            self._maybe_invoice,
            self._maybe_print_vouchers,
            self._best_single_command,
        ):
            plan = resolver(raw_instruction, normalized)
            if plan is not None:
                return plan

        return AssistantPlan(
            instruction=raw_instruction,
            normalized_instruction=normalized,
            status="unmatched",
            confidence=0.18,
            explanation="I could not safely match that request to an approved workflow yet.",
            warnings=["No workflow match found in the current registry."],
        )

    def _maybe_direct_command(self, instruction: str, normalized: str) -> AssistantPlan | None:
        trimmed = instruction.strip()
        if trimmed.lower().startswith("run "):
            trimmed = trimmed[4:].strip()
        if not trimmed:
            return None

        parts = trimmed.split(None, 1)
        command_name = parts[0]
        if not self.tool_registry.has_command(command_name):
            return None

        provided_values = self.tool_registry.parse_assignments(parts[1] if len(parts) > 1 else "")
        return self._build_plan(
            instruction=instruction,
            normalized=normalized,
            command_specs=[(command_name, provided_values, "Direct command invocation from the command bar.")],
            confidence=0.99,
            explanation="Recognized a registered workflow command directly.",
            source="direct",
        )

    def _maybe_bundle(self, instruction: str, normalized: str) -> AssistantPlan | None:
        tokens = set(normalized.split())
        command_specs: list[tuple[str, dict[str, str], str]] = []
        explanation = ""
        confidence = 0.0

        if (
            ("start" in tokens or "begin" in tokens)
            and ({"office", "morning", "work"} & tokens)
        ) or "start today office work" in normalized:
            command_specs = [
                ("mvp.start_day", {}, "Open your workspace starter flow and create the daily note."),
                ("mvp.download_report", {}, "Pull the daily report into exports for follow-up work."),
                ("desktop.check_entries", {}, "Check entry exceptions after the workspace is open."),
            ]
            confidence = 0.93
            explanation = "Matched the morning office-work routine and expanded it into approved workflows."
        elif {"download", "upload"} <= tokens and ({"report", "file", "invoice"} & tokens):
            command_specs = [
                ("mvp.download_report", {}, "Download the latest report into the exports folder."),
                ("portal.upload_latest_file", {}, "Upload the most recent export through the approved portal workflow."),
            ]
            confidence = 0.88
            explanation = "Matched a download-then-upload handoff sequence."
        elif ({"check", "entries"} <= tokens or {"pending", "work"} <= tokens) and (
            {"final", "summary", "report", "reports", "finish", "end"} & tokens
        ):
            command_specs = [
                ("desktop.check_entries", {}, "Review entry exceptions before the final summary."),
                ("mvp.end_day", {}, "Export the end-of-day summary after the check completes."),
            ]
            confidence = 0.87
            explanation = "Matched a close-out sequence with an entry check followed by the day summary."

        if not command_specs:
            return None

        return self._build_plan(
            instruction=instruction,
            normalized=normalized,
            command_specs=command_specs,
            confidence=confidence,
            explanation=explanation,
        )

    def _maybe_note(self, instruction: str, normalized: str) -> AssistantPlan | None:
        match = re.match(
            r"^(?:note|quick note|remember|write (?:a )?note|create (?:a )?note)\s+(.+)$",
            instruction.strip(),
            flags=re.IGNORECASE,
        )
        if match is None:
            return None

        note_text = match.group(1).strip()
        if not note_text:
            return None
        return self._build_plan(
            instruction=instruction,
            normalized=normalized,
            command_specs=[
                (
                    "mvp.note",
                    {"note_text": note_text},
                    "Write the note into the evidence folder and open it in Notepad.",
                )
            ],
            confidence=0.97,
            explanation="Matched the quick-note workflow and carried the note text into the workflow input.",
        )

    def _maybe_invoice(self, instruction: str, normalized: str) -> AssistantPlan | None:
        if not any(token in normalized for token in ("invoice", "ocr", "document", "image")):
            return None

        image_path = self._extract_path(instruction)
        provided: dict[str, str] = {}
        if image_path:
            provided["image_path"] = image_path

        confidence = 0.9 if image_path else 0.54
        explanation = (
            "Matched the invoice OCR workflow and filled the image path from the instruction."
            if image_path
            else "Matched the invoice OCR workflow, but I still need the image path to run it."
        )
        return self._build_plan(
            instruction=instruction,
            normalized=normalized,
            command_specs=[
                (
                    "phase2.read_invoice_id",
                    provided,
                    "Read a known invoice ID region, validate it, and queue low-confidence cases for review.",
                )
            ],
            confidence=confidence,
            explanation=explanation,
        )

    def _maybe_print_vouchers(self, instruction: str, normalized: str) -> AssistantPlan | None:
        tokens = set(normalized.split())
        if "print" not in tokens or not ({"voucher", "vouchers"} & tokens):
            return None

        provided = {"app_name": "voucher_app"}
        if "today" in tokens:
            provided["date_from"] = "today"
            provided["date_to"] = "today"

        explanation = "Matched the voucher-print state-machine workflow and set the date range for today's vouchers."
        if "today" not in tokens:
            explanation = "Matched the voucher-print workflow, but the date range should be reviewed before running."

        return self._build_plan(
            instruction=instruction,
            normalized=normalized,
            command_specs=[
                (
                    "desktop.print_today_vouchers",
                    provided,
                    "Navigate to the voucher list, apply the date range, load vouchers, and confirm printing.",
                )
            ],
            confidence=0.92 if "today" in tokens else 0.7,
            explanation=explanation,
        )

    def _best_single_command(self, instruction: str, normalized: str) -> AssistantPlan | None:
        tokens = set(normalized.split())
        candidates: list[_Candidate] = []
        for command_name, keywords in self._command_keywords.items():
            overlap = len(tokens & keywords)
            if overlap <= 0:
                continue
            coverage = overlap / max(1, len(keywords))
            confidence = 0.55 + min(0.3, overlap * 0.08) + min(0.08, coverage * 0.12)
            provided_values: dict[str, str] = {}
            if {"today", "latest"} & tokens:
                command = self.tool_registry.get_command(command_name)
                if any(parameter.name == "run_date" for parameter in command.parameters):
                    date_match = _DATE_PATTERN.search(instruction)
                    provided_values["run_date"] = date_match.group(0) if date_match else ""
            candidates.append(
                _Candidate(
                    command_name=command_name,
                    confidence=min(0.89, confidence),
                    reason=f"Keyword overlap matched the {command_name} workflow.",
                    provided_values=provided_values,
                )
            )

        if not candidates:
            return None

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        best = candidates[0]
        warnings: list[str] = []
        if len(candidates) > 1 and best.confidence - candidates[1].confidence < 0.05:
            warnings.append(
                f"Second-best match was {candidates[1].command_name}; review before running."
            )
            best.confidence = min(best.confidence, 0.68)

        plan = self._build_plan(
            instruction=instruction,
            normalized=normalized,
            command_specs=[(best.command_name, best.provided_values, best.reason)],
            confidence=best.confidence,
            explanation=best.reason,
        )
        plan.warnings.extend(warnings)
        return plan

    def _build_plan(
        self,
        *,
        instruction: str,
        normalized: str,
        command_specs: list[tuple[str, dict[str, str], str]],
        confidence: float,
        explanation: str,
        source: str = "heuristic",
    ) -> AssistantPlan:
        commands: list[PlannedCommand] = []
        missing_parameters: list[str] = []
        warnings: list[str] = []
        requires_confirmation = False

        for command_name, provided_values, reason in command_specs:
            command = self.tool_registry.get_command(command_name)
            values, missing = self.tool_registry.fill_defaults(command_name, provided_values)
            if "run_date" in values and not values["run_date"]:
                date_match = _DATE_PATTERN.search(instruction)
                if date_match:
                    values["run_date"] = date_match.group(0)
            if missing:
                missing_parameters.extend(f"{command_name}.{name}" for name in missing)
            raw_command = self.tool_registry.build_raw_command(command_name, values)
            commands.append(
                PlannedCommand(
                    tool_name="run_workflow",
                    command_name=command.name,
                    workflow_id=command.workflow_id,
                    raw_command=raw_command,
                    inputs=values,
                    reason=reason,
                    risk=command.risk,
                    requires_confirmation=command.requires_confirmation,
                )
            )
            if command.requires_confirmation or command.risk == "high":
                requires_confirmation = True
                warnings.append(f"{command.name} is marked as a risky workflow and needs approval.")

        status = "ready"
        if missing_parameters:
            status = "needs_clarification"
        elif requires_confirmation:
            status = "needs_confirmation"

        return AssistantPlan(
            instruction=instruction,
            normalized_instruction=normalized,
            status=status,
            confidence=confidence,
            explanation=explanation,
            commands=commands,
            warnings=warnings,
            missing_parameters=missing_parameters,
            requires_confirmation=requires_confirmation,
            source=source,
        )

    @staticmethod
    def _extract_path(instruction: str) -> str | None:
        match = _PATH_PATTERN.search(instruction)
        if match is None:
            return None
        return match.group("path").strip(' "\'')

    @staticmethod
    def _normalize(instruction: str) -> str:
        lowered = instruction.lower()
        lowered = lowered.replace("today's", "today")
        lowered = re.sub(r"[^a-z0-9:/\\._-]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()
