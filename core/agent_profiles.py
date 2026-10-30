"""Validated, external agent definitions and prompt loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.config import PACKAGE_ROOT, _load_yaml


class AgentProfile(BaseModel):
    id: str
    model_role: str
    prompt: str
    tools: list[str] = Field(default_factory=list)
    max_turns: int = Field(default=20, ge=1, le=100)

    def instructions(self) -> str:
        path = (PACKAGE_ROOT / self.prompt).resolve()
        if PACKAGE_ROOT not in path.parents:
            raise ValueError(f"Prompt escapes package root: {self.prompt}")
        return path.read_text(encoding="utf-8")


def load_agent_profiles(path: str | Path | None = None) -> dict[str, AgentProfile]:
    source = Path(path) if path else PACKAGE_ROOT / "config/agents.yaml"
    raw = _load_yaml(source).get("agents", {})
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Agent configuration must contain a non-empty agents mapping")
    return {
        name: AgentProfile(id=name, **value)
        for name, value in raw.items()
    }
