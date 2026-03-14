from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from llm_training.evaluation import evaluate_plan_match, summarize_evaluation
from llm_training.feedback_store import FeedbackStore
from llm_training.training_data import read_jsonl_records


class FeedbackTrainingTests(unittest.TestCase):
    def test_feedback_store_saves_dataset_compatible_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            feedback_file = Path(temp_dir) / "feedback.jsonl"
            store = FeedbackStore(feedback_file)

            record = store.save_feedback(
                instruction="print all today voucher",
                approved_plan={
                    "status": "needs_confirmation",
                    "commands": [
                        {
                            "command_name": "desktop.print_today_vouchers",
                            "inputs": {"app_name": "voucher_app", "date_from": "today", "date_to": "today"},
                        }
                    ],
                },
                screen_context={"active_window": "Voucher List"},
                notes="Approved after review.",
                origin="local-model",
            )

            self.assertEqual("print all today voucher", record["messages"][1]["content"])
            self.assertEqual("desktop.print_today_vouchers", record["expected_plan"]["commands"][0]["command_name"])
            self.assertEqual(1, len(read_jsonl_records(feedback_file)))

    def test_export_dataset_dedupes_matching_records(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            seed_file = temp_root / "seed.jsonl"
            feedback_file = temp_root / "feedback.jsonl"
            output_file = temp_root / "merged.jsonl"

            duplicate_record = {
                "messages": [
                    {"role": "system", "content": "Plan approved desktop commands only."},
                    {"role": "user", "content": "open workspace"},
                ],
                "screen_context": {"active_window": "Desktop"},
                "expected_plan": {"status": "ready", "commands": [{"command_name": "workspace.open_all", "inputs": {}}]},
            }
            seed_file.write_text(json.dumps(duplicate_record) + "\n", encoding="utf-8")
            feedback_file.write_text(json.dumps(duplicate_record) + "\n", encoding="utf-8")

            store = FeedbackStore(feedback_file)
            records = store.export_dataset(output_file, base_files=[seed_file], dedupe=True)

            self.assertEqual(1, len(records))
            self.assertEqual(1, len(read_jsonl_records(output_file)))

    def test_evaluation_summary_counts_exact_matches(self) -> None:
        match = evaluate_plan_match(
            {
                "status": "ready",
                "commands": [{"command_name": "workspace.open_all", "inputs": {}}],
            },
            {
                "status": "ready",
                "commands": [{"command_name": "workspace.open_all", "inputs": {}}],
            },
        )
        mismatch = evaluate_plan_match(
            {
                "status": "needs_confirmation",
                "commands": [{"command_name": "desktop.print_today_vouchers", "inputs": {"date_from": "today"}}],
            },
            {
                "status": "ready",
                "commands": [{"command_name": "workspace.open_all", "inputs": {}}],
            },
        )

        summary = summarize_evaluation(
            [
                {"instruction": "open workspace", **match},
                {"instruction": "print all today voucher", **mismatch},
            ]
        )

        self.assertEqual(2, summary["total_examples"])
        self.assertEqual(0.5, summary["exact_match_rate"])
        self.assertEqual(1, len(summary["failures"]))


if __name__ == "__main__":
    unittest.main()
