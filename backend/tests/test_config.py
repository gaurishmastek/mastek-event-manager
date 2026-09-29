from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import DEFAULT_ENV_FILE, Settings, _env_file
from app.core.email import mask_email, normalize_email
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
        {"email_provider": "console"},
        {"email_provider": "smtp", "smtp_host": "smtp.example.com", "email_from": "a@b.c", "smtp_security": "none"},
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


def test_masks_and_normalizes_email():
    assert normalize_email("  Asha.Patil@Example.COM ") == "asha.patil@example.com"
    assert mask_email("asha.patil@example.com") == "as•••@example.com"


def test_production_accepts_smtp():
    Settings(environment="production", email_provider="smtp", smtp_host="smtp.example.com", email_from="a@b.c", **SAFE)


@pytest.mark.parametrize("missing", ["smtp_host", "email_from"])
def test_smtp_needs_host_and_sender(missing):
    values = {"email_provider": "smtp", "smtp_host": "smtp.example.com", "email_from": "a@b.c", missing: ""}
    with pytest.raises(ValidationError, match="SMTP_HOST and EMAIL_FROM"):
        Settings(**values)


def test_invalid_pii_key_fails_with_generation_hint():
    with pytest.raises(ValidationError, match="Fernet.generate_key"):
        Settings(pii_encryption_key="change-me")


def test_blank_keys_fall_back_to_dev_defaults():
    settings = Settings(secret_key="", pii_encryption_key="")
    assert settings.secret_key == Settings().secret_key
    assert settings.pii_encryption_key == Settings().pii_encryption_key


BACKEND_DIR = Path(__file__).resolve().parents[1]
SMTP_ENV = "EMAIL_PROVIDER=smtp\nSMTP_HOST=smtp.from-file.test\nEMAIL_FROM=events@example.com\nSMTP_PORT=2525\n"


def test_default_env_file_is_backend_dotenv_whatever_the_working_directory():
    assert DEFAULT_ENV_FILE == BACKEND_DIR / ".env"
    assert DEFAULT_ENV_FILE.is_absolute()


def test_env_file_is_read_even_when_started_from_another_directory(tmp_path, monkeypatch):
    env_file = tmp_path / "backend.env"
    env_file.write_text(SMTP_ENV, encoding="utf-8")
    elsewhere = tmp_path / "repo-root"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("EMAIL_PROVIDER=console\n", encoding="utf-8")  # must not be picked up
    monkeypatch.chdir(elsewhere)
    for name in ("EMAIL_PROVIDER", "SMTP_HOST", "EMAIL_FROM", "SMTP_PORT"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=env_file)

    assert (settings.email_provider, settings.smtp_host, settings.smtp_port) == ("smtp", "smtp.from-file.test", 2525)


def test_environment_variables_override_the_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(SMTP_ENV, encoding="utf-8")
    monkeypatch.setenv("SMTP_HOST", "smtp.from-environment.test")

    assert Settings(_env_file=env_file).smtp_host == "smtp.from-environment.test"


def test_missing_env_file_falls_back_to_disabled_email(tmp_path, monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert Settings(_env_file=tmp_path / "missing.env").email_provider == "disabled"


def test_smtp_in_env_file_without_host_fails_at_startup(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("EMAIL_PROVIDER=smtp\nEMAIL_FROM=events@example.com\n", encoding="utf-8")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(ValidationError, match="SMTP_HOST and EMAIL_FROM"):
        Settings(_env_file=env_file)


@pytest.mark.parametrize(("value", "expected"), [(None, DEFAULT_ENV_FILE), ("", None), ("  ", None)])
def test_app_env_file_override(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("APP_ENV_FILE", raising=False)
    else:
        monkeypatch.setenv("APP_ENV_FILE", value)
    assert _env_file() == expected


def test_app_env_file_can_point_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / "custom.env"))
    assert _env_file() == tmp_path / "custom.env"
