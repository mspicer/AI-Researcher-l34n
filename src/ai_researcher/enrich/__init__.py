"""Enrichment: local-model summarisation, classification, and embeddings."""

from .analyze import Enricher
from .embed import Embedder, load_vectors
from .ollama import OllamaClient

__all__ = ["Enricher", "Embedder", "OllamaClient", "load_vectors"]
