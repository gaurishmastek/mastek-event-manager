"""Hashing and encryption helpers for secrets and personal data.

- `keyed_hash` is for low-entropy values that must be looked up but never reversed
  (mobile numbers, IPs, OTP codes). It is an HMAC, so a leaked table cannot be brute-forced
  without the server key.
- `token_hash` is for high-entropy random tokens (QR passes), where a plain SHA-256 is enough.
- `encrypt_pii`/`decrypt_pii` keep values we must read back (a guest's mobile, to send an OTP)
  encrypted at rest.
"""

import hashlib
import hmac
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import settings


def keyed_hash(value: str, *, purpose: str) -> str:
    message = f"{purpose}:{value}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache(maxsize=4)
def _fernet(key: str) -> Fernet:
    return Fernet(key.encode())


def encrypt_pii(value: str) -> str:
    return _fernet(settings.pii_encryption_key).encrypt(value.encode()).decode()


def decrypt_pii(value: str) -> str:
    return _fernet(settings.pii_encryption_key).decrypt(value.encode()).decode()
