"""Tests for blinder.vault — pseudonymisation vault with encrypted storage."""

from __future__ import annotations

import pytest

from blinder.pii_detector import PIIEntity
from blinder.vault import Vault, VaultEntry


@pytest.fixture
def vault(session_salt: bytes, encryption_key: bytes) -> Vault:
    """Create a fresh Vault instance for each test."""
    return Vault(session_salt=session_salt, encryption_key=encryption_key)


# -----------------------------------------------------------------------
# add_entity
# -----------------------------------------------------------------------


class TestAddEntity:
    """Verify that add_entity creates correct pseudonyms."""

    def test_returns_pseudonym_in_expected_format(self, vault: Vault):
        pseudonym = vault.add_entity("John Smith", "PERSON")
        assert pseudonym == "[PERSON_1]"

    def test_second_entity_same_type_increments_counter(self, vault: Vault):
        p1 = vault.add_entity("John Smith", "PERSON")
        p2 = vault.add_entity("Jane Doe", "PERSON")
        assert p1 == "[PERSON_1]"
        assert p2 == "[PERSON_2]"

    def test_same_entity_returns_same_pseudonym(self, vault: Vault):
        p1 = vault.add_entity("John Smith", "PERSON")
        p2 = vault.add_entity("John Smith", "PERSON")
        assert p1 == p2 == "[PERSON_1]"

    def test_different_entities_get_different_pseudonyms(self, vault: Vault):
        p1 = vault.add_entity("John Smith", "PERSON")
        p2 = vault.add_entity("Jane Doe", "PERSON")
        assert p1 != p2

    def test_different_entity_types_have_independent_counters(self, vault: Vault):
        p_person = vault.add_entity("John Smith", "PERSON")
        p_org = vault.add_entity("Acme Corp", "ORG")
        assert p_person == "[PERSON_1]"
        assert p_org == "[ORG_1]"

    def test_counter_increments_correctly_across_many_entities(self, vault: Vault):
        for i in range(10):
            pseudonym = vault.add_entity(f"Person {i}", "PERSON")
            assert pseudonym == f"[PERSON_{i + 1}]"


# -----------------------------------------------------------------------
# get_pseudonym / get_real_value
# -----------------------------------------------------------------------


class TestLookups:
    """Test bidirectional lookups."""

    def test_get_pseudonym_for_known_entity(self, vault: Vault):
        vault.add_entity("John Smith", "PERSON")
        assert vault.get_pseudonym("John Smith") == "[PERSON_1]"

    def test_get_pseudonym_for_unknown_entity_returns_none(self, vault: Vault):
        assert vault.get_pseudonym("Unknown Person") is None

    def test_get_real_value_for_known_pseudonym(self, vault: Vault):
        vault.add_entity("John Smith", "PERSON")
        assert vault.get_real_value("[PERSON_1]") == "John Smith"

    def test_get_real_value_for_unknown_pseudonym_returns_none(self, vault: Vault):
        assert vault.get_real_value("[PERSON_99]") is None


# -----------------------------------------------------------------------
# add_alias
# -----------------------------------------------------------------------


class TestAddAlias:
    """Test alias registration and lookup."""

    def test_alias_allows_forward_lookup(self, vault: Vault):
        vault.add_entity("John Smith", "PERSON")
        vault.add_alias("[PERSON_1]", "J. Smith")
        assert vault.get_pseudonym("J. Smith") == "[PERSON_1]"

    def test_alias_stored_in_entry(self, vault: Vault):
        vault.add_entity("John Smith", "PERSON")
        vault.add_alias("[PERSON_1]", "J. Smith")
        entries = vault.get_all_entries()
        assert "J. Smith" in entries[0].aliases

    def test_duplicate_alias_not_added_twice(self, vault: Vault):
        vault.add_entity("John Smith", "PERSON")
        vault.add_alias("[PERSON_1]", "J. Smith")
        vault.add_alias("[PERSON_1]", "J. Smith")
        entries = vault.get_all_entries()
        assert entries[0].aliases.count("J. Smith") == 1

    def test_alias_for_unknown_pseudonym_raises_key_error(self, vault: Vault):
        with pytest.raises(KeyError, match="Unknown pseudonym"):
            vault.add_alias("[PERSON_99]", "Nobody")


# -----------------------------------------------------------------------
# pseudonymize_text
# -----------------------------------------------------------------------


class TestPseudonymizeText:
    """Test full text replacement through pseudonymize_text."""

    def test_replaces_single_entity(self, vault: Vault):
        text = "Contact John Smith for details."
        entities = [
            PIIEntity(text="John Smith", label="PERSON", start=8, end=18, confidence=0.95, gate="ner"),
        ]
        result = vault.pseudonymize_text(text, entities)
        assert "John Smith" not in result
        assert "[PERSON_1]" in result
        assert result == "Contact [PERSON_1] for details."

    def test_replaces_multiple_entities(self, vault: Vault):
        text = "John Smith works at Acme Corp."
        entities = [
            PIIEntity(text="John Smith", label="PERSON", start=0, end=10, confidence=0.95, gate="ner"),
            PIIEntity(text="Acme Corp", label="ORG", start=20, end=29, confidence=0.90, gate="ner"),
        ]
        result = vault.pseudonymize_text(text, entities)
        assert "John Smith" not in result
        assert "Acme Corp" not in result
        assert "[PERSON_1]" in result
        assert "[ORG_1]" in result

    def test_preserves_surrounding_text(self, vault: Vault):
        text = "Before John Smith after."
        entities = [
            PIIEntity(text="John Smith", label="PERSON", start=7, end=17, confidence=0.95, gate="ner"),
        ]
        result = vault.pseudonymize_text(text, entities)
        assert result == "Before [PERSON_1] after."


# -----------------------------------------------------------------------
# encrypt_value / decrypt_value
# -----------------------------------------------------------------------


class TestVaultEncryption:
    """Test the vault's convenience encryption/decryption methods."""

    def test_encrypt_decrypt_round_trip(self, vault: Vault):
        original = "John Smith"
        ciphertext, nonce = vault.encrypt_value(original)
        decrypted = vault.decrypt_value(ciphertext, nonce)
        assert decrypted == original

    def test_ciphertext_is_not_plaintext(self, vault: Vault):
        original = "Jane Doe"
        ciphertext, _ = vault.encrypt_value(original)
        assert original.encode("utf-8") not in ciphertext

    def test_encrypt_decrypt_round_trip_unicode(self, vault: Vault):
        original = "Jose Garcia-Lopez"
        ciphertext, nonce = vault.encrypt_value(original)
        decrypted = vault.decrypt_value(ciphertext, nonce)
        assert decrypted == original


# -----------------------------------------------------------------------
# load_entries
# -----------------------------------------------------------------------


class TestLoadEntries:
    """Test bulk loading of entries to restore state."""

    def test_load_entries_restores_forward_and_reverse_maps(self, vault: Vault):
        entries = [
            VaultEntry(entity_type="PERSON", pseudonym="[PERSON_1]", real_value="John Smith"),
            VaultEntry(entity_type="ORG", pseudonym="[ORG_1]", real_value="Acme Corp"),
        ]
        vault.load_entries(entries)

        assert vault.get_pseudonym("John Smith") == "[PERSON_1]"
        assert vault.get_pseudonym("Acme Corp") == "[ORG_1]"
        assert vault.get_real_value("[PERSON_1]") == "John Smith"
        assert vault.get_real_value("[ORG_1]") == "Acme Corp"

    def test_load_entries_restores_counters(self, vault: Vault):
        entries = [
            VaultEntry(entity_type="PERSON", pseudonym="[PERSON_3]", real_value="Alice"),
        ]
        vault.load_entries(entries)

        # The next PERSON entity should be PERSON_4
        next_pseudonym = vault.add_entity("Bob", "PERSON")
        assert next_pseudonym == "[PERSON_4]"

    def test_load_entries_restores_aliases(self, vault: Vault):
        entries = [
            VaultEntry(
                entity_type="PERSON",
                pseudonym="[PERSON_1]",
                real_value="John Smith",
                aliases=["J. Smith", "Johnny"],
            ),
        ]
        vault.load_entries(entries)

        assert vault.get_pseudonym("J. Smith") == "[PERSON_1]"
        assert vault.get_pseudonym("Johnny") == "[PERSON_1]"

    def test_load_entries_with_multiple_types(self, vault: Vault):
        entries = [
            VaultEntry(entity_type="PERSON", pseudonym="[PERSON_2]", real_value="Alice"),
            VaultEntry(entity_type="PERSON", pseudonym="[PERSON_5]", real_value="Bob"),
            VaultEntry(entity_type="ORG", pseudonym="[ORG_3]", real_value="Globex"),
        ]
        vault.load_entries(entries)

        # Next PERSON should be 6, next ORG should be 4
        assert vault.add_entity("Charlie", "PERSON") == "[PERSON_6]"
        assert vault.add_entity("Initech", "ORG") == "[ORG_4]"

    def test_get_all_entries_returns_loaded_entries(self, vault: Vault):
        entries = [
            VaultEntry(entity_type="PERSON", pseudonym="[PERSON_1]", real_value="John Smith"),
        ]
        vault.load_entries(entries)

        all_entries = vault.get_all_entries()
        assert len(all_entries) == 1
        assert all_entries[0].real_value == "John Smith"
