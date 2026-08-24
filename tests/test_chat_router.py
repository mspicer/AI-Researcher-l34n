"""Chat router: OpenRouter + Gemini + quality-gated model selection.

No live vendor calls. Backends are fakes or httpx.MockTransport.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from ai_researcher.config import Settings
from ai_researcher.enrich.chat import (
    ChatRouter,
    GeminiChat,
    OpenAICompatChat,
    redact_secrets,
)


class FakeOllama:
    chat_model = "qwen3:4b"
    embed_model = "nomic-embed-text"
    available = True
    last_error = ""
    installed = ["qwen3:4b"]

    def __init__(self):
        self.json_calls = []
        self.text_calls = []

    async def probe(self):
        return True

    async def generate_json(self, prompt, **kwargs):
        self.json_calls.append(kwargs)
        return {"from": "ollama", "model": kwargs.get("model")}

    async def generate_text(self, prompt, **kwargs):
        self.text_calls.append(kwargs)
        return "ollama-text"

    async def embed(self, texts):
        return None

    async def aclose(self):
        return None

    def model_for(self, *, premium=False):
        return self.chat_model


class RecBackend:
    def __init__(self, name):
        self.name = name
        self.calls = []
        self.last_error = ""

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("json_mode"):
            return json.dumps({"from": self.name, "model": kwargs.get("model")})
        return f"{self.name}-text"

    async def aclose(self):
        return None


def _settings(**kw) -> Settings:
    defaults = dict(
        gemini_model="gemini-2.5-flash",
        gemini_premium_model="gemini-2.5-pro",
        openrouter_model="google/gemini-2.5-flash",
        openrouter_premium_model="anthropic/claude-sonnet-4",
        premium_readiness=0.62,
    )
    defaults.update(kw)
    return Settings(**defaults)


class TestRouting:
    def test_local_only_uses_ollama_for_both_bands(self):
        ollama = FakeOllama()
        router = ChatRouter(_settings(), ollama=ollama)
        asyncio.run(router.probe())
        assert router.model_for(premium=False) == "qwen3:4b"
        assert router.model_for(premium=True) == "qwen3:4b"
        assert router.available

    def test_gemini_is_the_cheap_workhorse(self):
        gemini = RecBackend("gemini")
        router = ChatRouter(
            _settings(gemini_api_key="g"),
            ollama=FakeOllama(),
            gemini=gemini,
        )
        asyncio.run(router.probe())
        assert router.model_for(premium=False) == "gemini-2.5-flash"
        assert router.model_for(premium=True) == "gemini-2.5-pro"

    def test_openrouter_takes_premium_when_both_keys_are_set(self):
        gemini = RecBackend("gemini")
        openrouter = RecBackend("openrouter")
        router = ChatRouter(
            _settings(gemini_api_key="g", openrouter_api_key="o"),
            ollama=FakeOllama(),
            gemini=gemini,
            openrouter=openrouter,
        )
        asyncio.run(router.probe())
        assert router.chat_model == "gemini-2.5-flash"
        assert router.model_for(premium=True) == "anthropic/claude-sonnet-4"

        asyncio.run(router.generate_json("hi", premium=False))
        asyncio.run(router.generate_text("hi", premium=True))
        assert gemini.calls[0]["model"] == "gemini-2.5-flash"
        assert gemini.calls[0]["json_mode"] is True
        assert openrouter.calls[0]["model"] == "anthropic/claude-sonnet-4"
        assert openrouter.calls[0]["json_mode"] is False

    def test_openrouter_only_uses_cheap_then_premium_models(self):
        openrouter = RecBackend("openrouter")
        router = ChatRouter(
            _settings(openrouter_api_key="o"),
            ollama=FakeOllama(),
            openrouter=openrouter,
        )
        assert router.model_for(premium=False) == "google/gemini-2.5-flash"
        assert router.model_for(premium=True) == "anthropic/claude-sonnet-4"

    def test_describe_never_includes_keys(self):
        router = ChatRouter(
            _settings(gemini_api_key="super-secret", openrouter_api_key="also-secret"),
            ollama=FakeOllama(),
            gemini=RecBackend("g"),
            openrouter=RecBackend("o"),
        )
        blob = json.dumps(router.describe())
        assert "super-secret" not in blob
        assert "also-secret" not in blob
        assert router.describe()["gemini"] is True
        assert router.describe()["openrouter"] is True


class TestOpenRouterShape:
    def test_json_mode_sends_response_format_and_bearer(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"ok": true}'}}]},
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = OpenAICompatChat(
            Settings(),
            api_key="sk-test-secret",
            base_url="https://openrouter.ai/api/v1",
            extra_headers={"X-Title": "AI Researcher", "HTTP-Referer": "http://localhost:8899"},
            client=http,
        )
        text = asyncio.run(
            backend.complete(
                model="anthropic/claude-sonnet-4",
                prompt="score this",
                system="json only",
                json_mode=True,
                max_tokens=180,
            )
        )
        asyncio.run(http.aclose())
        assert json.loads(text) == {"ok": True}
        req = captured[0]
        assert str(req.url).endswith("/chat/completions")
        assert req.headers["Authorization"] == "Bearer sk-test-secret"
        assert req.headers["X-Title"] == "AI Researcher"
        body = json.loads(req.content)
        assert body["model"] == "anthropic/claude-sonnet-4"
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["content"] == "score this"


class TestGeminiShape:
    def test_json_mode_sets_mime_type_and_system_instruction(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]},
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = GeminiChat(Settings(), api_key="AIza-test-secret", client=http)
        text = asyncio.run(
            backend.complete(
                model="gemini-2.5-flash",
                prompt="score this",
                system="json only",
                json_mode=True,
            )
        )
        asyncio.run(http.aclose())
        assert json.loads(text) == {"ok": True}
        req = captured[0]
        assert req.url.params["key"] == "AIza-test-secret"
        assert ":generateContent" in str(req.url)
        body = json.loads(req.content)
        assert body["system_instruction"]["parts"][0]["text"] == "json only"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["contents"][0]["parts"][0]["text"] == "score this"

    def test_failed_call_redacts_the_api_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="nope")

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend = GeminiChat(Settings(), api_key="AIza-test-secret", client=http)
        text = asyncio.run(
            backend.complete(model="gemini-2.5-flash", prompt="x")
        )
        asyncio.run(http.aclose())
        assert text is None
        assert "AIza-test-secret" not in backend.last_error
        assert "REDACTED" in backend.last_error or "401" in backend.last_error


class TestRedact:
    def test_query_key_and_bearer_are_stripped(self):
        url = "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=AIzaSecret"
        assert "AIzaSecret" not in redact_secrets(url)
        assert "Bearer REDACTED" in redact_secrets("401 Bearer sk-live-abcdef")
