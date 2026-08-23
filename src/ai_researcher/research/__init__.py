"""Karpathy-style deep research: gated multi-turn wiki briefs."""

from .schema import SCHEMA, TURNS
from .wiki import DeepResearcher, decision_to_verdict, parse_decision, parse_scores

__all__ = [
    "SCHEMA",
    "TURNS",
    "DeepResearcher",
    "decision_to_verdict",
    "parse_decision",
    "parse_scores",
]
