"""Trend detection: clustering, ranking, topic velocity, and the daily brief."""

from .brief import generate_brief
from .cluster import build_clusters
from .score import score_cluster, score_item
from .topics import (
    backfill_topics,
    compute_daily_topics,
    rising_topics,
    sparkline_series,
    top_entities,
)

__all__ = [
    "backfill_topics",
    "build_clusters",
    "compute_daily_topics",
    "generate_brief",
    "rising_topics",
    "score_cluster",
    "score_item",
    "sparkline_series",
    "top_entities",
]
