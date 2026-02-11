from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://blinder:localdev@localhost:5432/blinder_mvp"
    blinder_master_key: str = ""
    log_level: str = "INFO"

    # CORS — comma-separated origins allowed to access the API
    cors_origins: str = "http://localhost:5173"

    # LLM Provider settings
    default_provider: str = "ollama"     # "ollama", "openai", "anthropic"

    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # PII detection
    pii_confidence_threshold: float = 0.7

    # Context strategy
    context_window_threshold: float = 0.8  # switch to RAG at 80% of context window

    # RAG / Chunking
    chunk_size: int = 512          # words per chunk
    chunk_overlap: int = 50        # overlap words between chunks
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    rag_top_k: int = 10            # chunks to retrieve
    rrf_k: int = 60                # RRF constant (standard value)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
