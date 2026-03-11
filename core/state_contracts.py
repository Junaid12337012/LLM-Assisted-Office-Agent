from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.models import ConfigurationError
from core.utils import load_json


@dataclass(slots=True)
class ControlContract:
    name: str = ""
    type: str = ""
    automation_id: str = ""


@dataclass(slots=True)
class ScreenContract:
    app_name: str
    screen_id: str
    window_title_contains: list[str] = field(default_factory=list)
    required_controls: list[ControlContract] = field(default_factory=list)
    required_texts: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    transitions: dict[str, str] = field(default_factory=dict)


class ScreenContractRegistry:
    def __init__(self, contracts: list[ScreenContract]) -> None:
        self._contracts = contracts

    @classmethod
    def from_file(cls, path: str | Path) -> "ScreenContractRegistry":
        payload = load_json(path)
        items = payload.get("contracts") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ConfigurationError("State contracts must contain a top-level 'contracts' list.")
        return cls([_parse_contract(item) for item in items])

    def list(self, app_name: str | None = None) -> list[ScreenContract]:
        if not app_name:
            return list(self._contracts)
        return [contract for contract in self._contracts if contract.app_name == app_name]

    def get(self, app_name: str, screen_id: str) -> ScreenContract:
        for contract in self._contracts:
            if contract.app_name == app_name and contract.screen_id == screen_id:
                return contract
        raise ConfigurationError(f"Unknown screen contract '{app_name}:{screen_id}'.")


def _parse_contract(item: dict[str, Any]) -> ScreenContract:
    required = {"app_name", "screen_id"}
    missing = sorted(required.difference(item))
    if missing:
        raise ConfigurationError(f"State contract missing fields: {missing}")

    controls_payload = item.get("required_controls", [])
    if not isinstance(controls_payload, list):
        raise ConfigurationError("required_controls must be a list.")

    return ScreenContract(
        app_name=str(item["app_name"]),
        screen_id=str(item["screen_id"]),
        window_title_contains=[str(value) for value in item.get("window_title_contains", [])],
        required_controls=[_parse_control(control) for control in controls_payload],
        required_texts=[str(value) for value in item.get("required_texts", [])],
        actions=[str(value) for value in item.get("actions", [])],
        transitions={str(key): str(value) for key, value in dict(item.get("transitions", {})).items()},
    )


def _parse_control(item: dict[str, Any]) -> ControlContract:
    if not isinstance(item, dict):
        raise ConfigurationError("Each required control must be an object.")
    return ControlContract(
        name=str(item.get("name") or ""),
        type=str(item.get("type") or ""),
        automation_id=str(item.get("automation_id") or ""),
    )
