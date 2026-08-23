"""Enrichment: local-model summarisation, classification, embeddings, judgment."""

from .analyze import Enricher
from .embed import Embedder, load_vectors
from .judge import Judge, judge_text, readiness_of, verdict_of
from .ollama import OllamaClient

__all__ = [
    "Enricher",
    "Embedder",
    "Judge",
    "OllamaClient",
    "judge_text",
    "load_vectors",
    "readiness_of",
    "verdict_of",
]
