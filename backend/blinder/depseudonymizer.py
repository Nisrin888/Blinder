from __future__ import annotations

import re

from blinder.vault import Vault

# Matches pseudonyms like [PERSON_1], [ORG_23], [EMAIL_5], etc.
_PSEUDONYM_RE = re.compile(r"\[([A-Z_]+_\d+)\]")


class Depseudonymizer:
    """Restores real values in LLM output by replacing pseudonym tokens."""

    def __init__(self, vault: Vault) -> None:
        self._vault = vault

    def restore(self, text: str) -> str:
        """Find all ``[TYPE_N]`` tokens in *text* and replace with real values.

        Pseudonyms are sorted by length descending before replacement so that
        longer tokens (e.g. ``[PERSON_10]``) are replaced before shorter ones
        (e.g. ``[PERSON_1]``) to avoid substring collisions.

        Possessive forms such as ``[PERSON_1]'s`` are handled correctly,
        becoming e.g. ``Jane Smith's``.
        """
        # Collect all unique pseudonyms present in the text.
        found_pseudonyms: list[str] = _PSEUDONYM_RE.findall(text)
        if not found_pseudonyms:
            return text

        # Deduplicate and sort by length descending.
        unique_pseudonyms = sorted(
            set(found_pseudonyms),
            key=lambda p: len(p),
            reverse=True,
        )

        result = text
        for raw in unique_pseudonyms:
            bracketed = f"[{raw}]"
            real_value = self._vault.get_real_value(bracketed)
            if real_value is None:
                continue

            # Handle possessive: [PERSON_1]'s -> Jane Smith's
            result = result.replace(f"{bracketed}'s", f"{real_value}'s")
            # Standard replacement.
            result = result.replace(bracketed, real_value)

        return result
