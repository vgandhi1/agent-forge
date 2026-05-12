"""Tests for Ollama URL allowlisting."""

from __future__ import annotations

import pytest

from core.ollama_url import validate_ollama_base_url


def test_validate_loopback_default() -> None:
    assert validate_ollama_base_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_validate_localhost_implicit_http() -> None:
    out = validate_ollama_base_url("localhost:11434")
    assert "127.0.0.1" in out or "localhost" in out
    assert ":11434" in out


def test_reject_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="http"):
        validate_ollama_base_url("ftp://127.0.0.1:11434")


def test_reject_bad_port_without_trust_lan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTFORGE_OLLAMA_TRUST_LAN", raising=False)
    with pytest.raises(ValueError, match="port"):
        validate_ollama_base_url("http://127.0.0.1:9999")
