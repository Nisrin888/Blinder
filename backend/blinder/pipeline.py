from __future__ import annotations

import logging
import re
from typing import List, Tuple

from blinder.depseudonymizer import Depseudonymizer
from blinder.entity_mapper import EntityMapper
from blinder.pii_detector import PIIDetector, PIIEntity
from blinder.threat_sanitizer import ThreatDetail, ThreatSanitizer
from blinder.vault import Vault

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt-aware PII filter
# ---------------------------------------------------------------------------
# Analysts ask questions with numbers, dates, and locations that are NOT PII
# but query parameters. This filter uses a context window around each entity
# to distinguish analytical parameters from real PII.
#
# Three categories:
#   A) Always real PII — never suppress (PERSON, SSN, CREDIT_CARD, etc.)
#   B) Context-dependent — suppress only if analytical context nearby
#   C) Always suppress in prompts (standalone numbers as DATE, etc.)
# ---------------------------------------------------------------------------

# Category A: always real PII, never suppress regardless of context
_ALWAYS_PII = {
    "PERSON", "EMAIL", "PHONE", "SSN", "CREDIT_CARD",
    "BANK_ACCOUNT", "IBAN", "DRIVER_LICENSE", "PASSPORT",
    "IP_ADDRESS", "MEDICAL_LICENSE",
}

# Category B: entity types that are context-dependent in prompts
_CONTEXT_DEPENDENT = {"DATE", "DATE_TIME", "LOCATION", "ORG", "NORP"}

# Context window size (characters before/after entity) to check for analytical signals
_CONTEXT_WINDOW = 60

# --- Analytical signal patterns (checked in the LOCAL context window) ---

# Threshold / comparison keywords near a number
_THRESHOLD_CONTEXT = re.compile(
    r"\b(over|under|above|below|more than|less than|fewer than|greater than|"
    r"at least|at most|between|exceeds?|older than|younger than|"
    r"higher than|lower than)\b",
    re.IGNORECASE,
)

# Aggregation / statistical keywords
_AGGREGATION_CONTEXT = re.compile(
    r"\b(how many|count|average|avg|mean|total|sum|max|min|median|"
    r"top|bottom|first|last|highest|lowest|oldest|youngest|largest|smallest|"
    r"percentile|quartile|standard deviation|stdev|variance)\b",
    re.IGNORECASE,
)

# Filter / grouping keywords (for locations and dates used as dimensions)
_FILTER_CONTEXT = re.compile(
    r"\b(group by|by|in|from|per|for each|break down|segment|"
    r"filter|where|records? from|records? in|records? after|records? before|"
    r"hired in|filed in|joined in|created in|admitted in|cases? from|"
    r"show all|list all|list everyone)\b",
    re.IGNORECASE,
)

# Range patterns: "between X and Y", "from X to Y", "X to Y", "X-Y"
_RANGE_CONTEXT = re.compile(
    r"\b(between|range|from .+ to)\b",
    re.IGNORECASE,
)

# Currency symbols/suffixes near a number → analytical, not PII
_CURRENCY_RE = re.compile(r"[\$€£₹]|(\d[KkMmBb]\b)|\b(dollars?|euros?|pounds?|thousand|million|billion)\b")

# Percentage near a number
_PERCENTAGE_RE = re.compile(r"\d\s*%|\bpercent\b|\brate\b", re.IGNORECASE)


def _get_context(text: str, start: int, end: int) -> str:
    """Extract a context window around an entity span."""
    ctx_start = max(0, start - _CONTEXT_WINDOW)
    ctx_end = min(len(text), end + _CONTEXT_WINDOW)
    return text[ctx_start:ctx_end]


def _is_standalone_number(text: str) -> bool:
    """Check if entity text is a standalone number (with optional formatting)."""
    stripped = text.strip().replace(",", "").replace(".", "").replace("$", "").replace("€", "")
    stripped = stripped.replace("£", "").replace("₹", "").replace("%", "").replace("+", "")
    stripped = stripped.replace("-", "").replace("K", "").replace("k", "")
    stripped = stripped.replace("M", "").replace("m", "")
    return stripped.isdigit()


def _is_year_only(text: str) -> bool:
    """Check if entity text is a standalone 4-digit year (1900-2099)."""
    stripped = text.strip()
    return bool(re.match(r"^(19|20)\d{2}$", stripped))


def _has_person_nearby(text: str, start: int, end: int, all_entities: list[PIIEntity]) -> bool:
    """Check if a PERSON entity exists within proximity of this entity."""
    for other in all_entities:
        if other.label == "PERSON":
            # Check if within ~80 characters
            if abs(other.start - end) < 80 or abs(start - other.end) < 80:
                return True
    return False


def _filter_prompt_entities(text: str, entities: list[PIIEntity]) -> list[PIIEntity]:
    """Filter false-positive PII detections from user prompts.

    Uses a context window around each entity to decide whether it's a real PII
    value or an analytical parameter (threshold, filter, aggregation dimension).

    Covers all analyst query patterns:
      - Thresholds: "over 60", "salary above 100K", "under $5000"
      - Dates as filters: "from 2022", "after January", "hired in 2020"
      - Locations as dimensions: "by city", "in California", "count per state"
      - Rankings: "top 10", "first 100", "bottom 5"
      - Statistics: "90th percentile", "average age"
      - Ranges: "between 25 and 35", "ages 30-40"
    """
    if not entities:
        return entities

    filtered = []
    for entity in entities:
        # Category A: always keep — these are always real PII
        if entity.label in _ALWAYS_PII:
            filtered.append(entity)
            continue

        # Category B: context-dependent — check local window
        if entity.label in _CONTEXT_DEPENDENT:
            ctx = _get_context(text, entity.start, entity.end)

            # --- Numbers detected as DATE/DATE_TIME ---
            if entity.label in ("DATE", "DATE_TIME"):
                # Standalone number in threshold/aggregation context
                if _is_standalone_number(entity.text):
                    if (_THRESHOLD_CONTEXT.search(ctx) or
                            _AGGREGATION_CONTEXT.search(ctx) or
                            _CURRENCY_RE.search(ctx) or
                            _PERCENTAGE_RE.search(ctx) or
                            _RANGE_CONTEXT.search(ctx)):
                        logger.info(
                            "Prompt filter: suppressed '%s' (%s) — "
                            "standalone number in analytical context",
                            entity.text, entity.label,
                        )
                        continue

                # Year-only in filter context (e.g., "from 2022", "hired in 2020")
                if _is_year_only(entity.text):
                    if _FILTER_CONTEXT.search(ctx):
                        # But keep if a PERSON entity is nearby ("John hired in 2020")
                        if not _has_person_nearby(text, entity.start, entity.end, entities):
                            logger.info(
                                "Prompt filter: suppressed '%s' (%s) — "
                                "year in filter context, no person nearby",
                                entity.text, entity.label,
                            )
                            continue

                # Partial date in filter context (e.g., "after January", "in Q4 2020")
                if _FILTER_CONTEXT.search(ctx) or _RANGE_CONTEXT.search(ctx):
                    if not _has_person_nearby(text, entity.start, entity.end, entities):
                        logger.info(
                            "Prompt filter: suppressed '%s' (%s) — "
                            "date in filter context, no person nearby",
                            entity.text, entity.label,
                        )
                        continue

            # --- Locations as analytical dimensions ---
            if entity.label == "LOCATION":
                if _FILTER_CONTEXT.search(ctx) or _AGGREGATION_CONTEXT.search(ctx):
                    # Suppress "in California", "by city", "from New York"
                    # But keep full street addresses (contain digits)
                    if not re.search(r"\d", entity.text):
                        logger.info(
                            "Prompt filter: suppressed '%s' (%s) — "
                            "location in analytical/filter context",
                            entity.text, entity.label,
                        )
                        continue

            # --- ORG in aggregation context ---
            if entity.label == "ORG":
                if _AGGREGATION_CONTEXT.search(ctx) or _FILTER_CONTEXT.search(ctx):
                    # Suppress "average at Mayo Clinic", "count by company"
                    # But keep if it looks like a specific reference with person
                    if not _has_person_nearby(text, entity.start, entity.end, entities):
                        logger.info(
                            "Prompt filter: suppressed '%s' (%s) — "
                            "org in analytical context",
                            entity.text, entity.label,
                        )
                        continue

        # Default: keep the entity
        filtered.append(entity)

    suppressed_count = len(entities) - len(filtered)
    if suppressed_count > 0:
        logger.info(
            "Prompt filter: %d/%d entities suppressed as analytical parameters",
            suppressed_count, len(entities),
        )

    return filtered


class HighSeverityThreatError(Exception):
    """Raised when a high-severity threat is detected in input text."""

    def __init__(self, threats: list[ThreatDetail]) -> None:
        self.threats = threats
        descriptions = "; ".join(t.description for t in threats)
        super().__init__(f"High severity threats detected: {descriptions}")


class BlinderPipeline:
    """Top-level orchestrator that ties every Blinder component together.

    Typical flow
    ------------
    1. **Document ingestion** -- ``process_document`` blinds uploaded docs.
    2. **Prompt preparation** -- ``process_prompt`` blinds user prompts,
       resolving entities against the existing vault so the same person
       keeps the same pseudonym.
    3. **Response restoration** -- ``restore_response`` replaces pseudonyms
       in the LLM's answer with the original real values.
    """

    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self._detector = PIIDetector()
        self._sanitizer = ThreatSanitizer()
        self._mapper = EntityMapper(vault)
        self._depseudonymizer = Depseudonymizer(vault)

    # ------------------------------------------------------------------
    # Document processing
    # ------------------------------------------------------------------

    async def process_document(
        self,
        text: str,
        skip_ner: bool = False,
    ) -> tuple[str, int, list[ThreatDetail]]:
        """Blind a document before storing or sending to an LLM.

        Parameters
        ----------
        skip_ner : bool
            When True, only Presidio (Gate A) runs.  Use for tabular data.

        Returns
        -------
        blinded_text : str
            The document with all PII replaced by pseudonyms.
        pii_count : int
            Number of PII entities detected and replaced.
        threats : list[ThreatDetail]
            Any threats found by the sanitiser.

        Raises
        ------
        HighSeverityThreatError
            If any high-severity threats are detected.
        """
        # Step 1: Threat sanitisation
        sanitize_result = self._sanitizer.sanitize(text)
        high_threats = [
            t for t in sanitize_result.threats if t.severity == "high"
        ]
        if high_threats:
            raise HighSeverityThreatError(high_threats)

        cleaned = sanitize_result.cleaned_text

        # Step 2: PII detection
        entities = await self._detector.detect(cleaned, skip_ner=skip_ner)

        # Step 3: Pseudonymisation via the vault
        blinded_text = self.vault.pseudonymize_text(cleaned, entities)

        logger.info(
            "Document processed: %d PII entities blinded, %d threats",
            len(entities),
            len(sanitize_result.threats),
        )
        return blinded_text, len(entities), sanitize_result.threats

    async def process_document_with_entities(
        self,
        text: str,
        entities: list[PIIEntity],
    ) -> tuple[str, int, list[ThreatDetail]]:
        """Blind a document using pre-detected PII entities (skips detection).

        Used for tabular data where column-based sample detection provides
        entities with correct offsets, avoiding a full NER pass on every row.

        If threat sanitisation changes the text (rare for CSV data), the
        pre-computed offsets become invalid — falls back to pattern-only
        Presidio detection on the cleaned text.
        """
        # Step 1: Threat sanitisation
        sanitize_result = self._sanitizer.sanitize(text)
        high_threats = [
            t for t in sanitize_result.threats if t.severity == "high"
        ]
        if high_threats:
            raise HighSeverityThreatError(high_threats)

        cleaned = sanitize_result.cleaned_text

        # Step 2: If sanitisation changed the text, pre-computed offsets are
        # invalid — fall back to pattern-only detection on the cleaned text.
        if cleaned != text:
            entities = await self._detector.detect(cleaned, skip_ner=True)

        # Step 3: Pseudonymisation via the vault
        blinded_text = self.vault.pseudonymize_text(cleaned, entities)

        logger.info(
            "Document processed (pre-detected): %d PII entities blinded, %d threats",
            len(entities),
            len(sanitize_result.threats),
        )
        return blinded_text, len(entities), sanitize_result.threats

    # ------------------------------------------------------------------
    # Prompt processing
    # ------------------------------------------------------------------

    async def process_prompt(
        self,
        prompt: str,
    ) -> tuple[str, list[ThreatDetail]]:
        """Blind a user prompt, resolving entities against the existing vault.

        Returns
        -------
        blinded_prompt : str
            The prompt with PII replaced by consistent pseudonyms.
        threats : list[ThreatDetail]
            Any threats found by the sanitiser.

        Raises
        ------
        HighSeverityThreatError
            If any high-severity threats are detected.
        """
        # Step 1: Threat sanitisation
        sanitize_result = self._sanitizer.sanitize(prompt)
        high_threats = [
            t for t in sanitize_result.threats if t.severity == "high"
        ]
        if high_threats:
            raise HighSeverityThreatError(high_threats)

        cleaned = sanitize_result.cleaned_text

        # Step 2: PII detection
        entities = await self._detector.detect(cleaned)

        # Step 2b: Filter false positives from prompts
        # Standalone numbers in analytical context ("over 60", "salary above 100k")
        # are query parameters, not PII — suppress them before encryption.
        entities = _filter_prompt_entities(cleaned, entities)

        # Step 3: Resolve entities against existing vault (cross-doc linking)
        resolved = self._mapper.resolve_prompt_entities(entities, self.vault)

        # Step 4: Pseudonymisation
        blinded_prompt = self.vault.pseudonymize_text(cleaned, resolved)

        logger.info(
            "Prompt processed: %d PII entities blinded, %d threats",
            len(resolved),
            len(sanitize_result.threats),
        )
        return blinded_prompt, sanitize_result.threats

    # ------------------------------------------------------------------
    # Response restoration
    # ------------------------------------------------------------------

    def restore_response(self, response: str) -> str:
        """Replace pseudonyms in an LLM response with real values."""
        return self._depseudonymizer.restore(response)
