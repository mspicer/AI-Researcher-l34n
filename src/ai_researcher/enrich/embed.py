"""Embedding generation and storage.

Coverage matters more than it looks: clustering can only merge items that have
a vector, so every un-embedded item becomes a singleton story. The per-run cap
is therefore set well above a normal day's ingest rather than tuned for speed —
embedding runs at roughly 6 items/sec, so even a full backlog is a few minutes.

Optional: with no embedding model installed, clustering falls back to TF-IDF,
which is meaningfully worse at spotting "same story, different words" but keeps
the dashboard working out of the box.
"""

from __future__ import annotations

import logging

import numpy as np

from ..db import Database
from ..util import truncate
from .ollama import OllamaClient

log = logging.getLogger("ai_researcher.embed")

BATCH = 16


class Embedder:
    def __init__(self, db: Database, client: OllamaClient):
        self.db = db
        self.client = client

    @property
    def model(self) -> str:
        return self.client.embed_model

    async def run(self, limit: int = 2000) -> dict[str, int]:
        if not await self.client.probe() or not self.client.embed_model:
            return {"embedded": 0, "skipped": 1}

        model = self.client.embed_model
        rows = self.db.query(
            """
            SELECT i.id, i.title, COALESCE(e.summary, '') AS summary
            FROM items i
            LEFT JOIN enrichment e ON e.item_id = i.id
            LEFT JOIN embeddings em ON em.item_id = i.id
            WHERE em.item_id IS NULL OR em.model != ?
            ORDER BY COALESCE(i.published_at, i.fetched_at) DESC
            LIMIT ?
            """,
            (model, limit),
        )
        if not rows:
            return {"embedded": 0}

        embedded = 0
        failures = 0
        for start in range(0, len(rows), BATCH):
            chunk = rows[start:start + BATCH]
            texts = [
                truncate(f"{r['title']}. {r['summary']}".strip(), 1000) or r["title"] or " "
                for r in chunk
            ]
            vectors = await self.client.embed(texts)
            if vectors is None:
                # A batch can fail transiently when something else is using the
                # GPU. Skipping it costs one batch; abandoning the pass silently
                # caps coverage and quietly degrades clustering for the day.
                failures += 1
                log.info("embedding batch %s failed; continuing", start // BATCH)
                if failures >= 5:
                    log.warning("embedding gave up after %s failed batches", failures)
                    break
                continue
            with self.db.tx() as conn:
                for row, vec in zip(chunk, vectors):
                    arr = np.asarray(vec, dtype=np.float32)
                    norm = float(np.linalg.norm(arr))
                    if norm > 0:
                        arr /= norm  # store unit vectors: cosine becomes a dot product
                    conn.execute(
                        "INSERT INTO embeddings (item_id, model, dim, vec) VALUES (?,?,?,?) "
                        "ON CONFLICT(item_id) DO UPDATE SET model=excluded.model, "
                        "dim=excluded.dim, vec=excluded.vec",
                        (row["id"], model, arr.size, arr.tobytes()),
                    )
                    embedded += 1
        return {"embedded": embedded, "failed_batches": failures,
                "total": self.db.scalar("SELECT COUNT(*) FROM embeddings", default=0),
                "model": model}


def load_vectors(db: Database, item_ids: list[int]) -> dict[int, np.ndarray]:
    """Fetch stored unit vectors for the given items, skipping any that lack one."""
    if not item_ids:
        return {}
    out: dict[int, np.ndarray] = {}
    for start in range(0, len(item_ids), 500):
        chunk = item_ids[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        rows = db.query(
            f"SELECT item_id, dim, vec FROM embeddings WHERE item_id IN ({placeholders})",
            tuple(chunk),
        )
        for row in rows:
            arr = np.frombuffer(row["vec"], dtype=np.float32)
            if arr.size == row["dim"]:
                out[row["item_id"]] = arr
    # A dimension change mid-corpus (model swap) would break the maths.
    if out:
        dims = {v.size for v in out.values()}
        if len(dims) > 1:
            majority = max(dims, key=lambda d: sum(1 for v in out.values() if v.size == d))
            out = {k: v for k, v in out.items() if v.size == majority}
    return out
