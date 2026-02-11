from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ThreatDetail:
    """Description of a single detected threat."""

    threat_type: str
    description: str
    severity: str  # "low", "medium", "high"
    matched_pattern: str


@dataclass
class SanitizeResult:
    """Result of running the full sanitisation pipeline on a text."""

    is_safe: bool
    threats: list[ThreatDetail]
    cleaned_text: str


# ---------------------------------------------------------------------------
# Compiled injection patterns  (pattern, severity, description)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        "high",
        "Attempt to override system instructions",
    ),
    (
        re.compile(r"ignore\s+all\s+prior", re.IGNORECASE),
        "high",
        "Attempt to override prior instructions",
    ),
    (
        re.compile(r"disregard\s+(all\s+)?(the\s+)?above", re.IGNORECASE),
        "high",
        "Attempt to disregard above context",
    ),
    (
        re.compile(r"repeat\s+your\s+system\s+prompt", re.IGNORECASE),
        "high",
        "Attempt to extract system prompt",
    ),
    (
        re.compile(r"what\s+are\s+your\s+instructions", re.IGNORECASE),
        "high",
        "Attempt to extract system instructions",
    ),
    (
        re.compile(r"print\s+your\s+prompt", re.IGNORECASE),
        "high",
        "Attempt to extract prompt",
    ),
    (
        re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
        "medium",
        "Persona override attempt",
    ),
    (
        re.compile(r"act\s+as\s+if", re.IGNORECASE),
        "medium",
        "Persona override attempt",
    ),
    (
        re.compile(r"pretend\s+you\s+are", re.IGNORECASE),
        "medium",
        "Persona override attempt",
    ),
    (
        re.compile(r"do\s+anything\s+now", re.IGNORECASE),
        "high",
        "DAN jailbreak attempt",
    ),
    (
        re.compile(r"developer\s+mode", re.IGNORECASE),
        "high",
        "Developer mode jailbreak attempt",
    ),
    (
        re.compile(r"\bjailbreak\b", re.IGNORECASE),
        "high",
        "Explicit jailbreak keyword",
    ),
    (
        re.compile(r"\bDAN\b"),
        "medium",
        "Possible DAN jailbreak reference",
    ),
]

# Safe delimiters used to wrap document content sent to the LLM.
_BEGIN_DELIMITER = "### BEGIN DOCUMENT ###"
_END_DELIMITER = "### END DOCUMENT ###"

# Homoglyph pairs: (latin char, look-alike unicode char, script name)
_HOMOGLYPHS: list[tuple[str, str, str]] = [
    ("a", "\u0430", "Cyrillic"),
    ("c", "\u0441", "Cyrillic"),
    ("e", "\u0435", "Cyrillic"),
    ("o", "\u043e", "Cyrillic"),
    ("p", "\u0440", "Cyrillic"),
    ("x", "\u0445", "Cyrillic"),
    ("y", "\u0443", "Cyrillic"),
    ("s", "\u0455", "Cyrillic"),
    ("i", "\u0456", "Cyrillic"),
    ("A", "\u0410", "Cyrillic"),
    ("B", "\u0412", "Cyrillic"),
    ("C", "\u0421", "Cyrillic"),
    ("E", "\u0415", "Cyrillic"),
    ("H", "\u041d", "Cyrillic"),
    ("K", "\u041a", "Cyrillic"),
    ("M", "\u041c", "Cyrillic"),
    ("O", "\u041e", "Cyrillic"),
    ("P", "\u0420", "Cyrillic"),
    ("T", "\u0422", "Cyrillic"),
    ("X", "\u0425", "Cyrillic"),
    # Greek look-alikes
    ("o", "\u03bf", "Greek"),
    ("v", "\u03bd", "Greek"),
]

# Zero-width and invisible characters to strip.
_INVISIBLE_CHARS = {
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM
}

# Bidi override range U+202A-U+202E and isolate range U+2066-U+2069.
_BIDI_RANGE = set(chr(c) for c in range(0x202A, 0x202F)) | set(
    chr(c) for c in range(0x2066, 0x206A)
)

# Tag characters U+E0001-U+E007F.
_TAG_RANGE = set(chr(c) for c in range(0xE0001, 0xE0080))

# General category "Cf" (format chars) that we want to remove, minus ones
# we explicitly keep (e.g. soft-hyphen is harmless).
_FORMAT_CHARS_KEEP = {"\u00ad"}  # SOFT HYPHEN -- harmless


# ---------------------------------------------------------------------------
# Sanitiser
# ---------------------------------------------------------------------------


class ThreatSanitizer:
    """Unicode stripping and prompt-injection detection."""

    def sanitize(self, text: str) -> SanitizeResult:
        """Run all threat checks and return a ``SanitizeResult``."""
        threats: list[ThreatDetail] = []

        # 1. Strip dangerous unicode
        cleaned = self._strip_unicode_threats(text)

        # 2. Detect homoglyphs (run on original text so we can report them)
        threats.extend(self._detect_homoglyphs(text))

        # 3. Detect prompt injection
        threats.extend(self._detect_prompt_injection(cleaned))

        # 4. Detect delimiter injection
        threats.extend(self._detect_delimiter_injection(cleaned))

        is_safe = all(t.severity != "high" for t in threats)
        return SanitizeResult(
            is_safe=is_safe,
            threats=threats,
            cleaned_text=cleaned,
        )

    # ------------------------------------------------------------------
    # Unicode threat stripping
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_unicode_threats(text: str) -> str:
        """Normalise to NFKC and remove dangerous invisible characters."""
        # NFKC normalisation collapses compatibility characters.
        text = unicodedata.normalize("NFKC", text)

        result: list[str] = []
        for ch in text:
            if ch in _INVISIBLE_CHARS:
                continue
            if ch in _BIDI_RANGE:
                continue
            if ch in _TAG_RANGE:
                continue
            # Strip general "Cf" (format) category chars we have not
            # explicitly decided to keep.
            if unicodedata.category(ch) == "Cf" and ch not in _FORMAT_CHARS_KEEP:
                continue
            result.append(ch)
        return "".join(result)

    # ------------------------------------------------------------------
    # Homoglyph detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_homoglyphs(text: str) -> list[ThreatDetail]:
        """Check for common Cyrillic/Greek characters mixed with Latin."""
        has_latin = bool(re.search(r"[a-zA-Z]", text))
        if not has_latin:
            return []

        found: list[ThreatDetail] = []
        seen: set[str] = set()
        for _latin, lookalike, script in _HOMOGLYPHS:
            if lookalike in text and lookalike not in seen:
                seen.add(lookalike)
                found.append(
                    ThreatDetail(
                        threat_type="homoglyph",
                        description=(
                            f"{script} character U+{ord(lookalike):04X} "
                            f"resembling Latin '{_latin}' found in text"
                        ),
                        severity="medium",
                        matched_pattern=lookalike,
                    )
                )
        return found

    # ------------------------------------------------------------------
    # Prompt injection detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_prompt_injection(text: str) -> list[ThreatDetail]:
        """Pattern-match against known prompt injection phrases."""
        threats: list[ThreatDetail] = []
        for pattern, severity, description in _INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                threats.append(
                    ThreatDetail(
                        threat_type="prompt_injection",
                        description=description,
                        severity=severity,
                        matched_pattern=match.group(),
                    )
                )
        return threats

    # ------------------------------------------------------------------
    # Delimiter injection detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_delimiter_injection(text: str) -> list[ThreatDetail]:
        """Detect if the user-supplied text contains our safe delimiters."""
        threats: list[ThreatDetail] = []
        for delimiter in (_BEGIN_DELIMITER, _END_DELIMITER):
            if delimiter in text:
                threats.append(
                    ThreatDetail(
                        threat_type="delimiter_injection",
                        description=(
                            f"Text contains reserved delimiter: {delimiter}"
                        ),
                        severity="high",
                        matched_pattern=delimiter,
                    )
                )
        return threats

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def wrap_document_content(text: str) -> str:
        """Wrap *text* in safe delimiters for inclusion in an LLM context."""
        return f"{_BEGIN_DELIMITER}\n{text}\n{_END_DELIMITER}"
