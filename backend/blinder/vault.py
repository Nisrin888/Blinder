from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from blinder.encryption import encrypt, decrypt
from blinder.pii_detector import PIIEntity


@dataclass
class VaultEntry:
    """A single vault record mapping a real value to its pseudonym."""

    entity_type: str
    pseudonym: str
    real_value: str
    aliases: list[str] = field(default_factory=list)


class Vault:
    """Pseudonymisation vault with per-session AES-256-GCM encrypted storage.

    The vault maintains bidirectional mappings between real PII values and
    deterministic pseudonyms such as ``[PERSON_1]``, ``[ORG_2]``, etc.
    """

    def __init__(self, session_salt: bytes, encryption_key: bytes) -> None:
        self.session_salt = session_salt
        self.encryption_key = encryption_key

        # real_value -> pseudonym
        self._forward: dict[str, str] = {}
        # pseudonym  -> real_value
        self._reverse: dict[str, str] = {}
        # pseudonym  -> VaultEntry
        self._entries: dict[str, VaultEntry] = {}
        # entity_type -> next counter
        self._counters: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def add_entity(self, real_value: str, entity_type: str) -> str:
        """Register *real_value* and return its pseudonym.

        If *real_value* is already known the existing pseudonym is returned.
        Otherwise a new sequential pseudonym like ``[PERSON_1]`` is created.
        """
        if real_value in self._forward:
            return self._forward[real_value]

        counter = self._counters.get(entity_type, 0) + 1
        self._counters[entity_type] = counter
        pseudonym = f"[{entity_type}_{counter}]"

        self._forward[real_value] = pseudonym
        self._reverse[pseudonym] = real_value
        self._entries[pseudonym] = VaultEntry(
            entity_type=entity_type,
            pseudonym=pseudonym,
            real_value=real_value,
        )
        return pseudonym

    def get_pseudonym(self, real_value: str) -> str | None:
        """Look up the pseudonym for *real_value*, or ``None``."""
        return self._forward.get(real_value)

    def get_real_value(self, pseudonym: str) -> str | None:
        """Look up the real value for *pseudonym*, or ``None``."""
        return self._reverse.get(pseudonym)

    def add_alias(self, pseudonym: str, alias: str) -> None:
        """Register *alias* as an alternative reference for *pseudonym*."""
        if pseudonym not in self._entries:
            raise KeyError(f"Unknown pseudonym: {pseudonym}")
        entry = self._entries[pseudonym]
        if alias not in entry.aliases:
            entry.aliases.append(alias)
        # Allow forward lookup by alias as well.
        self._forward[alias] = pseudonym

    # ------------------------------------------------------------------
    # Text-level operations
    # ------------------------------------------------------------------

    def pseudonymize_text(self, text: str, entities: list[PIIEntity]) -> str:
        """Replace each detected entity span in *text* with its pseudonym.

        Entities are processed from the end of the string so that earlier
        indices remain valid as replacements change the string length.
        """
        # Sort by start position descending so we can splice in-place.
        sorted_entities = sorted(entities, key=lambda e: e.start, reverse=True)
        result = text
        for entity in sorted_entities:
            pseudonym = self.add_entity(entity.text, entity.label)
            result = result[: entity.start] + pseudonym + result[entity.end :]
        return result

    # ------------------------------------------------------------------
    # Bulk / persistence helpers
    # ------------------------------------------------------------------

    def get_all_entries(self) -> list[VaultEntry]:
        """Return all vault entries (useful for serialisation)."""
        return list(self._entries.values())

    def load_entries(self, entries: list[VaultEntry]) -> None:
        """Bulk-load entries (used when restoring a session from the DB)."""
        for entry in entries:
            self._forward[entry.real_value] = entry.pseudonym
            self._reverse[entry.pseudonym] = entry.real_value
            self._entries[entry.pseudonym] = entry

            # Rebuild counters so new entities get the right sequence.
            parts = entry.pseudonym.strip("[]").rsplit("_", 1)
            if len(parts) == 2:
                entity_type, num_str = parts
                try:
                    num = int(num_str)
                except ValueError:
                    continue
                if num > self._counters.get(entity_type, 0):
                    self._counters[entity_type] = num

            # Re-register aliases.
            for alias in entry.aliases:
                self._forward[alias] = entry.pseudonym

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def encrypt_value(self, value: str) -> tuple[bytes, bytes]:
        """Encrypt *value* with the session encryption key."""
        return encrypt(value, self.encryption_key)

    def decrypt_value(self, ciphertext: bytes, nonce: bytes) -> str:
        """Decrypt *ciphertext* with the session encryption key."""
        return decrypt(ciphertext, self.encryption_key, nonce)
