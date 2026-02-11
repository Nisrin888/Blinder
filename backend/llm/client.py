"""LLM client factory.

Provides ``get_llm_client()`` which returns the correct provider based on
the requested provider/model or the global default from settings.

Also keeps ``OllamaClient`` as a thin backward-compatible wrapper so
existing imports like ``from llm.client import OllamaClient`` still work.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from config import get_settings
from llm.providers import (
    LLMProvider,
    OllamaProvider,
    OpenAIProvider,
    AnthropicProvider,
    create_provider,
)

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Factory — primary way to get an LLM client
# ---------------------------------------------------------------------------

def get_llm_client(
    provider: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance.

    Parameters
    ----------
    provider : str | None
        One of "ollama", "openai", "anthropic". Defaults to settings.default_provider.
    model : str | None
        Model ID override. If None, uses the default for the provider.
    """
    provider = provider or settings.default_provider

    return create_provider(
        provider=provider,
        model=model,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_model=settings.anthropic_model,
    )


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

class OllamaClient(OllamaProvider):
    """Backward-compatible alias for OllamaProvider.

    Existing code that does ``OllamaClient()`` keeps working unchanged.
    """

    def __init__(
        self,
        base_url: str = settings.ollama_base_url,
        model: str = settings.ollama_model,
    ):
        super().__init__(base_url=base_url, model=model)
