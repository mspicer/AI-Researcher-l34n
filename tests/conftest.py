"""Shared test setup.

The default suite is offline (`-m 'not network'`). `Settings()` still points
at http://localhost:11434, so a developer box with Ollama installed makes the
"without a model" tests take the live-model path and fail. Send every real
OllamaClient at a closed port unless a test opts back in with
AIR_TEST_LIVE_OLLAMA=1.
"""

from __future__ import annotations

import os

import pytest

from ai_researcher.enrich.ollama import OllamaClient

_DEAD_OLLAMA = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def _no_live_ollama(monkeypatch):
    if os.environ.get("AIR_TEST_LIVE_OLLAMA"):
        yield
        return
    original_init = OllamaClient.__init__

    def init(self, settings, *args, **kwargs):
        settings.ollama_host = _DEAD_OLLAMA
        original_init(self, settings, *args, **kwargs)

    monkeypatch.setattr(OllamaClient, "__init__", init)
    yield
