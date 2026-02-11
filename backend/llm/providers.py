"""LLM provider abstraction layer.

Supports multiple backends:
  - Ollama (local, default)
  - OpenAI (GPT-4o, GPT-4, GPT-3.5-turbo, etc.)
  - Anthropic (Claude Sonnet 4.5, Claude Haiku 4.5, etc.)

All providers implement the same interface so chat.py doesn't need to
know which backend is active. Privacy guarantee: the blinder pipeline
still runs *before* any provider sees the prompt — providers only ever
receive pseudonymized text.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context window sizes for known models (tokens)
# ---------------------------------------------------------------------------
CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3-mini": 200_000,
    # Anthropic
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-haiku-20240307": 200_000,
}


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    provider_name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
    ) -> AsyncIterator[str]:
        """Streaming chat completion. Yields content chunks."""
        ...

    @abstractmethod
    async def chat_sync(self, messages: list[dict[str, str]]) -> str:
        """Non-streaming chat — returns full response as a single string."""
        ...

    @abstractmethod
    async def get_context_window_size(self) -> int:
        """Return the model's context window size in tokens."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is reachable and the model is available."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the current model identifier."""
        ...


# ---------------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    """Ollama running locally — no data leaves the machine."""

    provider_name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url.rstrip("/")
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            if stream:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done", False):
                            break
            else:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                yield data.get("message", {}).get("content", "")

    async def chat_sync(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")

    async def get_context_window_size(self) -> int:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/show",
                    json={"name": self._model},
                )
                response.raise_for_status()
                info = response.json()
                params = info.get("model_info", {})
                for key, value in params.items():
                    if "context" in key.lower():
                        return int(value)
            return 4096
        except Exception:
            logger.warning("Could not determine Ollama context window, defaulting to 4096")
            return 4096

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
                return any(m.get("name", "").startswith(self._model) for m in models)
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List all models available in the local Ollama instance."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
                return [m.get("name", "") for m in models if m.get("name")]
        except Exception:
            logger.warning("Could not list Ollama models")
            return []


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """OpenAI API provider (GPT-4o, GPT-4, etc.)."""

    provider_name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._api_key = api_key
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            if stream:
                async with client.stream(
                    "POST",
                    "https://api.openai.com/v1/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            else:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                yield data["choices"][0]["message"]["content"]

    async def chat_sync(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def get_context_window_size(self) -> int:
        return CONTEXT_WINDOWS.get(self._model, 128_000)

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers=self._headers(),
                )
                return response.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    """Anthropic API provider (Claude Sonnet 4.5, Claude Haiku, etc.)."""

    provider_name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        self._api_key = api_key
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _convert_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[str, list[dict[str, str]]]:
        """Separate system prompt from messages for Anthropic's API format."""
        system = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system += msg["content"] + "\n"
            else:
                user_messages.append({"role": msg["role"], "content": msg["content"]})
        return system.strip(), user_messages

    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
    ) -> AsyncIterator[str]:
        system, user_messages = self._convert_messages(messages)
        payload: dict = {
            "model": self._model,
            "max_tokens": 8192,
            "messages": user_messages,
            "stream": stream,
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=300.0) as client:
            if stream:
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                            event_type = data.get("type", "")
                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                text = delta.get("text", "")
                                if text:
                                    yield text
                            elif event_type == "message_stop":
                                break
                        except (json.JSONDecodeError, KeyError):
                            continue
            else:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        yield block["text"]
                        break

    async def chat_sync(self, messages: list[dict[str, str]]) -> str:
        system, user_messages = self._convert_messages(messages)
        payload: dict = {
            "model": self._model,
            "max_tokens": 8192,
            "messages": user_messages,
            "stream": False,
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block["text"]
            return ""

    async def get_context_window_size(self) -> int:
        return CONTEXT_WINDOWS.get(self._model, 200_000)

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            # Light check — just verify the key works
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=self._headers(),
                    json={
                        "model": self._model,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                # 200 = works, 401 = bad key, anything else = service issue
                return response.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Available models registry
# ---------------------------------------------------------------------------

PROVIDER_MODELS: dict[str, list[dict[str, str]]] = {
    "ollama": [],  # populated dynamically from Ollama instance
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o", "context": "128K"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context": "128K"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "context": "128K"},
        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "context": "16K"},
        {"id": "o3-mini", "name": "o3-mini", "context": "200K"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5", "context": "200K"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "context": "200K"},
    ],
}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_provider(
    provider: str,
    model: str | None = None,
    *,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3",
    openai_api_key: str = "",
    openai_model: str = "gpt-4o",
    anthropic_api_key: str = "",
    anthropic_model: str = "claude-sonnet-4-5-20250929",
) -> LLMProvider:
    """Create an LLM provider instance.

    Parameters
    ----------
    provider : str
        One of "ollama", "openai", "anthropic".
    model : str | None
        Override model ID. If None, uses the default for the provider.
    """
    if provider == "ollama":
        return OllamaProvider(
            base_url=ollama_base_url,
            model=model or ollama_model,
        )
    elif provider == "openai":
        if not openai_api_key:
            raise ValueError("OpenAI API key is required")
        return OpenAIProvider(
            api_key=openai_api_key,
            model=model or openai_model,
        )
    elif provider == "anthropic":
        if not anthropic_api_key:
            raise ValueError("Anthropic API key is required")
        return AnthropicProvider(
            api_key=anthropic_api_key,
            model=model or anthropic_model,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
