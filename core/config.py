"""Configuration loading with predictable paths and validation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Top-level configuration must be a mapping: {path}")
    return value


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    return deepcopy(_load_yaml(Path(path) if path else PACKAGE_ROOT / "config/settings.yaml"))


def load_tool_config(path: str | Path | None = None) -> dict[str, Any]:
    return deepcopy(_load_yaml(Path(path) if path else PACKAGE_ROOT / "config/tools.yaml"))

