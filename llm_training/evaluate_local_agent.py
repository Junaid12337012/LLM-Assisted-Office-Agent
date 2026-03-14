from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.runtime import build_services
from llm.dataset_validator import validate_jsonl_file
from llm.local_agent import LocalAgentPlanner
from llm.local_openai_client import LocalOpenAICompatibleClient
from llm_training.evaluation import evaluate_plan_match, summarize_evaluation
from llm_training.training_data import read_jsonl_records


class _StaticScreenCollector:
    def __init__(self, screen_context: dict[str, Any]) -> None:
        self.screen_context = dict(screen_context)

    def collect(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.screen_context)


def _build_local_planner(services: Any, screen_context: dict[str, Any]) -> LocalAgentPlanner:
    return LocalAgentPlanner(
        LocalOpenAICompatibleClient.from_env(),
        services.assistant.tool_registry,
        _StaticScreenCollector(screen_context),
        fallback_planner=services.assistant,
    )


def _evaluate_with_local_model(services: Any, record: dict[str, Any]) -> dict[str, Any]:
    instruction = str(record["messages"][-1]["content"])
    planner = _build_local_planner(services, record.get("screen_context") or {})
    return planner.plan(instruction).to_dict()


def _evaluate_with_heuristic(services: Any, record: dict[str, Any]) -> dict[str, Any]:
    instruction = str(record["messages"][-1]["content"])
    return services.assistant.plan(instruction).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the local or heuristic planner against a JSONL dataset.")
    parser.add_argument("--dataset-file", default="datasets/local_agent_eval.jsonl")
    parser.add_argument("--use-local-model", action="store_true")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    dataset_path = Path(args.dataset_file)
    dataset_errors = validate_jsonl_file(dataset_path)
    if dataset_errors:
        raise SystemExit("\n".join(dataset_errors))

    services = build_services(REPO_ROOT)
    records = read_jsonl_records(dataset_path)
    if args.limit > 0:
        records = records[: args.limit]

    results: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        actual_plan = (
            _evaluate_with_local_model(services, record)
            if args.use_local_model
            else _evaluate_with_heuristic(services, record)
        )
        evaluation = evaluate_plan_match(actual_plan, record["expected_plan"])
        results.append(
            {
                "index": index,
                "instruction": str(record["messages"][-1]["content"]),
                **evaluation,
            }
        )

    summary = summarize_evaluation(results)
    payload = {
        "dataset_file": str(dataset_path),
        "mode": "local-model" if args.use_local_model else "heuristic",
        "summary": summary,
    }
    if args.output_file:
        Path(args.output_file).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
