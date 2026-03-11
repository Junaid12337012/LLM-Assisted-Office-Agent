from __future__ import annotations

import copy
import json
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def ensure_parent(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def render_template(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        return value.format_map(_SafeFormatDict(flatten_context(context)))
    if isinstance(value, list):
        return [render_template(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_template(item, context) for key, item in value.items()}
    return value


def flatten_context(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, Mapping):
            flat.update(flatten_context(value, name))
        else:
            flat[name] = value
            if prefix:
                flat[key] = value
    return flat


def clone_jsonable(value: Any) -> Any:
    return copy.deepcopy(value)


def sleep_backoff(backoff_ms: int) -> None:
    if backoff_ms > 0:
        time.sleep(backoff_ms / 1000.0)

