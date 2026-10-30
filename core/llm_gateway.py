"""Small LiteLLM adapter used by every agent."""

from __future__ import annotations

import os
from typing import Any


class LLMGateway:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @staticmethod
    def _model_name(model_config: dict[str, Any]) -> str:
        provider = str(model_config.get("provider", "")).strip()
        name = str(model_config["model_name"]).strip()
        if provider and not name.startswith(f"{provider}/"):
            return f"{provider}/{name}"
        return name

    def completion(
        self,
        role: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
    ) -> Any:
        try:
            from litellm import completion
        except ImportError as exc:
            raise RuntimeError(
                "LiteLLM is not installed. Run: pip install -r requirements.txt"
            ) from exc

        config = self.settings["models"][role]
        kwargs: dict[str, Any] = {
            "model": self._model_name(config),
            "messages": messages,
            "temperature": config.get("temperature", 0.0),
        }
        if config.get("api_base"):
            kwargs["api_base"] = config["api_base"]
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if json_mode and self.settings.get("system", {}).get("enforce_json_mode", True):
            kwargs["response_format"] = {"type": "json_object"}

        try:
            return completion(**kwargs)
        except Exception as primary_error:
            fallback = self.settings.get("cloud_fallback", {})
            if not fallback.get("enabled"):
                raise RuntimeError(f"{role} model request failed: {primary_error}") from primary_error
            api_key_env = fallback.get("api_key_env")
            if api_key_env and not os.getenv(api_key_env):
                raise RuntimeError(
                    f"Fallback is enabled but {api_key_env} is not set"
                ) from primary_error
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("api_base", None)
            fallback_kwargs["model"] = self._model_name(fallback)
            return completion(**fallback_kwargs)

    @staticmethod
    def message(response: Any) -> Any:
        return response.choices[0].message

