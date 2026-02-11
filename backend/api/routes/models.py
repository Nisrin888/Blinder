"""Model management endpoints.

GET  /api/models           — list available providers + models
GET  /api/models/settings  — get current provider/model config (keys masked)
POST /api/models/settings  — update API keys and default provider at runtime
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

from config import get_settings
from llm.providers import OllamaProvider, PROVIDER_MODELS

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ModelInfo(BaseModel):
    id: str
    name: str
    context: str
    provider: str


class ProviderStatus(BaseModel):
    provider: str
    available: bool
    models: list[ModelInfo]


class ModelsResponse(BaseModel):
    providers: list[ProviderStatus]
    default_provider: str
    default_model: str


VALID_PROVIDERS = {"ollama", "openai", "anthropic"}


class ModelSettingsUpdate(BaseModel):
    default_provider: str | None = None
    default_model: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    @field_validator("default_provider")
    @classmethod
    def validate_provider(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_PROVIDERS:
            raise ValueError(f"Provider must be one of: {', '.join(sorted(VALID_PROVIDERS))}")
        return v

    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_key(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            if not re.match(r"^sk-[A-Za-z0-9_-]{20,}$", v):
                raise ValueError("Invalid OpenAI API key format (expected sk-...)")
        return v

    @field_validator("anthropic_api_key")
    @classmethod
    def validate_anthropic_key(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            if not re.match(r"^sk-ant-[A-Za-z0-9_-]{20,}$", v):
                raise ValueError("Invalid Anthropic API key format (expected sk-ant-...)")
        return v


class ModelSettingsResponse(BaseModel):
    default_provider: str
    ollama_model: str
    openai_model: str
    anthropic_model: str
    openai_api_key_set: bool
    anthropic_api_key_set: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=ModelsResponse)
async def list_models():
    """List available providers and their models."""
    settings = get_settings()
    providers: list[ProviderStatus] = []

    # 1. Ollama — dynamically list locally available models
    ollama = OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )
    ollama_available = await ollama.is_available()
    ollama_models: list[ModelInfo] = []
    if ollama_available:
        local_models = await ollama.list_models()
        for m in local_models:
            name = m.split(":")[0] if ":" in m else m
            ollama_models.append(ModelInfo(
                id=m,
                name=name.title(),
                context="varies",
                provider="ollama",
            ))
    providers.append(ProviderStatus(
        provider="ollama",
        available=ollama_available,
        models=ollama_models,
    ))

    # 2. OpenAI
    openai_available = bool(settings.openai_api_key)
    providers.append(ProviderStatus(
        provider="openai",
        available=openai_available,
        models=[
            ModelInfo(provider="openai", **m)
            for m in PROVIDER_MODELS["openai"]
        ],
    ))

    # 3. Anthropic
    anthropic_available = bool(settings.anthropic_api_key)
    providers.append(ProviderStatus(
        provider="anthropic",
        available=anthropic_available,
        models=[
            ModelInfo(provider="anthropic", **m)
            for m in PROVIDER_MODELS["anthropic"]
        ],
    ))

    # Determine default model for current provider
    default_model = {
        "ollama": settings.ollama_model,
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
    }.get(settings.default_provider, settings.ollama_model)

    return ModelsResponse(
        providers=providers,
        default_provider=settings.default_provider,
        default_model=default_model,
    )


@router.get("/settings", response_model=ModelSettingsResponse)
async def get_model_settings():
    """Get current model configuration (API keys masked)."""
    settings = get_settings()
    return ModelSettingsResponse(
        default_provider=settings.default_provider,
        ollama_model=settings.ollama_model,
        openai_model=settings.openai_model,
        anthropic_model=settings.anthropic_model,
        openai_api_key_set=bool(settings.openai_api_key),
        anthropic_api_key_set=bool(settings.anthropic_api_key),
    )


@router.post("/settings", response_model=ModelSettingsResponse)
async def update_model_settings(
    body: ModelSettingsUpdate,
    x_requested_with: str | None = Header(None),
):
    """Update model settings at runtime.

    Updates are applied to the in-memory settings singleton only (not
    written to environment variables or disk). Keys stay in-memory for
    the lifetime of the server process.

    Requires X-Requested-With header as CSRF protection — browsers won't
    send custom headers on cross-origin requests without a preflight.
    """
    # CSRF check: reject requests without the custom header.
    # Browsers enforce that cross-origin POSTs with custom headers
    # trigger a CORS preflight, which our strict allow_origins blocks.
    if x_requested_with != "XMLHttpRequest":
        raise HTTPException(
            status_code=403,
            detail="Missing or invalid X-Requested-With header",
        )

    settings = get_settings()

    if body.openai_api_key is not None:
        settings.openai_api_key = body.openai_api_key
        logger.info("OpenAI API key %s", "updated" if body.openai_api_key else "cleared")

    if body.anthropic_api_key is not None:
        settings.anthropic_api_key = body.anthropic_api_key
        logger.info("Anthropic API key %s", "updated" if body.anthropic_api_key else "cleared")

    if body.default_provider is not None:
        settings.default_provider = body.default_provider
        logger.info("Default provider changed to %s", body.default_provider)

    if body.default_model is not None:
        provider_model_map = {
            "ollama": "ollama_model",
            "openai": "openai_model",
            "anthropic": "anthropic_model",
        }
        attr = provider_model_map.get(settings.default_provider)
        if attr:
            setattr(settings, attr, body.default_model)

    return ModelSettingsResponse(
        default_provider=settings.default_provider,
        ollama_model=settings.ollama_model,
        openai_model=settings.openai_model,
        anthropic_model=settings.anthropic_model,
        openai_api_key_set=bool(settings.openai_api_key),
        anthropic_api_key_set=bool(settings.anthropic_api_key),
    )
