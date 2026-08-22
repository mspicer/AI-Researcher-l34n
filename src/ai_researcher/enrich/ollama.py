"""Thin async Ollama client with model auto-detection.

Everything here degrades rather than raises: when Ollama is down or no suitable
model is installed, callers fall back to heuristics and the run still completes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from ..config import Settings

log = logging.getLogger("ai_researcher.ollama")

# Preferred chat models, best first. Matched as a prefix against installed tags,
# so "qwen2.5:7b-instruct" satisfies a "qwen2.5" preference.
CHAT_PREFERENCES = [
    "qwen3", "llama3.3", "llama3.2", "llama3.1", "qwen2.5", "mistral-nemo",
    "gemma3", "gemma2", "phi4", "mistral", "nous-hermes", "llama3",
]
EMBED_PREFERENCES = [
    "nomic-embed-text", "mxbai-embed-large", "bge-m3", "snowflake-arctic-embed",
    "all-minilm", "embeddinggemma",
]
# Tags that are embedding models even though nothing above matched.
EMBED_MARKERS = ("embed", "bge", "minilm", "e5-")


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base = settings.ollama_host.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(settings.ollama_timeout, connect=8.0))
        self._installed: list[str] | None = None
        self._chat_model: str | None = None
        self._embed_model: str | None = None
        self._lock = asyncio.Lock()
        self.available = False
        self.last_error = ""

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── discovery ────────────────────────────────────────────────────
    async def probe(self) -> bool:
        """Contact Ollama and resolve which models we'll use. Idempotent."""
        async with self._lock:
            if self._installed is not None:
                return self.available
            try:
                resp = await self._client.get(f"{self.base}/api/tags", timeout=8.0)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001 - any failure means "no ollama"
                self._installed = []
                self.available = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Ollama unreachable at %s (%s)", self.base, exc)
                return False

            self._installed = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
            self._chat_model = self._pick(
                self.settings.ollama_chat_model, CHAT_PREFERENCES, embed=False
            )
            self._embed_model = self._pick(
                self.settings.ollama_embed_model, EMBED_PREFERENCES, embed=True
            )
            self.available = bool(self._chat_model)
            if not self.available:
                self.last_error = "no suitable chat model installed"
            log.info(
                "Ollama ready: chat=%s embed=%s (installed: %s)",
                self._chat_model, self._embed_model or "none", ", ".join(self._installed) or "none",
            )
            return self.available

    def _pick(self, configured: str, preferences: list[str], *, embed: bool) -> str | None:
        installed = self._installed or []
        if configured:
            # Honour an explicit choice even if it isn't installed yet — Ollama
            # will pull it on first use, and a hard failure here would be worse.
            return configured
        def is_embed(tag: str) -> bool:
            low = tag.lower()
            return any(m in low for m in EMBED_MARKERS)

        pool = [t for t in installed if is_embed(t) == embed]
        for pref in preferences:
            for tag in pool:
                if tag.lower().startswith(pref.lower()):
                    return tag
        return pool[0] if pool else None

    @property
    def chat_model(self) -> str:
        return self._chat_model or ""

    @property
    def embed_model(self) -> str:
        return self._embed_model or ""

    @property
    def installed(self) -> list[str]:
        return list(self._installed or [])

    # ── generation ───────────────────────────────────────────────────
    async def generate_json(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict[str, Any] | None = None,
        num_predict: int = 512,
        temperature: float = 0.1,
    ) -> dict[str, Any] | None:
        """Generate and parse a JSON object, or None if the model wouldn't."""
        options = {
            "temperature": temperature,
            "num_predict": num_predict,
            "top_p": 0.9,
        }
        body: dict[str, Any] = {
            "model": self.chat_model,
            "prompt": prompt,
            "stream": False,
            "options": options,
            # `format` forces valid JSON on modern Ollama; a schema tightens it
            # further where the model supports structured outputs.
            "format": schema or "json",
            # Reasoning models (qwen3, deepseek-r1) otherwise spend the entire
            # token budget thinking and return an empty response. Extraction
            # needs no chain of thought, so it is switched off outright.
            "think": False,
            # Keep weights resident between items; on a VRAM-tight host the
            # reload between calls costs more than the generation itself.
            "keep_alive": "10m",
        }
        if system:
            body["system"] = system

        text = await self._generate(body)
        if text is None:
            return None
        return _parse_json_object(text)

    async def generate_text(
        self, prompt: str, *, system: str = "", num_predict: int = 900,
        temperature: float = 0.3, timeout: float | None = None,
    ) -> str | None:
        """Long-form generation. `timeout` overrides the client default, which
        is sized for short per-item calls and is too tight for a full brief."""
        body: dict[str, Any] = {
            "model": self.chat_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
            "think": False,
            "keep_alive": "10m",
        }
        if system:
            body["system"] = system
        return await self._generate(body, timeout=timeout)

    async def _generate(
        self, body: dict[str, Any], *, timeout: float | None = None
    ) -> str | None:
        if not self.chat_model:
            return None
        kwargs = {"timeout": timeout} if timeout else {}
        try:
            resp = await self._client.post(
                f"{self.base}/api/generate", json=body, **kwargs
            )
            if resp.status_code == 400 and "think" in body:
                # Ollama versions before thinking support reject the key.
                body = {k: v for k, v in body.items() if k != "think"}
                resp = await self._client.post(
                    f"{self.base}/api/generate", json=body, **kwargs
                )
            resp.raise_for_status()
            return (resp.json().get("response") or "").strip()
        except Exception as exc:  # noqa: BLE001
            detail = str(exc) or type(exc).__name__  # httpx timeouts stringify to ''
            log.warning("Ollama generate failed: %s", detail)
            self.last_error = detail[:200]
            return None

    # ── embeddings ───────────────────────────────────────────────────
    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self._embed_model or not texts:
            return None
        try:
            resp = await self._client.post(
                f"{self.base}/api/embed",
                json={"model": self._embed_model, "input": texts,
                      "keep_alive": "10m"},
            )
            resp.raise_for_status()
            vectors = resp.json().get("embeddings")
        except Exception as exc:  # noqa: BLE001
            log.debug("Ollama embed failed: %s", exc)
            return None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            return None
        return vectors


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Small models still wrap JSON in prose or fences; dig it out."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None
