"""BYOK key-vault encryption helpers (PRD §3.1, §1 Zero-Retention).

Tenant Google Gemini and E2B API keys are encrypted at rest with a master
Fernet key (AES-128-CBC + HMAC authentication; Fernet is the vetted symmetric
primitive shipped by `cryptography`). The plaintext key only ever exists
in-memory inside a Celery task and is never logged or persisted.

The master key lives in the ``FERNET_KEY`` environment variable. Generate one
with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    """Raised when encryption/decryption of a BYOK secret fails."""


def _fernet() -> Fernet:
    key = settings.FERNET_KEY
    if not key:
        raise VaultError(
            "FERNET_KEY is not configured. Generate one with "
            "Fernet.generate_key() and set it in the environment."
        )
    if isinstance(key, str):
        key = key.encode("utf-8")
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:  # malformed key material
        raise VaultError(f"FERNET_KEY is invalid: {exc}") from exc


def encrypt_key(plaintext: str) -> bytes:
    """Encrypt a BYOK secret for storage in a BinaryField. Returns ciphertext bytes."""
    if plaintext is None:
        raise VaultError("Cannot encrypt a null secret.")
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_key(ciphertext: bytes) -> str:
    """Decrypt a stored BYOK secret back to plaintext. Used only inside workers."""
    if not ciphertext:
        raise VaultError("Cannot decrypt an empty secret.")
    # Django may hand back a memoryview from a BinaryField; normalise to bytes.
    if isinstance(ciphertext, memoryview):
        ciphertext = ciphertext.tobytes()
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise VaultError(
            "Failed to decrypt BYOK secret (wrong FERNET_KEY or corrupted data)."
        ) from exc
