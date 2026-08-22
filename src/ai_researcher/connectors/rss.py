"""Generic RSS/Atom connector — covers vendor blogs, news, and newsletters."""

from __future__ import annotations

from typing import Any

import feedparser

from ..config import Source
from ..util import parse_datetime
from .base import Connector, FetchResult, RawItem


class RSSConnector(Connector):
    kind = "rss"

    def available(self, source: Source) -> tuple[bool, str]:
        return (True, "") if source.url else (False, "no url configured")

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        # Conditional GET keeps us cheap and polite on hourly polling.
        headers: dict[str, str] = {}
        if state.get("etag"):
            headers["If-None-Match"] = state["etag"]
        if state.get("last_modified"):
            headers["If-Modified-Since"] = state["last_modified"]

        resp = await self.fetcher.get(source.url, headers=headers)
        if resp is None:
            return FetchResult(status="error", error="request failed")
        if resp.status_code == 304:
            return FetchResult(
                status="not-modified",
                etag=state.get("etag", ""),
                last_modified=state.get("last_modified", ""),
            )
        if resp.status_code >= 400:
            return FetchResult(status="error", error=f"HTTP {resp.status_code}")

        parsed = feedparser.parse(resp.content)
        entries = parsed.get("entries") or []
        if not entries:
            # bozo alone isn't fatal — plenty of real feeds are slightly invalid.
            reason = str(parsed.get("bozo_exception", "")) or "no entries"
            return FetchResult(status="error", error=reason[:200])

        items: list[RawItem] = []
        for entry in entries:
            item = self._to_item(entry)
            if item is not None:
                items.append(item.normalized())

        return FetchResult(
            items=items,
            etag=resp.headers.get("ETag", ""),
            last_modified=resp.headers.get("Last-Modified", ""),
        )

    def _to_item(self, entry: Any) -> RawItem | None:
        link = entry.get("link") or ""
        if isinstance(entry.get("links"), list) and not link:
            for candidate in entry["links"]:
                if candidate.get("rel") in (None, "alternate") and candidate.get("href"):
                    link = candidate["href"]
                    break
        title = (entry.get("title") or "").strip()
        if not title and not link:
            return None

        body = ""
        content = entry.get("content")
        if isinstance(content, list) and content:
            body = content[0].get("value", "")
        body = body or entry.get("summary", "") or entry.get("description", "")

        published = (
            parse_datetime(entry.get("published"))
            or parse_datetime(entry.get("updated"))
            or parse_datetime(entry.get("created"))
        )

        author = entry.get("author") or ""
        if not author and isinstance(entry.get("authors"), list) and entry["authors"]:
            author = entry["authors"][0].get("name", "")

        tags = [
            t.get("term", "")
            for t in (entry.get("tags") or [])
            if isinstance(t, dict) and t.get("term")
        ]

        external_id = entry.get("id") or entry.get("guid") or link or title
        return RawItem(
            external_id=str(external_id)[:400],
            title=title,
            url=link,
            body=body,
            author=author[:200],
            published_at=published,
            meta={"feed_tags": tags[:8]} if tags else {},
        )
