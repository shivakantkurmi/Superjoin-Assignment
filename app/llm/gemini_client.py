from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class GeminiConfigurationError(RuntimeError):
    """Raised when Gemini cannot be configured safely."""


class GeminiResponseError(RuntimeError):
    """Raised when Gemini returns unusable structured output."""


class GeminiClient:
    """Small SDK boundary so extraction and reasoning can be mocked in tests."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        generate: Callable[..., Any] | None = None,
    ) -> None:
        self.api_keys = self._configured_values("GEMINI_API_KEYS", api_key or os.getenv("GEMINI_API_KEY"))
        self.models = self._configured_values("GEMINI_MODELS", model or os.getenv("GEMINI_MODEL", "gemini-3.7-flash"))
        self.api_key = self.api_keys[0] if self.api_keys else None
        self.model = self.models[0]
        self._generate = generate
        self._sdk_clients: dict[str, Any] = {}

    @staticmethod
    def _configured_values(name: str, fallback: str | None) -> list[str]:
        raw = os.getenv(name, "") or fallback or ""
        return [value.strip() for value in raw.split(",") if value.strip()]

    def _sdk_generate(self, prompt: str, response_schema: Any) -> Any:
        if not self.api_keys:
            raise GeminiConfigurationError("GEMINI_API_KEY is not configured")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - setup failure path
            raise GeminiConfigurationError("google-genai is not installed") from exc

        failures: list[str] = []
        for api_key in self.api_keys:
            for model in self.models:
                try:
                    logger.info("gemini stage=fact_or_reasoning model=%s key_slot=%d status=started", model, self.api_keys.index(api_key) + 1)
                    client = self._sdk_clients.get(api_key)
                    if client is None:
                        client = genai.Client(api_key=api_key)
                        self._sdk_clients[api_key] = client
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=response_schema,
                        ),
                    )
                    logger.info("gemini model=%s status=completed", model)
                    return response
                except Exception as exc:
                    message = str(exc)
                    failures.append(f"{model}: {message}")
                    logger.warning("gemini model=%s status=failed error=%s", model, message)
                    if "client has been closed" in message.casefold():
                        self._sdk_clients.pop(api_key, None)
                    if not self._is_transient(exc):
                        raise GeminiResponseError(message) from exc
        raise GeminiResponseError("All configured Gemini key/model combinations failed: " + " | ".join(failures))

    @staticmethod
    def _is_transient(error: Exception) -> bool:
        text = str(error).casefold()
        return any(marker in text for marker in ("503", "unavailable", "429", "resource exhausted", "rate limit", "client has been closed"))

    def generate_json(self, prompt: str, response_schema: Any) -> dict[str, Any]:
        response = (
            self._generate(prompt, response_schema)
            if self._generate
            else self._sdk_generate(prompt, response_schema)
        )
        if isinstance(response, dict):
            return response
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            if hasattr(parsed, "model_dump"):
                parsed = parsed.model_dump()
            if isinstance(parsed, dict):
                return parsed

        text = getattr(response, "text", None)
        if not text:
            raise GeminiResponseError("Gemini returned no JSON content")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiResponseError("Gemini returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise GeminiResponseError("Gemini JSON response must be an object")
        return parsed