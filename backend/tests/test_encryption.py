"""Tests for blinder.encryption — AES-256-GCM encrypt/decrypt and key derivation."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from blinder.encryption import derive_key, encrypt, decrypt


class TestEncryptDecryptRoundTrip:
    """Verify that encrypt followed by decrypt returns the original plaintext."""

    def test_round_trip_basic(self, encryption_key: bytes):
        plaintext = "Jane Smith, SSN 123-45-6789"
        ciphertext, nonce = encrypt(plaintext, encryption_key)
        result = decrypt(ciphertext, encryption_key, nonce)
        assert result == plaintext

    def test_round_trip_empty_string(self, encryption_key: bytes):
        plaintext = ""
        ciphertext, nonce = encrypt(plaintext, encryption_key)
        result = decrypt(ciphertext, encryption_key, nonce)
        assert result == plaintext

    def test_round_trip_unicode(self, encryption_key: bytes):
        plaintext = "Nombre: Jose Garcia-Lopez, direccion: Calle 123"
        ciphertext, nonce = encrypt(plaintext, encryption_key)
        result = decrypt(ciphertext, encryption_key, nonce)
        assert result == plaintext

    def test_round_trip_long_text(self, encryption_key: bytes):
        plaintext = "A" * 100_000
        ciphertext, nonce = encrypt(plaintext, encryption_key)
        result = decrypt(ciphertext, encryption_key, nonce)
        assert result == plaintext


class TestDifferentPlaintextsDifferentCiphertexts:
    """Different plaintexts must produce different ciphertexts."""

    def test_different_plaintexts_produce_different_ciphertexts(self, encryption_key: bytes):
        ct1, _ = encrypt("Alice", encryption_key)
        ct2, _ = encrypt("Bob", encryption_key)
        assert ct1 != ct2

    def test_same_plaintext_produces_different_ciphertexts_due_to_random_nonce(
        self, encryption_key: bytes
    ):
        """AES-GCM uses a random nonce each time, so even the same plaintext
        should produce different ciphertexts on successive calls."""
        ct1, nonce1 = encrypt("same text", encryption_key)
        ct2, nonce2 = encrypt("same text", encryption_key)
        # Nonces should differ (random 12 bytes, collision astronomically unlikely)
        assert nonce1 != nonce2
        # Ciphertexts should therefore also differ
        assert ct1 != ct2


class TestWrongKeyFails:
    """Decryption with the wrong key must raise an error."""

    def test_wrong_key_raises_invalid_tag(self, session_salt: bytes):
        correct_key = derive_key("correct_master_key", session_salt)
        wrong_key = derive_key("wrong_master_key", session_salt)

        plaintext = "Top secret PII data"
        ciphertext, nonce = encrypt(plaintext, correct_key)

        with pytest.raises(InvalidTag):
            decrypt(ciphertext, wrong_key, nonce)

    def test_corrupted_ciphertext_raises_invalid_tag(self, encryption_key: bytes):
        plaintext = "Sensitive information"
        ciphertext, nonce = encrypt(plaintext, encryption_key)

        # Flip a byte in the ciphertext
        corrupted = bytearray(ciphertext)
        corrupted[0] ^= 0xFF
        corrupted = bytes(corrupted)

        with pytest.raises(InvalidTag):
            decrypt(corrupted, encryption_key, nonce)

    def test_wrong_nonce_raises_invalid_tag(self, encryption_key: bytes):
        plaintext = "Sensitive information"
        ciphertext, nonce = encrypt(plaintext, encryption_key)

        wrong_nonce = bytes(b ^ 0xFF for b in nonce)

        with pytest.raises(InvalidTag):
            decrypt(ciphertext, encryption_key, wrong_nonce)


class TestDeriveKey:
    """Tests for the PBKDF2-based key derivation function."""

    def test_consistent_output_for_same_inputs(self):
        key1 = derive_key("my_master_key", b"salt_value_here!")
        key2 = derive_key("my_master_key", b"salt_value_here!")
        assert key1 == key2

    def test_produces_32_bytes(self, session_salt: bytes):
        key = derive_key("some_master_key", session_salt)
        assert len(key) == 32

    def test_different_salts_produce_different_keys(self):
        salt_a = b"salt_a_16_bytes!"
        salt_b = b"salt_b_16_bytes!"
        key_a = derive_key("same_master_key", salt_a)
        key_b = derive_key("same_master_key", salt_b)
        assert key_a != key_b

    def test_different_master_keys_produce_different_keys(self, session_salt: bytes):
        key_a = derive_key("master_key_alpha", session_salt)
        key_b = derive_key("master_key_bravo", session_salt)
        assert key_a != key_b

    def test_output_is_bytes(self, session_salt: bytes):
        key = derive_key("test_key", session_salt)
        assert isinstance(key, bytes)
