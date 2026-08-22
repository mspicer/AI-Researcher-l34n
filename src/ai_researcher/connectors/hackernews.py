"""Hacker News via the Algolia search API (no key required)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from ..config import Source
from ..util import parse_datetime, utcnow
from .base import Connector, FetchResult, RawItem

API = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNewsConnector(Connector):
    kind = "hackernews"

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        queries = source.config.get("queries") or ["AI"]
        min_points = int(source.config.get("min_points", 40))
        since = utcnow() - timedelta(days=min(self.settings.item_max_age_days, 7))
        cutoff = int(since.timestamp())

        results = await asyncio.gather(
            *(self._search(q, min_points, cutoff) for q in queries),
            return_exceptions=True,
        )

        items: dict[str, RawItem] = {}
        failures = 0
        for result in results:
            if isinstance(result, BaseException) or result is None:
                failures += 1
                continue
            for item in result:
                items.setdefault(item.external_id, item)

        if not items and failures:
            return FetchResult(status="error", error=f"{failures} HN queries failed")
        return FetchResult(items=list(items.values()))

    async def _search(self, query: str, min_points: int, cutoff: int) -> list[RawItem] | None:
        payload = await self.fetcher.get_json(
            API,
            params={
                "query": query,
                "tags": "story",
                "numericFilters": f"points>={min_points},created_at_i>{cutoff}",
                "hitsPerPage": 60,
            },
        )
        if not payload:
            return None

        out: list[RawItem] = []
        for hit in payload.get("hits") or []:
            object_id = hit.get("objectID")
            if not object_id:
                continue
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            # Ask HN and friends have no outbound link; the thread is the item.
            target = hit.get("url") or hn_url
            out.append(
                RawItem(
                    external_id=str(object_id),
                    title=(hit.get("title") or "").strip(),
                    url=target,
                    body=(hit.get("story_text") or "")[:4000],
                    author=hit.get("author") or "",
                    published_at=parse_datetime(hit.get("created_at")),
                    engagement=float(hit.get("points") or 0),
                    comments=int(hit.get("num_comments") or 0),
                    meta={"hn_url": hn_url, "matched_query": query},
                ).normalized()
            )
        return out
