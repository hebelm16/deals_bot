import logging

import pytest

from config import Config


def _base(monkeypatch):
    monkeypatch.setattr(Config, "TOKEN", "token")
    monkeypatch.setattr(Config, "CHANNEL_ID", "canal")
    monkeypatch.setattr(Config, "USER_ID", "123")
    monkeypatch.setattr(Config, "USE_WEBHOOKS", False)
    monkeypatch.setattr(Config, "WEBHOOK_URL", "")
    monkeypatch.setattr(Config, "AI_HOOK_REQUIRED", False)
    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(Config, "GROQ_API_KEY", "")


def test_validate_correcta(monkeypatch):
    _base(monkeypatch)
    Config.validate()


def test_validate_sin_token(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(Config, "TOKEN", None)
    with pytest.raises(ValueError, match="TOKEN"):
        Config.validate()


def test_validate_webhook_sin_url(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(Config, "USE_WEBHOOKS", True)
    with pytest.raises(ValueError, match="WEBHOOK_URL"):
        Config.validate()


def test_validate_ia_obligatoria_sin_claves(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(Config, "AI_HOOK_REQUIRED", True)
    with pytest.raises(ValueError, match="GEMINI"):
        Config.validate()


def test_avisa_cuando_no_hay_ia(monkeypatch, caplog):
    _base(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="OfertasBot"):
        Config.validate()
    assert "No hay proveedor de IA" in caplog.text
