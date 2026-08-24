"""Chat backends: local Ollama, cheap Gemini, optional OpenRouter premium.

Embeddings stay on Ollama (or TF-IDF). Chat is routed by *content quality*:

* **Workhorse** — bulk enrichment and low-readiness judgment. Gemini Flash
  if a key is set, else the cheap OpenRouter model, else local Ollama.
* **Premium** — deep-research wiki, the daily brief, and judgment when the
  heuristic readiness is already at the research gate. OpenRouter's high-end
  model if a key is set, else Gemini Pro, else the workhorse.

No keys required. Missing backends drop out; the run still finishes.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..config import Settings
from .ollama import OllamaClient, _parse_json_object

log = logging.getLogger("ai_researcher.chat")

_UNSET = object()

_SECRET = re.compile(
    r"(key=)[^&\s]+|(Bearer\s+)\S+|((?:sk-|or-)[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Keep vendor error URLs out of logs and doctor output."""
    if not text:
        return text
    return _SECRET.sub(lambda m: (m.group(1) or m.group(2) or "") + "REDACTED", text)


class OpenAICompatChat:
    """OpenRouter (and any OpenAI-compatible chat completions endpoint)."""

    def __init__(
        self,
        settings: Settings,
        *,
        api_key: str,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.extra_headers = extra_headers or {}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_timeout, connect=8.0)
        )
        self.last_error = ""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete(
        self,
        *,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 512,
        temperature: float = 0.2,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> str | None:
        if not model or not self.api_key:
            return None
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=self._headers(),
                **kwargs,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            self.last_error = redact_secrets(str(exc) or type(exc).__name__)[:200]
            log.warning("OpenRouter generate failed: %s", self.last_error)
            return None
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            self.last_error = "empty OpenRouter response"
            return None
        message = (choices[0] or {}).get("message") or {}
        text = (message.get("content") or "").strip()
        return text or None


class GeminiChat:
    """Google Gemini generateContent. Cheap workhorse when a key is set."""

    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        settings: Settings,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_timeout, connect=8.0)
        )
        self.last_error = ""

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete(
        self,
        *,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 512,
        temperature: float = 0.2,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> str | None:
        if not model or not self.api_key:
            return None
        gen: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            gen["responseMimeType"] = "application/json"
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen,
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            resp = await self._client.post(
                f"{self.BASE}/models/{model}:generateContent",
                params={"key": self.api_key},
                json=body,
                **kwargs,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            self.last_error = redact_secrets(str(exc) or type(exc).__name__)[:200]
            log.warning("Gemini generate failed: %s", self.last_error)
            return None
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list) or not candidates:
            self.last_error = "empty Gemini response"
            return None
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
        text = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict)).strip()
        return text or None


class ChatRouter:
    """Duck-types :class:`OllamaClient` so enrich / judge / wiki / brief stay unchanged."""

    def __init__(
        self,
        settings: Settings,
        *,
        ollama: OllamaClient | Any | None = None,
        openrouter: Any = _UNSET,
        gemini: Any = _UNSET,
    ):
        self.settings = settings
        self.ollama = ollama if ollama is not None else OllamaClient(settings)
        self._openrouter = openrouter
        self._gemini = gemini
        self.available = False
        self.last_error = ""

    def _openrouter_backend(self) -> Any:
        if self._openrouter is _UNSET:
            key = self.settings.openrouter_api_key
            if key:
                self._openrouter = OpenAICompatChat(
                    self.settings,
                    api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    extra_headers={
                        "HTTP-Referer": f"http://localhost:{self.settings.port}",
                        "X-Title": "AI Researcher",
                    },
                )
            else:
                self._openrouter = None
        return self._openrouter

    def _gemini_backend(self) -> Any:
        if self._gemini is _UNSET:
            key = self.settings.gemini_api_key
            self._gemini = GeminiChat(self.settings, api_key=key) if key else None
        return self._gemini

    def _pair(self, premium: bool) -> tuple[Any, str]:
        """Return ``(backend, model)`` for this quality band. Deterministic; no last-used state."""
        s = self.settings
        gemini = self._gemini_backend()
        openrouter = self._openrouter_backend()
        ollama_model = getattr(self.ollama, "chat_model", "") or ""
        if premium:
            if openrouter:
                return openrouter, s.openrouter_premium_model
            if gemini:
                return gemini, s.gemini_premium_model
            if ollama_model:
                return self.ollama, ollama_model
            return None, ""
        if gemini:
            return gemini, s.gemini_model
        if openrouter:
            return openrouter, s.openrouter_model
        if ollama_model:
            return self.ollama, ollama_model
        return None, ""

    def model_for(self, *, premium: bool = False) -> str:
        return self._pair(premium)[1]

    @property
    def chat_model(self) -> str:
        return self.model_for(premium=False)

    @property
    def embed_model(self) -> str:
        return getattr(self.ollama, "embed_model", "") or ""

    @property
    def installed(self) -> list[str]:
        return list(getattr(self.ollama, "installed", []) or [])

    def describe(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "workhorse": self.model_for(premium=False),
            "premium": self.model_for(premium=True),
            "ollama": getattr(self.ollama, "chat_model", "") or "",
            "embed": self.embed_model,
            "gemini": bool(self.settings.gemini_api_key),
            "openrouter": bool(self.settings.openrouter_api_key),
            "premium_readiness": self.settings.premium_readiness,
            "error": self.last_error or getattr(self.ollama, "last_error", "") or "",
        }

    async def probe(self) -> bool:
        """Discover Ollama models; cloud keys count as available without a round-trip."""
        try:
            await self.ollama.probe()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Ollama probe failed: %s", exc)
        self.available = bool(self.model_for(premium=False))
        if not self.available:
            self.last_error = (
                self.last_error
                or getattr(self.ollama, "last_error", "")
                or "no chat backend configured"
            )
        return self.available

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict[str, Any] | None = None,
        num_predict: int = 512,
        temperature: float = 0.1,
        premium: bool = False,
        model: str | None = None,
    ) -> dict[str, Any] | None:
        backend, use_model = self._pair(premium)
        use_model = model or use_model
        if backend is None or not use_model:
            return None
        if backend is self.ollama:
            return await self.ollama.generate_json(
                prompt,
                system=system,
                schema=schema,
                num_predict=num_predict,
                temperature=temperature,
                premium=premium,
                model=use_model,
            )
        text = await backend.complete(
            model=use_model,
            prompt=prompt,
            system=system,
            max_tokens=num_predict,
            temperature=temperature,
            json_mode=True,
        )
        if getattr(backend, "last_error", ""):
            self.last_error = backend.last_error
        if not text:
            return None
        return _parse_json_object(text)

    async def generate_text(
        self,
        prompt: str,
        *,
        system: str = "",
        num_predict: int = 900,
        temperature: float = 0.3,
        timeout: float | None = None,
        premium: bool = False,
        model: str | None = None,
    ) -> str | None:
        backend, use_model = self._pair(premium)
        use_model = model or use_model
        if backend is None or not use_model:
            return None
        if backend is self.ollama:
            return await self.ollama.generate_text(
                prompt,
                system=system,
                num_predict=num_predict,
                temperature=temperature,
                timeout=timeout,
                premium=premium,
                model=use_model,
            )
        text = await backend.complete(
            model=use_model,
            prompt=prompt,
            system=system,
            max_tokens=num_predict,
            temperature=temperature,
            json_mode=False,
            timeout=timeout,
        )
        if getattr(backend, "last_error", ""):
            self.last_error = backend.last_error
        return text

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        return await self.ollama.embed(texts)

    async def aclose(self) -> None:
        await self.ollama.aclose()
        for backend in (self._openrouter, self._gemini):
            if backend is _UNSET or backend is None:
                continue
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()
