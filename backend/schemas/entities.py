from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PIIEntity:
    """A detected PII entity with its location and metadata."""
    text: str
    label: str
    start: int
    end: int
    confidence: float = 1.0
    gate: str = "ner"  # "presidio" or "ner"


@dataclass
class VaultEntryData:
    """In-memory representation of a vault entry."""
    entity_type: str
    pseudonym: str
    real_value: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class ThreatDetail:
    """A detected threat in input text."""
    threat_type: str
    description: str
    severity: str  # "low", "medium", "high"
    matched_pattern: str = ""


@dataclass
class SanitizeResult:
    """Result of threat sanitization."""
    is_safe: bool
    threats: list[ThreatDetail] = field(default_factory=list)
    cleaned_text: str = ""
