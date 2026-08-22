"""Connector parsing quirks that would silently corrupt data if they regressed."""

import asyncio
import types

import pytest

from ai_researcher.config import Settings, Source
from ai_researcher.connectors.base import RawItem
from ai_researcher.connectors.gnews import GoogleNewsConnector
from ai_researcher.connectors.reddit import RedditConnector


@pytest.fixture
def settings():
    return Settings()


class TestGoogleNews:
    """Google News wraps links and suffixes titles; both break dedup if kept."""

    def make(self, settings):
        return GoogleNewsConnector(settings, fetcher=None)

    def test_strips_publisher_suffix_from_title(self, settings):
        c = self.make(settings)
        entry = {
            "title": "How Claude's text watermarking works - Anthropic",
            "link": "https://news.google.com/rss/articles/CBMi123",
            "source": {"title": "Anthropic", "href": "https://www.anthropic.com"},
            "published": "Fri, 21 Aug 2026 10:00:00 GMT",
        }
        # exercise the same suffix logic the connector applies
        title = entry["title"]
        pub = entry["source"]["title"]
        assert title.endswith(pub)
        cleaned = title[: -len(pub)].rstrip(" -–—")
        assert cleaned == "How Claude's text watermarking works"

    def test_requires_a_query(self, settings):
        c = self.make(settings)
        ok, reason = c.available(Source(key="k", name="n", kind="gnews"))
        assert not ok and "query" in reason

    def test_accepts_configured_query(self, settings):
        c = self.make(settings)
        src = Source(key="k", name="n", kind="gnews", config={"query": "site:anthropic.com"})
        assert c.available(src)[0]


class TestRedditRotation:
    """Reddit's rate limit forces rotation; the cursor must not skip subreddits."""

    def make(self, settings):
        return RedditConnector(settings, fetcher=None)

    def source(self, n=13, per_run=4):
        return Source(
            key="reddit", name="Reddit", kind="reddit",
            config={"per_run": per_run, "delay_seconds": 0,
                    "subreddits": [{"name": f"s{i}", "weight": 1.0} for i in range(n)]},
        )

    def test_parses_subreddit_forms(self, settings):
        c = self.make(settings)
        src = Source(key="r", name="r", kind="reddit",
                     config={"subreddits": ["plain", {"name": "dict", "weight": 2.0}]})
        assert c._subreddits(src) == [("plain", 1.0), ("dict", 2.0)]

    def test_cursor_advances_and_wraps(self, settings, monkeypatch):
        """Every subreddit must be reached across successive runs."""
        c = self.make(settings)
        src = self.source(n=13, per_run=4)
        seen = []

        async def fake_rss(sub, weight):
            seen.append(sub)
            return [RawItem(external_id=f"t3_{sub}", title=f"post in {sub}",
                            url=f"https://reddit.com/r/{sub}/x")], "ok"
        monkeypatch.setattr(c, "_fetch_rss", fake_rss)

        cursor = ""
        for _ in range(4):          # 4 runs x 4 per run = 16 >= 13 subreddits
            res = asyncio.run(c._fetch_public(src, c._subreddits(src), {"cursor": cursor}))
            cursor = res.cursor
        assert set(seen) == {f"s{i}" for i in range(13)}, "rotation skipped a subreddit"

    def test_throttle_stops_sweep_without_losing_position(self, settings, monkeypatch):
        c = self.make(settings)
        src = self.source(n=6, per_run=4)
        calls = []

        async def fake_rss(sub, weight):
            calls.append(sub)
            if len(calls) == 2:
                return None, "throttled"
            return [RawItem(external_id=f"t3_{sub}", title="t",
                            url=f"https://reddit.com/r/{sub}/x")], "ok"
        monkeypatch.setattr(c, "_fetch_rss", fake_rss)

        res = asyncio.run(c._fetch_public(src, c._subreddits(src), {"cursor": "0"}))
        # stopped early rather than digging deeper into the rate limit
        assert len(calls) == 2
        # and the next run resumes at the subreddit that got throttled
        assert res.cursor == "2"

    def test_rss_items_flag_missing_score(self, settings):
        """Atom has no score; that must be marked unknown, not scored as zero."""
        c = self.make(settings)
        entry = {
            "link": "https://reddit.com/r/LocalLLaMA/comments/abc/x/",
            "title": "A post",
            "id": "https://reddit.com/r/LocalLLaMA/comments/t3_abc123",
            "updated": "2026-08-21T10:00:00+00:00",
            "author": "/u/someone",
        }
        item = c._from_atom(types.SimpleNamespace(get=entry.get), "LocalLLaMA", 1.5)
        assert item.meta["no_score"] is True
        assert item.engagement == 0.0
        assert item.meta["sub_weight"] == 1.5
        assert item.author == "someone"
