from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_analyzer.nlp_engine import NlpEngineProvider
import spacy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

PRESIDIO_LABEL_MAP: dict[str, str] = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "US_SSN": "SSN",
    "CREDIT_CARD": "CREDIT_CARD",
    "DATE_TIME": "DATE",
    "IP_ADDRESS": "IP_ADDRESS",
    "LOCATION": "LOCATION",
    "NRP": "NORP",
    "US_DRIVER_LICENSE": "DRIVER_LICENSE",
    "US_PASSPORT": "PASSPORT",
    "US_BANK_NUMBER": "BANK_ACCOUNT",
    "IBAN_CODE": "IBAN",
    "MEDICAL_LICENSE": "MEDICAL_LICENSE",
    "URL": "URL",
    "LEGAL_CASE_NUMBER": "LEGAL_CASE_NUMBER",
}

SPACY_LABEL_MAP: dict[str, str] = {
    "PERSON": "PERSON",
    "ORG": "ORG",
    "GPE": "LOCATION",
    "DATE": "DATE",
    "LAW": "LEGAL_REF",
    "NORP": "NORP",
}

RELEVANT_SPACY_TYPES = set(SPACY_LABEL_MAP.keys())

# Entity types handled purely by regex/pattern recognizers in Presidio.
# Requesting only these prevents SpacyRecognizer (NER) from running,
# which is the key to fast processing of large tabular data.
PATTERN_ONLY_ENTITIES: list[str] = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SSN",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "URL",
    "IBAN_CODE",
    "US_BANK_NUMBER",
    "US_DRIVER_LICENSE",
    "US_PASSPORT",
    "MEDICAL_LICENSE",
    "CRYPTO",
    "LEGAL_CASE_NUMBER",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PIIEntity:
    """A single PII detection."""

    text: str
    label: str
    start: int
    end: int
    confidence: float
    gate: str  # "presidio" or "ner"


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class PIIDetector:
    """Dual-gate PII scanner combining Microsoft Presidio and spaCy NER."""

    _instance: "PIIDetector | None" = None

    def __new__(cls) -> "PIIDetector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # --- Gate A: Presidio (configured to use en_core_web_sm) ---
        legal_case_pattern = Pattern(
            name="legal_case_number_pattern",
            regex=r"\b\d{2}-[A-Z]{2}-\d{5}\b",
            score=0.85,
        )
        legal_case_recognizer = PatternRecognizer(
            supported_entity="LEGAL_CASE_NUMBER",
            name="LegalCaseRecognizer",
            patterns=[legal_case_pattern],
        )

        # Tell Presidio to use en_core_web_sm instead of default en_core_web_lg
        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        })
        nlp_engine = provider.create_engine()
        self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        self._analyzer.registry.add_recognizer(legal_case_recognizer)

        # --- Gate B: spaCy NER (lazy-loaded on first use) ---
        self._nlp = None

        logger.info("PIIDetector initialized (singleton)")

    # -- public API ----------------------------------------------------------

    async def detect(self, text: str, skip_ner: bool = False) -> list[PIIEntity]:
        """Run detection gates and return merged, deduplicated results.

        When *skip_ner* is True, only Gate A (Presidio) runs using
        pattern-only entity types (no SpacyRecognizer / NER).  This is
        appropriate for tabular data (CSV / Excel) where NER adds cost
        but no meaningful accuracy over regex pattern matching.
        """
        loop = asyncio.get_event_loop()

        if skip_ner:
            gate_a_results = await loop.run_in_executor(
                None, self._gate_a_presidio, text, True
            )
            return self._merge_detections(gate_a_results, [])

        gate_a_results, gate_b_results = await asyncio.gather(
            loop.run_in_executor(None, self._gate_a_presidio, text, False),
            loop.run_in_executor(None, self._gate_b_ner, text),
        )
        return self._merge_detections(gate_a_results, gate_b_results)

    # -- Gate A: Presidio ----------------------------------------------------

    _CHUNK_SIZE = 5000  # characters per chunk — keeps Presidio fast

    def _gate_a_presidio(self, text: str, patterns_only: bool = False) -> list[PIIEntity]:
        if len(text) <= self._CHUNK_SIZE:
            return self._gate_a_presidio_single(text, patterns_only)

        # Chunk large text by line boundaries so entities aren't split
        entities: list[PIIEntity] = []
        lines = text.split("\n")
        chunk_lines: list[str] = []
        chunk_len = 0
        offset = 0

        for line in lines:
            line_with_nl = line + "\n"
            if chunk_len + len(line_with_nl) > self._CHUNK_SIZE and chunk_lines:
                chunk_text = "".join(chunk_lines)
                for e in self._gate_a_presidio_single(chunk_text, patterns_only):
                    e.start += offset
                    e.end += offset
                    entities.append(e)
                offset += len(chunk_text)
                chunk_lines = []
                chunk_len = 0
            chunk_lines.append(line_with_nl)
            chunk_len += len(line_with_nl)

        # Process remaining lines
        if chunk_lines:
            chunk_text = "".join(chunk_lines)
            for e in self._gate_a_presidio_single(chunk_text, patterns_only):
                e.start += offset
                e.end += offset
                entities.append(e)

        return entities

    def _gate_a_presidio_single(self, text: str, patterns_only: bool = False) -> list[PIIEntity]:
        kwargs: dict = {"text": text, "language": "en"}
        if patterns_only:
            kwargs["entities"] = PATTERN_ONLY_ENTITIES
        results = self._analyzer.analyze(**kwargs)
        entities: list[PIIEntity] = []
        for r in results:
            label = PRESIDIO_LABEL_MAP.get(r.entity_type, r.entity_type)
            entities.append(
                PIIEntity(
                    text=text[r.start : r.end],
                    label=label,
                    start=r.start,
                    end=r.end,
                    confidence=r.score,
                    gate="presidio",
                )
            )
        return entities

    # -- Gate B: spaCy NER ---------------------------------------------------

    def _load_ner_model(self) -> None:
        """Lazy-load the transformer NER model on first Gate B call."""
        if self._nlp is not None:
            return
        try:
            self._nlp = spacy.load("en_core_web_trf")
            logger.info("Loaded spaCy model: en_core_web_trf (lazy)")
        except OSError:
            logger.warning(
                "en_core_web_trf not available, falling back to en_core_web_sm"
            )
            self._nlp = spacy.load("en_core_web_sm")

    def _gate_b_ner(self, text: str) -> list[PIIEntity]:
        self._load_ner_model()
        doc = self._nlp(text)
        entities: list[PIIEntity] = []
        for ent in doc.ents:
            if ent.label_ not in RELEVANT_SPACY_TYPES:
                continue
            label = SPACY_LABEL_MAP[ent.label_]
            entities.append(
                PIIEntity(
                    text=ent.text,
                    label=label,
                    start=ent.start_char,
                    end=ent.end_char,
                    confidence=0.80,  # spaCy does not provide per-entity scores
                    gate="ner",
                )
            )
        return entities

    # -- Merge / deduplicate -------------------------------------------------

    @staticmethod
    def _merge_detections(
        gate_a: list[PIIEntity],
        gate_b: list[PIIEntity],
    ) -> list[PIIEntity]:
        """Merge results from both gates, deduplicating overlapping spans.

        When two detections overlap the longer span with the higher confidence
        is preferred.
        """
        all_entities = gate_a + gate_b

        # Sort by span length descending, then confidence descending so the
        # "best" detection for any region comes first.
        all_entities.sort(
            key=lambda e: (-(e.end - e.start), -e.confidence),
        )

        merged: list[PIIEntity] = []
        occupied: list[tuple[int, int]] = []

        for entity in all_entities:
            overlaps = False
            for occ_start, occ_end in occupied:
                # Two spans overlap if neither is entirely before the other.
                if entity.start < occ_end and entity.end > occ_start:
                    overlaps = True
                    break
            if not overlaps:
                merged.append(entity)
                occupied.append((entity.start, entity.end))

        # Return sorted by start position for downstream consumers.
        merged.sort(key=lambda e: e.start)
        return merged
