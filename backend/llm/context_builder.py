from __future__ import annotations

import logging

from llm.providers import LLMProvider
from llm.prompts import get_system_prompt

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Assembles LLM context using adaptive strategy: stuff vs RAG fallback."""

    def __init__(self, client: LLMProvider, threshold: float = 0.8):
        self.client = client
        self.threshold = threshold

    async def build_messages(
        self,
        blinded_documents: list[str],
        conversation_history: list[dict[str, str]],
        new_prompt: str,
        pseudonym_legend: list[str] | None = None,
        domain: str = "general",
        retrieved_chunks: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Build the message list for the LLM.

        If retrieved_chunks is provided (hybrid RAG mode), uses those instead
        of full documents. Otherwise tries context-stuffing with full docs.
        """
        system_prompt = get_system_prompt(domain)

        if retrieved_chunks is not None:
            # RAG mode — use pre-retrieved chunks instead of full docs
            logger.info("Using %d pre-retrieved chunks (hybrid RAG mode)", len(retrieved_chunks))
            doc_text = "\n\n---\n\n".join(retrieved_chunks)
            return self._build_stuffed(system_prompt, doc_text, conversation_history, new_prompt, pseudonym_legend)

        # Stuff mode — try to fit full documents
        context_window = await self.client.get_context_window_size()
        max_tokens = int(context_window * self.threshold)

        doc_text = self._combine_documents(blinded_documents)
        total_estimate = self._estimate_tokens(
            system_prompt + doc_text + new_prompt
        ) + sum(self._estimate_tokens(m.get("content", "")) for m in conversation_history)

        if total_estimate < max_tokens:
            return self._build_stuffed(system_prompt, doc_text, conversation_history, new_prompt, pseudonym_legend)
        else:
            logger.warning(
                "Content exceeds context window (%d > %d tokens) but no retrieved_chunks provided. "
                "Falling back to keyword retrieval.",
                total_estimate, max_tokens,
            )
            relevant_chunks = self._retrieve_relevant(
                blinded_documents, new_prompt, max_tokens, conversation_history, system_prompt
            )
            return self._build_stuffed(system_prompt, relevant_chunks, conversation_history, new_prompt, pseudonym_legend)

    def _combine_documents(self, documents: list[str]) -> str:
        if not documents:
            return ""
        parts = []
        for i, doc in enumerate(documents, 1):
            parts.append(f"--- Document {i} ---\n{doc}")
        return "\n\n".join(parts)

    def _build_stuffed(
        self,
        system_prompt: str,
        doc_content: str,
        history: list[dict[str, str]],
        new_prompt: str,
        pseudonym_legend: list[str] | None = None,
    ) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": system_prompt}]

        if doc_content:
            legend_text = ""
            if pseudonym_legend:
                legend_text = (
                    "\n\n### PSEUDONYM LEGEND ###\n"
                    "The following pseudonyms are used in these documents. "
                    "Use ONLY these exact pseudonyms in your responses:\n"
                    + "\n".join(f"- {p}" for p in pseudonym_legend)
                    + "\n### END LEGEND ###\n"
                )

            messages.append({
                "role": "user",
                "content": (
                    "### BEGIN DOCUMENT ###\n"
                    f"{doc_content}\n"
                    "### END DOCUMENT ###\n"
                    f"{legend_text}\n"
                    "The above documents have been provided for analysis. "
                    "All identifying information has been replaced with pseudonyms for privacy. "
                    "Use ONLY the exact pseudonyms listed above in your responses."
                ),
            })
            messages.append({
                "role": "assistant",
                "content": (
                    "I have received the documents. I will use ONLY the exact "
                    "pseudonyms from the documents (like [PERSON_1], [ORG_1], etc.) "
                    "and will never create new pseudonym formats. "
                    "How can I help you analyze these documents?"
                ),
            })

        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": new_prompt})
        return messages

    def _retrieve_relevant(
        self,
        documents: list[str],
        query: str,
        max_tokens: int,
        history: list[dict[str, str]],
        system_prompt: str = "",
    ) -> str:
        """Simple keyword-based retrieval (BM25-lite). Chunks documents and
        returns the most relevant chunks that fit within the token budget."""
        chunks = []
        for doc in documents:
            chunks.extend(self._chunk_text(doc, chunk_size=512, overlap=50))

        if not chunks:
            return ""

        query_tokens = set(query.lower().split())
        scored = []
        for chunk in chunks:
            chunk_tokens = set(chunk.lower().split())
            overlap = len(query_tokens & chunk_tokens)
            scored.append((overlap, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)

        history_tokens = sum(
            self._estimate_tokens(m.get("content", "")) for m in history
        )
        budget = max_tokens - self._estimate_tokens(system_prompt) - self._estimate_tokens(query) - history_tokens - 500
        selected = []
        used = 0
        for score, chunk in scored:
            chunk_tokens = self._estimate_tokens(chunk)
            if used + chunk_tokens > budget:
                break
            selected.append(chunk)
            used += chunk_tokens

        return "\n\n---\n\n".join(selected)

    def _chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
        """Split text into word-based chunks with overlap."""
        words = text.split()
        if len(words) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(words):
            end = start + chunk_size
            chunk = " ".join(words[start:end])
            chunks.append(chunk)
            start = end - overlap
        return chunks

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token for English text."""
        return len(text) // 4
