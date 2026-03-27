"""Encryption/decryption service for sensitive data (certificate private keys)."""
import base64
import hashlib
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "ENC:"


class CryptoService:
    """Symmetric encryption using Fernet (AES-128-CBC + HMAC-SHA256)."""

    _fernet: Optional[Fernet] = None

    @classmethod
    def _get_fernet(cls) -> Fernet:
        if cls._fernet is None:
            key_material = settings.SECRET_KEY.encode("utf-8")
            derived = hashlib.sha256(key_material).digest()
            fernet_key = base64.urlsafe_b64encode(derived)
            cls._fernet = Fernet(fernet_key)
        return cls._fernet

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """Encrypt a string, returning ``ENC:<base64-ciphertext>``."""
        if not plaintext:
            return plaintext
        if plaintext.startswith(ENCRYPTED_PREFIX):
            return plaintext
        token = cls._get_fernet().encrypt(plaintext.encode("utf-8"))
        return ENCRYPTED_PREFIX + token.decode("ascii")

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """Decrypt an ``ENC:``-prefixed string back to plaintext."""
        if not ciphertext or not ciphertext.startswith(ENCRYPTED_PREFIX):
            return ciphertext
        raw = ciphertext[len(ENCRYPTED_PREFIX):]
        return cls._get_fernet().decrypt(raw.encode("ascii")).decode("utf-8")

    @classmethod
    def decrypt_if_encrypted(cls, value: Optional[str]) -> Optional[str]:
        """Return decrypted value if encrypted, otherwise return as-is."""
        if not value:
            return value
        if value.startswith(ENCRYPTED_PREFIX):
            try:
                return cls.decrypt(value)
            except InvalidToken:
                logger.error("Failed to decrypt value — key may have changed")
                return value
        return value
