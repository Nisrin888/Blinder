"""Tests for blinder.depseudonymizer — reverse pseudonym mapping in LLM output."""

from __future__ import annotations

import pytest

from blinder.depseudonymizer import Depseudonymizer
from blinder.vault import Vault


@pytest.fixture
def vault(session_salt: bytes, encryption_key: bytes) -> Vault:
    return Vault(session_salt=session_salt, encryption_key=encryption_key)


@pytest.fixture
def depseudonymizer(vault: Vault) -> Depseudonymizer:
    return Depseudonymizer(vault)


# -----------------------------------------------------------------------
# Basic replacement
# -----------------------------------------------------------------------


class TestBasicReplacement:
    """Verify that pseudonym tokens are replaced with real values."""

    def test_single_pseudonym_replaced(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        vault.add_entity("John Smith", "PERSON")
        text = "The defendant is [PERSON_1]."
        result = depseudonymizer.restore(text)
        assert result == "The defendant is John Smith."

    def test_org_pseudonym_replaced(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        vault.add_entity("Acme Corp", "ORG")
        text = "[ORG_1] filed the motion."
        result = depseudonymizer.restore(text)
        assert result == "Acme Corp filed the motion."


# -----------------------------------------------------------------------
# Possessive handling
# -----------------------------------------------------------------------


class TestPossessiveHandling:
    """Possessive forms like [PERSON_1]'s should become real_value's."""

    def test_possessive_replaced_correctly(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        vault.add_entity("Jane Doe", "PERSON")
        text = "[PERSON_1]'s attorney filed a brief."
        result = depseudonymizer.restore(text)
        assert result == "Jane Doe's attorney filed a brief."

    def test_possessive_and_standard_in_same_text(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        vault.add_entity("Jane Doe", "PERSON")
        text = "[PERSON_1]'s case was reviewed by [PERSON_1]."
        result = depseudonymizer.restore(text)
        assert result == "Jane Doe's case was reviewed by Jane Doe."


# -----------------------------------------------------------------------
# Multiple pseudonyms
# -----------------------------------------------------------------------


class TestMultiplePseudonyms:
    """Multiple different pseudonyms in the same text."""

    def test_multiple_types_replaced(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        vault.add_entity("John Smith", "PERSON")
        vault.add_entity("Acme Corp", "ORG")
        vault.add_entity("New York", "LOCATION")
        text = "[PERSON_1] sued [ORG_1] in [LOCATION_1]."
        result = depseudonymizer.restore(text)
        assert result == "John Smith sued Acme Corp in New York."

    def test_multiple_same_type_replaced(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        vault.add_entity("John Smith", "PERSON")
        vault.add_entity("Jane Doe", "PERSON")
        text = "[PERSON_1] and [PERSON_2] reached an agreement."
        result = depseudonymizer.restore(text)
        assert result == "John Smith and Jane Doe reached an agreement."


# -----------------------------------------------------------------------
# Substring collision (PERSON_10 vs PERSON_1)
# -----------------------------------------------------------------------


class TestSubstringCollision:
    """[PERSON_10] must be replaced before [PERSON_1] to avoid partial matches."""

    def test_person_10_replaced_before_person_1(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        # Add 10 persons
        vault.add_entity("Alice", "PERSON")       # [PERSON_1]
        vault.add_entity("Bob", "PERSON")          # [PERSON_2]
        vault.add_entity("Charlie", "PERSON")      # [PERSON_3]
        vault.add_entity("David", "PERSON")        # [PERSON_4]
        vault.add_entity("Eve", "PERSON")          # [PERSON_5]
        vault.add_entity("Frank", "PERSON")        # [PERSON_6]
        vault.add_entity("Grace", "PERSON")        # [PERSON_7]
        vault.add_entity("Heidi", "PERSON")        # [PERSON_8]
        vault.add_entity("Ivan", "PERSON")         # [PERSON_9]
        vault.add_entity("Judy", "PERSON")         # [PERSON_10]

        text = "[PERSON_10] met with [PERSON_1]."
        result = depseudonymizer.restore(text)
        # PERSON_10 -> Judy, PERSON_1 -> Alice (no substring collision)
        assert result == "Judy met with Alice."
        assert "0]" not in result  # leftover from bad replacement

    def test_no_partial_match_artifacts(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        """Ensure replacing [PERSON_1] does not corrupt [PERSON_10]."""
        vault.add_entity("Alice", "PERSON")       # [PERSON_1]
        for i in range(8):
            vault.add_entity(f"Person_{i+2}", "PERSON")
        vault.add_entity("Judy", "PERSON")         # [PERSON_10]

        text = "Report: [PERSON_1] and [PERSON_10] are co-defendants."
        result = depseudonymizer.restore(text)
        assert "Alice" in result
        assert "Judy" in result
        # No leftover bracket fragments
        assert "[" not in result
        assert "]" not in result


# -----------------------------------------------------------------------
# Unknown pseudonyms left unchanged
# -----------------------------------------------------------------------


class TestUnknownPseudonyms:
    """Pseudonyms not in the vault should be left as-is."""

    def test_unknown_pseudonym_untouched(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        vault.add_entity("John Smith", "PERSON")
        text = "[PERSON_1] works with [PERSON_99]."
        result = depseudonymizer.restore(text)
        assert result == "John Smith works with [PERSON_99]."

    def test_all_unknown_pseudonyms_untouched(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        text = "[ORG_5] and [PERSON_3] are referenced."
        result = depseudonymizer.restore(text)
        assert result == "[ORG_5] and [PERSON_3] are referenced."

    def test_text_without_pseudonyms_unchanged(
        self, vault: Vault, depseudonymizer: Depseudonymizer
    ):
        text = "No pseudonyms in this text."
        result = depseudonymizer.restore(text)
        assert result == "No pseudonyms in this text."
