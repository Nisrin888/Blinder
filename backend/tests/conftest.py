from __future__ import annotations

import os
import pytest

# Set a test master key for vault encryption
os.environ.setdefault("BLINDER_MASTER_KEY", "test_key_for_development_only_32chars00")


@pytest.fixture
def sample_legal_text():
    """A realistic legal document snippet with PII."""
    return (
        "SETTLEMENT AGREEMENT\n\n"
        "This Settlement Agreement is entered into by and between "
        "John Smith (hereinafter referred to as 'Plaintiff') and "
        "Acme Corporation (hereinafter referred to as 'Defendant').\n\n"
        "Plaintiff's attorney, Jane Doe, Esq., of Johnson & Partners LLP, "
        "has negotiated the following terms:\n\n"
        "1. Defendant shall pay Plaintiff the sum of $250,000.\n"
        "2. The deadline for payment is March 15, 2025.\n"
        "3. Plaintiff's Social Security Number 123-45-6789 shall be used "
        "for tax reporting purposes only.\n"
        "4. All correspondence shall be sent to john.smith@email.com "
        "or by phone at (555) 123-4567.\n"
        "5. Case No. 24-CV-00123 shall be dismissed with prejudice.\n\n"
        "Signed this 1st day of January, 2025, in New York, New York."
    )


@pytest.fixture
def sample_prompt():
    """A realistic lawyer prompt referencing entities from the document."""
    return "What is the settlement deadline for John Smith's case?"


@pytest.fixture
def session_salt():
    """A deterministic salt for testing."""
    return b"test_salt_32_bytes_long_exactly!!"


@pytest.fixture
def encryption_key():
    """A derived key for testing."""
    from blinder.encryption import derive_key
    return derive_key("test_key_for_development_only_32chars00", b"test_salt_32_bytes_long_exactly!!")
