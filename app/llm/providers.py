from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol

from .gemini_client import GeminiClient, GeminiResponseError

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    def generate_json(self, prompt: str, response_schema: Any) -> dict[str, Any]: ...


class GeminiProvider:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient()

    def generate_json(self, prompt: str, response_schema: Any) -> dict[str, Any]:
        return self.client.generate_json(prompt, response_schema)


class GroqProvider:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

    def generate_json(self, prompt: str, response_schema: Any) -> dict[str, Any]:
        if not self.api_key:
            raise GeminiResponseError("GROQ_API_KEY is not configured")
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise GeminiResponseError("groq is not installed") from exc
        response = Groq(api_key=self.api_key).chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        try:
            data = json.loads(response.choices[0].message.content)
        except (IndexError, AttributeError, json.JSONDecodeError) as exc:
            raise GeminiResponseError("Groq returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise GeminiResponseError("Groq JSON response must be an object")
        return data


class LLMRouter:
    """Use Gemini first and Groq only as a bounded provider fallback."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers

    def generate_json(self, prompt: str, response_schema: Any) -> dict[str, Any]:
        failures: list[str] = []
        for provider in self.providers:
            try:
                return provider.generate_json(prompt, response_schema)
            except Exception as exc:
                failures.append(str(exc))
                logger.warning("llm provider failed: %s", exc)
        raise GeminiResponseError("All configured LLM providers failed: " + " | ".join(failures))