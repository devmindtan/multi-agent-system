"""Small LiteLLM adapter used by every agent."""

from __future__ import annotations

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
        if self.settings.get("system", {}).get("local_only", True):
            provider = str(config.get("provider", "")).lower()
            api_base = str(config.get("api_base", ""))
            if provider not in {"ollama", "vllm"}:
                raise RuntimeError(f"Local-only mode rejected provider: {provider}")
            if not any(host in api_base for host in ("localhost", "127.0.0.1", "::1")):
                raise RuntimeError(f"Local-only mode rejected non-local endpoint: {api_base}")
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
        except Exception as error:
            raise RuntimeError(f"{role} local model request failed: {error}") from error

    @staticmethod
    def message(response: Any) -> Any:
        return response.choices[0].message

