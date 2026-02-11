from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


def derive_key(master_key: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES-256 key from a master key string and session salt.

    Uses PBKDF2-HMAC-SHA256 with 600 000 iterations as a secure key derivation
    function.  Argon2id would be preferred but PBKDF2 from the ``cryptography``
    library is used as a universally-available fallback.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600_000,
    )
    return kdf.derive(master_key.encode("utf-8"))


def encrypt(plaintext: str, key: bytes) -> tuple[bytes, bytes]:
    """AES-256-GCM encrypt *plaintext* with *key*.

    Returns ``(ciphertext, nonce)`` where *nonce* is a random 12-byte value.
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, key: bytes, nonce: bytes) -> str:
    """AES-256-GCM decrypt *ciphertext* with *key* and *nonce*.

    Returns the plaintext string.
    """
    aesgcm = AESGCM(key)
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext_bytes.decode("utf-8")
