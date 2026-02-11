from __future__ import annotations

import logging
import threading

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmbeddingService:
    """Local embedding generation using sentence-transformers.

    Singleton — loads the model once on first call. All inference is local;
    nothing leaves the machine.
    """

    _instance: EmbeddingService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> EmbeddingService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._model = None
        return cls._instance

    def _load_model(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", settings.embedding_model)
        self._model = SentenceTransformer(settings.embedding_model)
        logger.info("Embedding model loaded (dim=%d)", settings.embedding_dimensions)

    def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns 384-dim vector."""
        self._load_model()
        vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts efficiently in one batch."""
        if not texts:
            return []
        self._load_model()
        vectors = self._model.encode(texts, normalize_embeddings=True, batch_size=64)
        return vectors.tolist()
