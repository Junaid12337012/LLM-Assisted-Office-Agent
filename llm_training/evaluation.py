from __future__ import annotations

from typing import Any

from llm_training.training_data import minimal_expected_plan


def evaluate_plan_match(plan_like: dict[str, Any], expected_plan: dict[str, Any]) -> dict[str, Any]:
    actual = minimal_expected_plan(plan_like)
    expected = minimal_expected_plan(expected_plan)
    actual_commands = actual.get("commands", [])
    expected_commands = expected.get("commands", [])
    return {
        "status_match": actual.get("status") == expected.get("status"),
        "command_names_match": [item.get("command_name") for item in actual_commands]
        == [item.get("command_name") for item in expected_commands],
        "inputs_match": [dict(item.get("inputs") or {}) for item in actual_commands]
        == [dict(item.get("inputs") or {}) for item in expected_commands],
        "actual": actual,
        "expected": expected,
    }


def summarize_evaluation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    exact_matches = 0
    status_matches = 0
    command_matches = 0
    input_matches = 0
    failures: list[dict[str, Any]] = []

    for row in rows:
        if row["status_match"]:
            status_matches += 1
        if row["command_names_match"]:
            command_matches += 1
        if row["inputs_match"]:
            input_matches += 1
        if row["status_match"] and row["command_names_match"] and row["inputs_match"]:
            exact_matches += 1
        else:
            failures.append(row)

    return {
        "total_examples": total,
        "exact_match_rate": round(exact_matches / total, 3) if total else 0.0,
        "status_match_rate": round(status_matches / total, 3) if total else 0.0,
        "command_match_rate": round(command_matches / total, 3) if total else 0.0,
        "input_match_rate": round(input_matches / total, 3) if total else 0.0,
        "failures": failures,
    }
