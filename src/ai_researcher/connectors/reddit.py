"""Reddit connector.

Reddit ended self-serve API key creation with its Responsible Builder Policy,
and as of this build every JSON endpoint — www, old, and oauth alike — returns
403 to an unauthenticated client. The only route left is the public per-
subreddit Atom feed, and that is throttled to roughly one request per minute
per IP, with a penalty box after any burst.

That budget cannot sweep a dozen subreddits in one run, so the connector
*rotates*: each run fetches a few subreddits, spaced generously, and the next
run picks up where this one stopped. With hourly runs every subreddit is
refreshed every few hours, which is ample for a daily trends dashboard.

Two consequences worth knowing:

* Atom carries no score or comment count, so engagement-based ranking is blind
  here. Items are flagged `no_score` and the ranker treats that as unknown
  rather than as zero interest.
* On a 429 the connector stops immediately rather than retrying. Digging into
  a penalty box only lengthens it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import feedparser

from ..config import Source
from ..util import parse_datetime
from .base import Connector, FetchResult, RawItem

log = logging.getLogger("ai_researcher.reddit")

PUBLIC_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"

# Measured against the live endpoint: bursts get a multi-minute penalty box,
# and even 10-30s spacing 429s once tripped. ~75s is the sustainable pace.
UNAUTH_DELAY = 75.0
OAUTH_DELAY = 0.3
DEFAULT_PER_RUN = 4


class RedditConnector(Connector):
    kind = "reddit"

    def __init__(self, settings, fetcher):
        super().__init__(settings, fetcher)
        self._token: str | None = None
        self._token_checked = False
        self._token_lock = asyncio.Lock()

    async def _bearer(self) -> str | None:
        """Client-credentials token, attempted once per process."""
        if not (self.settings.reddit_client_id and self.settings.reddit_client_secret):
            return None
        async with self._token_lock:
            if self._token_checked:
                return self._token
            self._token_checked = True
            payload = await self.fetcher.post_json(
                f"{PUBLIC_BASE}/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self.settings.reddit_client_id, self.settings.reddit_client_secret),
            )
            if payload and payload.get("access_token"):
                self._token = payload["access_token"]
                log.info("Reddit OAuth active")
            else:
                log.info("Reddit OAuth credentials rejected; using public Atom feeds")
            return self._token

    # ── entry point ──────────────────────────────────────────────────
    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        subs = self._subreddits(source)
        if not subs:
            return FetchResult(status="error", error="no subreddits configured")

        token = await self._bearer()
        if token:
            return await self._fetch_authenticated(source, subs, token)
        return await self._fetch_public(source, subs, state)

    @staticmethod
    def _subreddits(source: Source) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for sub in source.config.get("subreddits") or []:
            if isinstance(sub, dict):
                if sub.get("name"):
                    out.append((sub["name"], float(sub.get("weight", 1.0))))
            elif sub:
                out.append((str(sub), 1.0))
        return out

    # ── public Atom path (the normal case) ───────────────────────────
    async def _fetch_public(
        self, source: Source, subs: list[tuple[str, float]], state: dict[str, Any]
    ) -> FetchResult:
        per_run = max(1, int(source.config.get("per_run", DEFAULT_PER_RUN)))
        delay = float(source.config.get("delay_seconds", UNAUTH_DELAY))

        try:
            cursor = int(state.get("cursor") or 0)
        except (TypeError, ValueError):
            cursor = 0
        cursor %= len(subs)

        # Rotate a window of subreddits, wrapping around the list.
        window = [subs[(cursor + i) % len(subs)] for i in range(min(per_run, len(subs)))]

        collected: list[RawItem] = []
        fetched = 0
        throttled = False
        failures: list[str] = []

        for position, (name, weight) in enumerate(window):
            if position:
                await asyncio.sleep(delay)
            items, status = await self._fetch_rss(name, weight)
            if status == "throttled":
                # Stop the whole sweep: the budget is per-IP, so the next
                # subreddit would fail too and deepen the penalty.
                throttled = True
                log.info("Reddit throttled at r/%s; ending sweep early", name)
                break
            if items is None:
                failures.append(f"r/{name}")
                continue
            fetched += 1
            collected.extend(items)

        # Advance past exactly what we consumed, so a short sweep does not skip
        # the subreddits it never reached.
        consumed = fetched + len(failures) + (1 if throttled else 0)
        next_cursor = (cursor + max(consumed, 1)) % len(subs)

        notes = [f"rotated {fetched}/{len(subs)} subreddits"]
        if throttled:
            notes.append("throttled by Reddit")
        if failures:
            notes.append(f"{len(failures)} failed")

        if not collected:
            return FetchResult(
                status="error",
                error="; ".join(notes) or "no items",
                cursor=str(next_cursor),
            )
        return FetchResult(
            items=collected, error="; ".join(notes), cursor=str(next_cursor)
        )

    async def _fetch_rss(
        self, sub: str, sub_weight: float
    ) -> tuple[list[RawItem] | None, str]:
        """Returns (items, status). status is ok | failed | throttled."""
        resp = await self.fetcher.get(
            f"{PUBLIC_BASE}/r/{sub}/hot/.rss",
            attempts=1,  # never retry into a rate limit
        )
        if resp is None:
            return None, "failed"
        if resp.status_code == 429:
            return None, "throttled"
        if resp.status_code >= 400:
            return None, "failed"

        parsed = feedparser.parse(resp.content)
        entries = parsed.get("entries") or []
        if not entries:
            return None, "failed"

        out: list[RawItem] = []
        for entry in entries[:40]:
            item = self._from_atom(entry, sub, sub_weight)
            if item is not None:
                out.append(item)
        return out, "ok"

    def _from_atom(self, entry: Any, sub: str, sub_weight: float) -> RawItem | None:
        link = entry.get("link") or ""
        title = (entry.get("title") or "").strip()
        if not link or not title:
            return None

        # Reddit's Atom ids are the fullname ("t3_abc123"). Preserving it means
        # a post seen over Atom now and over JSON later is the same row.
        raw_id = str(entry.get("id") or link)
        if "t3_" in raw_id:
            external_id = "t3_" + raw_id.split("t3_", 1)[1].split("/")[0][:12]
        else:
            external_id = raw_id.rstrip("/").rsplit("/", 1)[-1][:64]

        author = (entry.get("author") or "").strip()
        if author.startswith("/u/"):
            author = author[3:]

        return RawItem(
            external_id=external_id,
            title=title,
            url=link,
            body=entry.get("summary", "") or "",
            author=author,
            published_at=parse_datetime(entry.get("updated") or entry.get("published")),
            engagement=0.0,
            meta={
                "subreddit": sub,
                "sub_weight": sub_weight,
                "permalink": link,
                "via": "rss",
                # Signals to the ranker that 0 means "unmeasured", not "ignored".
                "no_score": True,
            },
        ).normalized()

    # ── authenticated path (only if you hold approved credentials) ───
    async def _fetch_authenticated(
        self, source: Source, subs: list[tuple[str, float]], token: str
    ) -> FetchResult:
        min_score = int(source.config.get("min_score", 20))
        headers = {"Authorization": f"bearer {token}"}
        collected: dict[str, RawItem] = {}
        failures = 0

        for name, weight in subs:
            for listing, params in (("hot", {}), ("top", {"t": "day"})):
                payload = await self.fetcher.get_json(
                    f"{OAUTH_BASE}/r/{name}/{listing}.json",
                    headers=headers,
                    params={"limit": 50, "raw_json": 1, **params},
                )
                await asyncio.sleep(OAUTH_DELAY)
                if not payload:
                    failures += 1
                    continue
                for child in (payload.get("data") or {}).get("children") or []:
                    item = self._from_json(child.get("data") or {}, name, weight)
                    if item is None or item.engagement < min_score:
                        continue
                    existing = collected.get(item.external_id)
                    if existing is None or item.engagement > existing.engagement:
                        collected[item.external_id] = item

        if not collected and failures:
            return FetchResult(status="error", error=f"{failures} listings failed")
        return FetchResult(items=list(collected.values()))

    def _from_json(self, d: dict[str, Any], sub: str, sub_weight: float) -> RawItem | None:
        if not d.get("id") or d.get("stickied") or d.get("over_18"):
            return None
        permalink = f"https://reddit.com{d.get('permalink', '')}"
        outbound = d.get("url_overridden_by_dest") or ""
        is_self = bool(d.get("is_self"))
        # The outbound URL is what lets a thread dedup against the blog post or
        # paper it discusses, so prefer it over the permalink for link posts.
        target = permalink if is_self or not outbound else outbound

        return RawItem(
            external_id=f"t3_{d['id']}",
            title=(d.get("title") or "").strip(),
            url=target,
            body=(d.get("selftext") or "")[:4000],
            author=d.get("author") or "",
            published_at=parse_datetime(d.get("created_utc")),
            engagement=float(d.get("score") or 0),
            comments=int(d.get("num_comments") or 0),
            meta={
                "subreddit": sub,
                "sub_weight": sub_weight,
                "permalink": permalink,
                "upvote_ratio": d.get("upvote_ratio"),
                "flair": d.get("link_flair_text") or "",
                "is_self": is_self,
                "via": "json",
            },
        ).normalized()
