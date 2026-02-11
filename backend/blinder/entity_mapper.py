from __future__ import annotations

import re
import string
from typing import Optional

from blinder.pii_detector import PIIEntity
from blinder.vault import Vault

# Titles that should be stripped during normalisation.
_TITLE_PATTERN = re.compile(
    r"^(mr|mrs|ms|miss|dr|prof|judge|justice|hon|sr|jr)\.?\s+",
    re.IGNORECASE,
)


class EntityMapper:
    """Cross-document entity resolution layer.

    Ensures that the same real-world entity is always mapped to the same
    pseudonym, even when it appears in slightly different forms across
    documents and prompts (e.g. "Dr. Jane Smith" vs "Jane Smith").
    """

    def __init__(self, vault: Vault) -> None:
        self._vault = vault

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_prompt_entities(
        self,
        prompt_entities: list[PIIEntity],
        vault: Vault,
    ) -> list[PIIEntity]:
        """Resolve *prompt_entities* against the existing vault.

        For each entity, if we can find a matching entry already stored in the
        vault, we update the entity's label/text so that
        ``vault.pseudonymize_text`` will assign the same pseudonym.

        Returns the (potentially updated) list of entities.
        """
        resolved: list[PIIEntity] = []
        for entity in prompt_entities:
            match_pseudonym = self._find_match(entity.text, entity.label)
            if match_pseudonym is not None:
                # Ensure the exact text maps to the same pseudonym.
                real_value = vault.get_real_value(match_pseudonym)
                if real_value is not None and real_value != entity.text:
                    # Register the new surface form as an alias.
                    vault.add_alias(match_pseudonym, entity.text)
                    # Put the canonical real_value in the forward map so
                    # pseudonymize_text picks it up.
                    vault._forward[entity.text] = match_pseudonym
            resolved.append(entity)
        return resolved

    # ------------------------------------------------------------------
    # Matching helpers
    # ------------------------------------------------------------------

    def _find_match(self, text: str, entity_type: str) -> str | None:
        """Try to find an existing vault entry that matches *text*.

        Strategy (in order):
        1. Exact match in the forward map.
        2. Normalised match (case-insensitive, titles stripped).
        3. Token-overlap match (>= 2 common tokens with same entity type).
        """
        # 1. Exact
        pseudonym = self._vault.get_pseudonym(text)
        if pseudonym is not None:
            return pseudonym

        norm_text = self._normalize(text)
        text_tokens = norm_text.split()

        for real_value, pseudonym in self._vault._forward.items():
            # Skip entries that are not raw real values (aliases already point
            # to a pseudonym via the forward map).
            if real_value.startswith("[") and real_value.endswith("]"):
                continue

            # Ensure the entity type matches.
            entry = self._vault._entries.get(pseudonym)
            if entry is None or entry.entity_type != entity_type:
                continue

            # 2. Normalised match
            norm_existing = self._normalize(real_value)
            if norm_text == norm_existing:
                return pseudonym

            # 3. Token overlap
            existing_tokens = norm_existing.split()
            overlap = self._token_overlap(text_tokens, existing_tokens)
            if overlap >= 2:
                return pseudonym

        return None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase, strip titles and punctuation."""
        lowered = text.lower().strip()
        lowered = _TITLE_PATTERN.sub("", lowered)
        # Strip trailing/leading punctuation.
        lowered = lowered.strip(string.punctuation + " ")
        return lowered

    @staticmethod
    def _token_overlap(tokens1: list[str], tokens2: list[str]) -> int:
        """Count the number of tokens shared between two token lists."""
        set1 = set(tokens1)
        set2 = set(tokens2)
        return len(set1 & set2)
