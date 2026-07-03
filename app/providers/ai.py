from __future__ import annotations

import json
from abc import ABC, abstractmethod

from openai import AsyncAzureOpenAI, AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from openai import APIConnectionError, APIError, RateLimitError


class AiProviderError(Exception):
    """Raised when the AI provider fails to produce a usable turn after retries."""


class AiProvider(ABC):
    """Adapter interface for the conversation LLM. One instance per call,
    built from the organization's stored, decrypted AI credentials.
    """

    @abstractmethod
    async def complete_json(self, *, system_prompt: str, user_content: str) -> dict:
        """Send one turn, return the parsed JSON object the model returned."""


def _retry_decorator():
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((APIError, APIConnectionError, RateLimitError)),
        reraise=True,
    )


class AzureOpenAiProvider(AiProvider):
    def __init__(self, *, endpoint: str, api_key: str, deployment: str, api_version: str) -> None:
        self._client = AsyncAzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        self._deployment = deployment

    @_retry_decorator()
    async def _call(self, *, system_prompt: str, user_content: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=30,
        )
        return response.choices[0].message.content or "{}"

    async def complete_json(self, *, system_prompt: str, user_content: str) -> dict:
        try:
            raw = await self._call(system_prompt=system_prompt, user_content=user_content)
            return json.loads(raw)
        except Exception as exc:
            raise AiProviderError(str(exc)) from exc


class OpenAiProvider(AiProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    @_retry_decorator()
    async def _call(self, *, system_prompt: str, user_content: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=30,
        )
        return response.choices[0].message.content or "{}"

    async def complete_json(self, *, system_prompt: str, user_content: str) -> dict:
        try:
            raw = await self._call(system_prompt=system_prompt, user_content=user_content)
            return json.loads(raw)
        except Exception as exc:
            raise AiProviderError(str(exc)) from exc


def get_ai_provider(provider: str, credentials: dict) -> AiProvider:
    if provider == "azure_openai":
        return AzureOpenAiProvider(
            endpoint=credentials["endpoint"],
            api_key=credentials["apiKey"],
            deployment=credentials["deployment"],
            api_version=credentials.get("apiVersion", "2025-01-01-preview"),
        )
    if provider == "openai":
        return OpenAiProvider(api_key=credentials["apiKey"], model=credentials.get("model", "gpt-4o-mini"))
    raise ValueError(f"Unsupported AI provider: {provider}")
