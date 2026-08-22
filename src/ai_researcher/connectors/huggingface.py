"""Hugging Face connectors: daily papers and trending model releases.

The trending-models feed is the closest thing to a real-time model-drop wire —
new open weights show up here before the blog posts land.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from ..config import Source
from ..util import parse_datetime, utcnow
from .base import Connector, FetchResult, RawItem

PAPERS_API = "https://huggingface.co/api/daily_papers"
MODELS_API = "https://huggingface.co/api/models"


class HFPapersConnector(Connector):
    kind = "hf_papers"

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        days = int(source.config.get("days", 3))
        today = utcnow().date()
        dates = [(today - timedelta(days=d)).isoformat() for d in range(days)]

        results = await asyncio.gather(
            *(self.fetcher.get_json(PAPERS_API, params={"date": d}) for d in dates),
            return_exceptions=True,
        )

        items: dict[str, RawItem] = {}
        ok = False
        for payload in results:
            if isinstance(payload, BaseException) or not payload:
                continue
            ok = True
            for entry in payload:
                item = self._to_item(entry)
                if item and item.external_id not in items:
                    items[item.external_id] = item

        if not ok:
            return FetchResult(status="error", error="daily_papers API unavailable")
        return FetchResult(items=list(items.values()))

    def _to_item(self, entry: dict[str, Any]) -> RawItem | None:
        paper = entry.get("paper") or {}
        paper_id = paper.get("id")
        if not paper_id:
            return None
        authors = [a.get("name", "") for a in (paper.get("authors") or [])]
        # Upvotes on HF papers are a decent early proxy for "researchers care".
        upvotes = float(paper.get("upvotes") or 0)
        return RawItem(
            external_id=f"hfpaper:{paper_id}",
            title=(paper.get("title") or entry.get("title") or "").strip(),
            url=f"https://arxiv.org/abs/{paper_id}",
            body=(paper.get("summary") or "").strip(),
            author=", ".join(authors[:6]),
            published_at=parse_datetime(paper.get("publishedAt") or entry.get("publishedAt")),
            engagement=upvotes,
            comments=int(paper.get("numComments") or 0),
            meta={
                "arxiv_id": paper_id,
                "hf_url": f"https://huggingface.co/papers/{paper_id}",
                "author_count": len(authors),
                "featured": True,
            },
        ).normalized()


class HFModelsConnector(Connector):
    kind = "hf_models"

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        limit = int(source.config.get("limit", 60))
        min_downloads = int(source.config.get("min_downloads", 100))
        cutoff = utcnow() - timedelta(days=max(self.settings.item_max_age_days, 21))

        payload = await self.fetcher.get_json(
            MODELS_API,
            params={
                "sort": "trendingScore",
                "direction": -1,
                "limit": limit,
                "full": "true",
            },
        )
        if not payload:
            return FetchResult(status="error", error="models API unavailable")

        items: list[RawItem] = []
        for entry in payload:
            model_id = entry.get("modelId") or entry.get("id")
            if not model_id:
                continue
            created = parse_datetime(entry.get("createdAt"))
            downloads = int(entry.get("downloads") or 0)
            likes = int(entry.get("likes") or 0)

            # Trending includes long-lived staples; we only want fresh drops.
            if created and created < cutoff:
                continue
            if downloads < min_downloads and likes < 20:
                continue

            org = model_id.split("/")[0] if "/" in model_id else ""
            tags = [t for t in (entry.get("tags") or []) if isinstance(t, str)][:12]
            pipeline = entry.get("pipeline_tag") or ""
            desc_bits = [b for b in (pipeline, ", ".join(tags[:6])) if b]

            items.append(
                RawItem(
                    external_id=f"hfmodel:{model_id}",
                    title=f"{model_id} — new model on Hugging Face",
                    url=f"https://huggingface.co/{model_id}",
                    body=f"Open weights released by {org or 'an unknown org'}. " +
                         ("; ".join(desc_bits) if desc_bits else ""),
                    author=org,
                    published_at=created,
                    engagement=float(likes),
                    meta={
                        "model_id": model_id,
                        "org": org,
                        "downloads": downloads,
                        "likes": likes,
                        "pipeline_tag": pipeline,
                        "tags": tags,
                        "trending_score": entry.get("trendingScore"),
                        "is_model_release": True,
                    },
                ).normalized()
            )
        return FetchResult(items=items)
