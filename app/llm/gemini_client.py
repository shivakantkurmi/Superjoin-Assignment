from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any


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
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self._generate = generate

    def _sdk_generate(self, prompt: str, response_schema: Any) -> Any:
        if not self.api_key:
            raise GeminiConfigurationError("GEMINI_API_KEY is not configured")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - setup failure path
            raise GeminiConfigurationError("google-genai is not installed") from exc

        client = genai.Client(api_key=self.api_key)
        return client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

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