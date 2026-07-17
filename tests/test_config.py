from __future__ import annotations

import pytest

from mcpserver.config import GrokConfig


def test_grok_config_from_env_and_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_API_URL", "https://example.test/v1/")
    monkeypatch.setenv("GROK_API_KEY", "super-secret")
    monkeypatch.setenv("GROK_MODEL", "grok-custom")
    monkeypatch.setenv("GROK_REASONING_EFFORT", "xhigh")
    monkeypatch.setenv("GROK_REASONING_FIELD", "reasoning_effort")

    config = GrokConfig.from_env()
    masked = config.masked()

    assert config.api_url == "https://example.test/v1"
    assert config.api_key == "super-secret"
    assert masked["apiKeyConfigured"] is True
    assert "super-secret" not in str(masked)
    assert masked["model"] == "grok-custom"
    assert masked["reasoningEffort"] == "xhigh"


def test_grok_config_rejects_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROK_API_URL", "https://example.test/v1")
    monkeypatch.delenv("GROK_API_KEY", raising=False)

    with pytest.raises(ValueError, match="GROK_API_KEY"):
        GrokConfig.from_env()
