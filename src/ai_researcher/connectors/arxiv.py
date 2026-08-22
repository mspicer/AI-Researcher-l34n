"""arXiv connector using the public Atom export API."""

from __future__ import annotations

from typing import Any

import feedparser

from ..config import Source
from ..util import parse_datetime
from .base import Connector, FetchResult, RawItem

API = "https://export.arxiv.org/api/query"


class ArxivConnector(Connector):
    kind = "arxiv"

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        categories = source.config.get("categories") or ["cs.AI"]
        max_results = int(source.config.get("max_results", 100))
        search = " OR ".join(f"cat:{c}" for c in categories)

        resp = await self.fetcher.get(
            API,
            params={
                "search_query": search,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": max_results,
                "start": 0,
            },
        )
        if resp is None:
            return FetchResult(status="error", error="request failed")
        if resp.status_code >= 400:
            return FetchResult(status="error", error=f"HTTP {resp.status_code}")

        parsed = feedparser.parse(resp.content)
        entries = parsed.get("entries") or []
        if not entries:
            return FetchResult(status="error", error="no entries returned")

        items: list[RawItem] = []
        for entry in entries:
            arxiv_id = (entry.get("id") or "").rsplit("/", 1)[-1]
            if not arxiv_id:
                continue
            authors = [a.get("name", "") for a in (entry.get("authors") or [])]
            primary = (entry.get("arxiv_primary_category") or {}).get("term", "")
            cats = [t.get("term", "") for t in (entry.get("tags") or []) if t.get("term")]

            items.append(
                RawItem(
                    external_id=arxiv_id,
                    title=(entry.get("title") or "").replace("\n", " ").strip(),
                    url=f"https://arxiv.org/abs/{arxiv_id.split('v')[0]}",
                    body=(entry.get("summary") or "").replace("\n", " ").strip(),
                    author=", ".join(authors[:6]),
                    published_at=parse_datetime(entry.get("published")),
                    meta={
                        "arxiv_id": arxiv_id,
                        "primary_category": primary,
                        "categories": cats[:8],
                        "author_count": len(authors),
                        "pdf": f"https://arxiv.org/pdf/{arxiv_id.split('v')[0]}",
                    },
                ).normalized()
            )
        return FetchResult(items=items)
