"""Thin Ollama client: a prompt and a pydantic model in, a validated instance out."""

import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class OllamaUnreachable(Exception):
    """The host could not be reached; the whole run should abort (and later retry)."""


class BadLLMOutput(Exception):
    """The model kept returning invalid output for this one item."""


class OllamaClient:
    def __init__(
        self, client: httpx.Client, base_url: str, model: str, *, temperature: float = 0.1,
        max_attempts: int = 3,
    ):
        self._client = client
        self._url = base_url.rstrip("/") + "/api/generate"
        self.model = model
        self._temperature = temperature
        self._max_attempts = max_attempts

    def generate(self, prompt: str, shape: type[T], **options) -> tuple[T, float]:
        """Return the validated response and the seconds the successful call took."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": shape.model_json_schema(),
            "options": {"temperature": self._temperature, **options},
        }
        last_error: Exception | None = None
        for _ in range(self._max_attempts):
            started = time.perf_counter()
            try:
                response = self._client.post(self._url, json=payload, timeout=600)
                response.raise_for_status()
            except httpx.TransportError as exc:
                raise OllamaUnreachable(f"Ollama unreachable at {self._url}: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise OllamaUnreachable(f"Ollama error at {self._url}: {exc}") from exc
            seconds = time.perf_counter() - started
            try:
                return shape.model_validate_json(response.json()["response"]), seconds
            except (ValidationError, KeyError, ValueError) as exc:
                last_error = exc
        raise BadLLMOutput(f"invalid output after {self._max_attempts} attempts: {last_error}")
