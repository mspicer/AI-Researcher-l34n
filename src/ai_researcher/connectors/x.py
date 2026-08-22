"""X / Twitter connector (API v2 recent search).

Stays dormant unless X_BEARER_TOKEN is set. X has no free read tier, so this
requires a paid plan; every other source in the catalog works without it.
Recent search only reaches back seven days, which suits a daily dashboard.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..config import Source
from ..util import parse_datetime
from .base import Connector, FetchResult, RawItem

API = "https://api.x.com/2/tweets/search/recent"


class XConnector(Connector):
    kind = "x"

    def available(self, source: Source) -> tuple[bool, str]:
        if not self.settings.x_bearer_token:
            return False, "X_BEARER_TOKEN not set"
        if not source.config.get("queries"):
            return False, "no queries configured"
        return True, ""

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        queries = source.config.get("queries") or []
        max_results = min(int(source.config.get("max_results_per_query", 50)), 100)
        min_likes = int(source.config.get("min_likes", 0))
        headers = {"Authorization": f"Bearer {self.settings.x_bearer_token}"}

        # Sequential, not concurrent: the paid tiers still meter tightly and a
        # burst of parallel searches is the fastest way to eat a 429.
        collected: dict[str, RawItem] = {}
        errors: list[str] = []
        for query in queries:
            try:
                items = await self._search(query, headers, max_results, min_likes)
            except Exception as exc:  # noqa: BLE001 - one bad query must not sink the run
                errors.append(str(exc)[:120])
                continue
            if items is None:
                errors.append("search request failed")
                continue
            for item in items:
                collected.setdefault(item.external_id, item)
            await asyncio.sleep(1.0)

        if not collected and errors:
            return FetchResult(status="error", error="; ".join(errors[:3]))
        return FetchResult(items=list(collected.values()),
                           error="; ".join(errors[:3]) if errors else "")

    async def _search(
        self, query: str, headers: dict[str, str], max_results: int, min_likes: int
    ) -> list[RawItem] | None:
        payload = await self.fetcher.get_json(
            API,
            headers=headers,
            params={
                "query": query,
                "max_results": max_results,
                "tweet.fields": "created_at,public_metrics,entities,author_id,lang",
                "expansions": "author_id",
                "user.fields": "username,name,verified,public_metrics",
            },
        )
        if not payload:
            return None

        users = {
            u["id"]: u
            for u in ((payload.get("includes") or {}).get("users") or [])
            if u.get("id")
        }

        out: list[RawItem] = []
        for tweet in payload.get("data") or []:
            metrics = tweet.get("public_metrics") or {}
            likes = int(metrics.get("like_score", metrics.get("like_count", 0)) or 0)
            reposts = int(metrics.get("retweet_count") or 0)
            if likes < min_likes:
                continue

            user = users.get(tweet.get("author_id") or "", {})
            username = user.get("username", "unknown")
            text = (tweet.get("text") or "").strip()

            # A tweet linking out is usually a pointer to the real artifact;
            # prefer that URL so it dedups against the blog post or paper.
            urls = [
                u.get("expanded_url") or u.get("url", "")
                for u in ((tweet.get("entities") or {}).get("urls") or [])
                if not (u.get("expanded_url") or "").startswith("https://twitter.com/")
            ]
            outbound = next((u for u in urls if u), "")
            tweet_url = f"https://x.com/{username}/status/{tweet['id']}"

            out.append(
                RawItem(
                    external_id=f"x:{tweet['id']}",
                    title=text.split("\n")[0][:280] or f"Post by @{username}",
                    url=outbound or tweet_url,
                    body=text,
                    author=f"@{username}",
                    published_at=parse_datetime(tweet.get("created_at")),
                    engagement=float(likes + reposts * 2),
                    comments=int(metrics.get("reply_count") or 0),
                    meta={
                        "tweet_url": tweet_url,
                        "username": username,
                        "display_name": user.get("name", ""),
                        "likes": likes,
                        "reposts": reposts,
                        "matched_query": query,
                    },
                ).normalized()
            )
        return out
