"""Envelope-style encryption for admin-entered secrets (AI provider keys, SMTP passwords...).

Fernet (AES-128-CBC + HMAC-SHA256) with a key ring for rotation. In production the ring is
loaded from a KMS-managed secret (ADR 0006); the interface stays the same.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..settings import get_settings


class SecretBox:
    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("at least one master key is required")
        self._ring = MultiFernet([Fernet(k.encode()) for k in keys])

    def encrypt(self, plaintext: str) -> str:
        return self._ring.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._ring.decrypt(token.encode()).decode()
        except InvalidToken as e:  # never include the token in the message
            raise ValueError("secret cannot be decrypted with the configured master keys") from e

    def rotate(self, token: str) -> str:
        """Re-encrypt under the primary key."""
        return self._ring.rotate(token.encode()).decode()


@lru_cache
def get_box() -> SecretBox:
    return SecretBox([k.strip() for k in get_settings().a11y_master_keys.split(",") if k.strip()])
