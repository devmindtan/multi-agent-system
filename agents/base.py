"""Common helpers for model-backed graph nodes."""

from __future__ import annotations

import json
import re
from typing import Any

from core.llm_gateway import LLMGateway


class BaseAgent:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    @staticmethod
    def content(message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(getattr(message, "content", "") or "")

    @staticmethod
    def parse_json(text: str) -> dict[str, Any]:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                raise ValueError("Model response did not contain a JSON object")
            value = json.loads(match.group(0))
        if not isinstance(value, dict):
            raise ValueError("Model response must be a JSON object")
        return value

