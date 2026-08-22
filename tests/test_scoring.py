"""Ranking: per-source normalisation, missing data, and corroboration."""

from datetime import timedelta

from ai_researcher.trends.score import score_cluster, score_item
from ai_researcher.util import iso, utcnow

NOW = utcnow()


def item(**kw):
    base = {
        "published_at": iso(NOW - timedelta(hours=2)),
        "importance": 0.5, "engagement": 0.0, "comments": 0,
        "source_key": "rss", "source_weight": 1.0, "tier": "news", "meta": {},
    }
    base.update(kw)
    return base


class TestScoreItem:
    def test_importance_drives_score(self):
        assert score_item(item(importance=0.9), now=NOW) > score_item(item(importance=0.2), now=NOW)

    def test_recency_decay(self):
        fresh = score_item(item(published_at=iso(NOW - timedelta(hours=1))), now=NOW)
        stale = score_item(item(published_at=iso(NOW - timedelta(days=6))), now=NOW)
        assert fresh > stale * 2

    def test_engagement_normalised_per_source(self):
        """400 HN points and 400 GitHub stars are not the same quantity."""
        hn = score_item(item(engagement=400, source_key="hackernews"), now=NOW)
        gh = score_item(item(engagement=400, source_key="github_trending"), now=NOW)
        assert hn > gh

    def test_missing_score_is_unknown_not_zero(self):
        """Reddit's RSS fallback reports no score; that must not bury the item."""
        unknown = score_item(item(engagement=0, meta={"no_score": True}), now=NOW)
        genuinely_ignored = score_item(item(engagement=0, meta={}), now=NOW)
        assert unknown > genuinely_ignored

    def test_subreddit_weight_applies(self):
        strong = score_item(item(meta={"sub_weight": 1.5}), now=NOW)
        weak = score_item(item(meta={"sub_weight": 0.7}), now=NOW)
        assert strong > weak

    def test_undated_item_still_scores(self):
        assert score_item(item(published_at=None), now=NOW) > 0

    def test_malformed_meta_does_not_raise(self):
        assert score_item(item(meta=None), now=NOW) >= 0


class TestScoreCluster:
    def test_corroboration_beats_a_lone_item(self):
        """Five outlets reporting one thing outranks one outlet shouting."""
        lone = [item(importance=0.7, source_key="a", score=1.0)]
        many = [item(importance=0.5, source_key=k, score=0.6) for k in "abcde"]
        for group in (lone, many):
            for it in group:
                it.setdefault("score", score_item(it, now=NOW))
        assert score_cluster(many, now=NOW) > score_cluster(lone, now=NOW)

    def test_one_source_repeating_itself_does_not_win(self):
        """A single aggregator posting 20 near-duplicates is not a story."""
        spam = [dict(item(source_key="spam", score=0.4)) for _ in range(20)]
        real = [dict(item(source_key=k, score=0.5)) for k in "abcd"]
        assert score_cluster(real, now=NOW) > score_cluster(spam, now=NOW) * 0.6

    def test_single_high_importance_item_still_surfaces(self):
        big = [item(importance=0.95, source_key="lab", score=1.4, tier="lab")]
        meh = [item(importance=0.3, source_key=k, score=0.3) for k in "abc"]
        assert score_cluster(big, now=NOW) > score_cluster(meh, now=NOW)

    def test_empty_group_is_zero(self):
        assert score_cluster([], now=NOW) == 0.0
