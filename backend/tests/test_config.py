import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings
from app.core.mobile import mask_mobile, normalize_indian_mobile

SAFE = {"secret_key": "s" * 48, "pii_encryption_key": Fernet.generate_key().decode()}


def test_production_accepts_real_keys():
    Settings(environment="production", **SAFE)


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_key": Settings().secret_key},
        {"secret_key": "too-short"},
        {"pii_encryption_key": Settings().pii_encryption_key},
        {"sms_provider": "console"},
    ],
)
def test_production_refuses_unsafe_config(overrides):
    with pytest.raises(ValidationError):
        Settings(environment="production", **{**SAFE, **overrides})


@pytest.mark.parametrize("raw", ["9876543210", "+919876543210", "919876543210", "09876543210", "+91 98765-43210"])
def test_normalizes_indian_mobiles(raw):
    assert normalize_indian_mobile(raw) == "+919876543210"


def test_masks_mobile():
    assert mask_mobile("+919876543210") == "98•••••210"


def test_invalid_pii_key_fails_with_generation_hint():
    with pytest.raises(ValidationError, match="Fernet.generate_key"):
        Settings(pii_encryption_key="change-me")


def test_blank_keys_fall_back_to_dev_defaults():
    settings = Settings(secret_key="", pii_encryption_key="")
    assert settings.secret_key == Settings().secret_key
    assert settings.pii_encryption_key == Settings().pii_encryption_key
