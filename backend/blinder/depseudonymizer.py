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
        unresolved: list[str] = []
        for raw in unique_pseudonyms:
            bracketed = f"[{raw}]"
            real_value = self._vault.get_real_value(bracketed)
            if real_value is None:
                unresolved.append(bracketed)
                continue

            # Handle possessive: [PERSON_1]'s -> Jane Smith's
            result = result.replace(f"{bracketed}'s", f"{real_value}'s")
            # Standard replacement.
            result = result.replace(bracketed, real_value)

        # Clean up hallucinated pseudonyms the LLM invented (not in vault).
        # Convert e.g. "[PROF_1]" → "PROF_1" so they read naturally instead
        # of looking like broken tokens in the lawyer view.
        for bracketed in unresolved:
            # Extract a human-readable label: [ARTICLE_1] → "the article"
            label = _humanize_pseudonym(bracketed)
            result = result.replace(f"{bracketed}'s", f"{label}'s")
            result = result.replace(bracketed, label)

        return result


def _humanize_pseudonym(pseudonym: str) -> str:
    """Convert an unresolvable pseudonym to a readable placeholder.

    ``[PROF_1]`` → ``the professor``
    ``[ARTICLE_1]`` → ``the article``
    ``[UNKNOWN_THING_3]`` → ``UNKNOWN_THING_3``
    """
    # Strip brackets: "[PROF_1]" → "PROF_1"
    inner = pseudonym.strip("[]")
    # Split off the counter: "PROF_1" → "PROF"
    parts = inner.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        type_name = parts[0]
    else:
        return inner

    # Map common hallucinated types to natural language
    friendly: dict[str, str] = {
        "PROF": "the professor",
        "PROFESSOR": "the professor",
        "ARTICLE": "the article",
        "PAPER": "the paper",
        "STUDY": "the study",
        "REPORT": "the report",
        "AUTHOR": "the author",
        "RESEARCHER": "the researcher",
        "DOCTOR": "the doctor",
        "COMPANY": "the company",
        "PARTY": "the party",
        "CLIENT": "the client",
        "WITNESS": "the witness",
        "JUDGE": "the judge",
        "DEFENDANT": "the defendant",
        "PLAINTIFF": "the plaintiff",
    }
    return friendly.get(type_name, inner)
