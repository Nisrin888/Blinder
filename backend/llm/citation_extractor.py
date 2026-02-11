"""Post-hoc citation extraction using BM25-lite keyword scoring.

After the LLM produces a response, this module scores each document chunk
against the response to identify which source documents were most relevant.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass
class DocumentChunk:
    """A chunk of a document with source metadata."""

    document_id: str
    filename: str
    chunk_index: int
    text: str  # blinded text


@dataclass
class Citation:
    """A single citation linking a response to a document chunk."""

    document_id: str
    filename: str
    chunk_index: int
    score: float
    snippet_blinded: str
    snippet_lawyer: str  # filled in later by depseudonymizer
    marker: int | None = None  # inline citation number [N], None for BM25-only


class CitationExtractor:
    """Extracts source citations by scoring document chunks against an LLM response."""

    def __init__(
        self,
        max_citations: int = 3,
        min_score: float = 0.05,
        snippet_words: int = 40,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> None:
        self.max_citations = max_citations
        self.min_score = min_score
        self.snippet_words = snippet_words
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def extract(
        self,
        response_text: str,
        documents: list[DocumentChunk],
    ) -> list[Citation]:
        """Score each document chunk against the response and return top-K citations."""
        all_chunks = self._prepare_chunks(documents)
        if not all_chunks:
            return []

        response_tokens = self._tokenize(response_text)
        if not response_tokens:
            return []

        # Compute IDF across all chunks
        doc_count = len(all_chunks)
        doc_freq: dict[str, int] = {}
        chunk_token_sets: list[set[str]] = []
        for chunk in all_chunks:
            tokens = set(self._tokenize(chunk.text))
            chunk_token_sets.append(tokens)
            for token in tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        # Score each chunk using BM25-lite
        scored: list[tuple[float, int]] = []
        for idx, chunk in enumerate(all_chunks):
            chunk_tokens = chunk_token_sets[idx]
            score = 0.0
            for token in response_tokens:
                if token in chunk_tokens:
                    df = doc_freq.get(token, 0)
                    idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1)
                    score += idf
            scored.append((score, idx))

        scored.sort(key=lambda x: x[0], reverse=True)

        max_score = scored[0][0] if scored[0][0] > 0 else 1.0

        # Deduplicate by document_id: keep best chunk per document
        seen_docs: set[str] = set()
        citations: list[Citation] = []
        for score, idx in scored:
            if len(citations) >= self.max_citations:
                break
            chunk = all_chunks[idx]
            normalized = score / max_score
            if normalized < self.min_score:
                break
            if chunk.document_id in seen_docs:
                continue
            seen_docs.add(chunk.document_id)

            snippet = self._extract_snippet(chunk.text, response_tokens)
            citations.append(Citation(
                document_id=chunk.document_id,
                filename=chunk.filename,
                chunk_index=chunk.chunk_index,
                score=round(normalized, 3),
                snippet_blinded=snippet,
                snippet_lawyer="",  # filled by caller
            ))

        return citations

    def extract_inline(
        self,
        response_text: str,
        source_metadata: list[dict],
        source_texts: list[str],
    ) -> list[Citation]:
        """Extract inline [N] citation markers from the LLM response.

        source_metadata is a list of {"index": N, "filename": ..., "document_id": ...}.
        source_texts is the list of blinded texts corresponding to each source.
        Returns Citation objects with marker set to the inline number.
        """
        # Find all [N] markers in the response
        markers_found = set(int(m) for m in re.findall(r"\[(\d+)\]", response_text))
        # Filter out pseudonym-like patterns: [PERSON_1] would not match \d+ so we're safe

        valid_by_index = {m["index"]: m for m in source_metadata}
        citations: list[Citation] = []

        for marker_num in sorted(markers_found):
            meta = valid_by_index.get(marker_num)
            if meta is None:
                continue
            # Find the corresponding source text
            src_idx = marker_num - 1  # 0-based
            if src_idx < 0 or src_idx >= len(source_texts):
                continue

            source_text = source_texts[src_idx]

            # Extract a relevant snippet from the source
            response_tokens = self._tokenize(response_text)
            snippet = self._extract_snippet(source_text, response_tokens)

            # Compute a BM25-lite relevance score for this source
            response_token_set = set(response_tokens)
            source_tokens = set(self._tokenize(source_text))
            overlap = len(response_token_set & source_tokens)
            total = len(response_token_set) if response_token_set else 1
            score = round(min(overlap / total, 1.0), 3)

            citations.append(Citation(
                document_id=meta["document_id"],
                filename=meta["filename"],
                chunk_index=0,
                score=score,
                snippet_blinded=snippet,
                snippet_lawyer="",  # filled by caller
                marker=marker_num,
            ))

        return citations

    def _prepare_chunks(self, documents: list[DocumentChunk]) -> list[DocumentChunk]:
        """Split documents longer than chunk_size words into overlapping chunks."""
        result: list[DocumentChunk] = []
        for doc in documents:
            words = doc.text.split()
            if len(words) <= self.chunk_size:
                result.append(doc)
            else:
                start = 0
                ci = 0
                while start < len(words):
                    end = start + self.chunk_size
                    chunk_text = " ".join(words[start:end])
                    result.append(DocumentChunk(
                        document_id=doc.document_id,
                        filename=doc.filename,
                        chunk_index=ci,
                        text=chunk_text,
                    ))
                    ci += 1
                    start = end - self.chunk_overlap
        return result

    def _tokenize(self, text: str) -> list[str]:
        """Lowercase split, strip punctuation, filter stopwords."""
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]

    def _extract_snippet(self, chunk_text: str, response_tokens: list[str]) -> str:
        """Extract the most relevant snippet from the chunk via sliding window."""
        words = chunk_text.split()
        if len(words) <= self.snippet_words:
            return chunk_text

        response_set = set(response_tokens)
        best_score = -1
        best_start = 0
        for i in range(len(words) - self.snippet_words + 1):
            window = words[i : i + self.snippet_words]
            window_tokens = {w.lower().strip(".,;:!?\"'()[]") for w in window}
            overlap = len(window_tokens & response_set)
            if overlap > best_score:
                best_score = overlap
                best_start = i

        snippet = " ".join(words[best_start : best_start + self.snippet_words])
        if best_start > 0:
            snippet = "..." + snippet
        if best_start + self.snippet_words < len(words):
            snippet = snippet + "..."
        return snippet


_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "was", "are", "not",
    "but", "has", "had", "have", "been", "from", "they", "will", "would",
    "could", "should", "may", "can", "its", "his", "her", "their", "our",
    "all", "any", "each", "one", "two", "also", "than", "then", "when",
    "where", "which", "who", "whom", "how", "what", "into", "out",
}
