"""Symmetric encryption utilities for protecting secrets at rest.

Uses Fernet (symmetric authenticated encryption) with a key derived from settings.SECRET_KEY.
This enables reversible encryption for fields like API keys.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


# Derive a 32-byte urlsafe key for Fernet from the application's SECRET_KEY
# Note: Rotating SECRET_KEY will invalidate existing ciphertexts.
# If key rotation is required, implement a keyring with key IDs.
_DEF_FERNET_KEY: bytes = base64.urlsafe_b64encode(
    hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
)


def _get_fernet() -> Fernet:
    return Fernet(_DEF_FERNET_KEY)

# encrypt_str 指定一个字符串加密函数，返回 URL 安全的 base64 编码的密文。
def encrypt_str(plain: str) -> str:
    """Encrypt a string and return urlsafe base64 token."""
    if plain is None:
        return ""
    f = _get_fernet()
    token: bytes = f.encrypt(plain.encode("utf-8"))
    return token.decode("utf-8")

# decrypt_str 指定一个解密函数，将密文解密回原始字符串。如果密文无效或损坏，则返回 None。
def decrypt_str(token: str) -> Optional[str]:
    """Decrypt a token back to string. Returns None if invalid/corrupted."""
    if not token:
        return None
    f = _get_fernet()
    try:
        data = f.decrypt(token.encode("utf-8"))
        return data.decode("utf-8")
    except (InvalidToken, Exception):
        return None

# mask_secret 指定一个函数，用于返回秘密的掩码表示，只显示最后 4 个字符。如果输入为空或 None，则返回 None。
def mask_secret(plain: Optional[str]) -> Optional[str]:
    """Return a masked representation of a secret, revealing only last 4 chars.
    If plain is None or empty, returns None.
    """
    if not plain:
        return None
    n = len(plain)
    if n <= 4:
        return "*" * n
    return "*" * (n - 4) + plain[-4:]

