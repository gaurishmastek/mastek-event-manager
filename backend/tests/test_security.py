from datetime import timedelta

import jwt

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.mixins import utcnow


def test_password_is_hashed_with_argon2id_and_salted():
    first = hash_password("Correct-horse-42")
    second = hash_password("Correct-horse-42")
    assert first.startswith("$argon2id$")
    assert first != second
    assert "Correct-horse-42" not in first


def test_verify_password():
    stored = hash_password("Correct-horse-42")
    assert verify_password("Correct-horse-42", stored)
    assert not verify_password("wrong-password-1", stored)
    assert not verify_password("Correct-horse-42", None)
    assert not verify_password("Correct-horse-42", "not-a-hash")


def test_access_token_round_trip():
    token, expires_in = create_access_token(7, "admin", 0)
    claims = decode_access_token(token)
    assert claims is not None
    assert claims["sub"] == "7"
    assert expires_in == get_settings().access_token_expire_minutes * 60


def test_rejects_expired_token():
    now = utcnow()
    payload = {
        "sub": "1",
        "type": "access",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
    }
    token = jwt.encode(payload, get_settings().secret_key, algorithm="HS256")
    assert decode_access_token(token) is None


def test_rejects_token_signed_with_another_key():
    payload = {"sub": "1", "type": "access", "iat": utcnow(), "exp": utcnow() + timedelta(hours=1)}
    token = jwt.encode(payload, "another-secret-key-that-is-also-long-enough", algorithm="HS256")
    assert decode_access_token(token) is None


def test_rejects_unsigned_token():
    payload = {"sub": "1", "type": "access", "iat": utcnow(), "exp": utcnow() + timedelta(hours=1)}
    token = jwt.encode(payload, None, algorithm="none")
    assert decode_access_token(token) is None


def test_rejects_token_of_wrong_type():
    payload = {"sub": "1", "type": "refresh", "iat": utcnow(), "exp": utcnow() + timedelta(hours=1)}
    token = jwt.encode(payload, get_settings().secret_key, algorithm="HS256")
    assert decode_access_token(token) is None
