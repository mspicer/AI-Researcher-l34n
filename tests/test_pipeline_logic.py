"""Storage, clustering, and brief post-processing against a real database."""

import tempfile
import types
from datetime import timedelta
from pathlib import Path

import pytest

from ai_researcher.db import Database, jdump
from ai_researcher.trends.brief import _clean
from ai_researcher.trends.cluster import build_clusters
from ai_researcher.util import content_hash, iso, url_hash, utcnow


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        yield Database(Path(tmp) / "t.db")


def add_item(db, *, source, title, url, entities=(), importance=0.5, hours_ago=1, body=""):
    now = utcnow()
    published = iso(now - timedelta(hours=hours_ago))
    cur = db.execute(
        "INSERT INTO items (source_key, external_id, url, canonical_url, url_hash, "
        "content_hash, title, author, body, published_at, fetched_at, engagement, comments, meta) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (source, f"{source}:{title[:20]}:{url}", url, url, url_hash(url),
         content_hash(title, body), title, "", body, published, iso(now), 0, 0, "{}"),
    )
    item_id = cur.lastrowid
    db.execute(
        "INSERT INTO enrichment (item_id, summary, category, entities, tags, importance, "
        "why, model, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (item_id, title, "model-release", jdump(list(entities)), "[]", importance, "", "", iso(now)),
    )
    db.execute("INSERT OR IGNORE INTO sources (key, name, kind) VALUES (?,?,?)",
               (source, source, "rss"))
    return item_id


class TestFtsIndex:
    def test_index_is_deletable(self):
        """Regression: a contentless FTS5 table cannot be DELETEd from, which
        broke re-indexing an item after enrichment."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Database(Path(tmp) / "t.db")
            d.execute("INSERT INTO items (source_key, external_id, fetched_at, title) "
                      "VALUES ('s','1',?,'hello world')", (iso(utcnow()),))
            d.index_item(1, "hello world", "body", "summary", "OpenAI")
            d.index_item(1, "hello world", "body", "updated summary", "OpenAI")  # must not raise
            assert d.search_ids("hello")

    def test_search_tolerates_punctuation(self, db):
        add_item(db, source="a", title="GPT-5 is out", url="https://a.com/1")
        db.index_item(1, "GPT-5 is out", "", "", "")
        assert db.search_ids('gpt-5 "quoted') is not None  # must not raise


class TestClustering:
    def test_identical_urls_merge(self, db):
        add_item(db, source="a", title="OpenAI ships GPT-5", url="https://o.ai/gpt5")
        add_item(db, source="b", title="Totally different words", url="https://o.ai/gpt5?utm_source=x")
        result = build_clusters(db)
        assert result["clusters"] == 1

    def test_distinct_stories_stay_separate(self, db):
        add_item(db, source="a", title="OpenAI ships a new model", url="https://o.ai/1",
                 entities=["OpenAI"])
        add_item(db, source="b", title="EU fines a chipmaker over export rules",
                 url="https://eu.int/2", entities=["Intel"])
        assert build_clusters(db)["clusters"] == 2

    def test_entity_guard_keeps_parallel_announcements_apart(self, db):
        """Two labs shipping the same kind of thing on the same day reads as
        near-identical text, but it is two stories."""
        add_item(db, source="a", title="Anthropic releases a new frontier model today",
                 url="https://an.com/1", entities=["Anthropic"])
        add_item(db, source="b", title="Mistral releases a new frontier model today",
                 url="https://mi.com/2", entities=["Mistral AI"])
        assert build_clusters(db)["clusters"] == 2

    def test_empty_db_is_handled(self, db):
        assert build_clusters(db)["clusters"] == 0

    def test_cluster_records_source_count(self, db):
        for src in "abc":
            add_item(db, source=src, title="OpenAI ships GPT-5", url="https://o.ai/gpt5")
        build_clusters(db)
        assert db.scalar("SELECT source_count FROM clusters") == 3


class TestBriefCleaning:
    @pytest.mark.parametrize("raw", [
        "Okay, the user wants a briefing.\n\nLet me think.\n\n## The one thing\nReal.",
        "<think>reasoning</think>\n## The one thing\nReal.",
        "```markdown\n## The one thing\nReal.\n```",
        "Here is your briefing:\n## The one thing\nReal.",
    ])
    def test_strips_scaffolding(self, raw):
        assert _clean(raw).startswith("## The one thing")

    def test_keeps_clean_input_untouched(self):
        good = "## The one thing\nContent here."
        assert _clean(good) == good


class TestClusterCategory:
    def test_primary_artifact_beats_commentary(self, db):
        """A model release discussed in five threads is still a model release."""
        from ai_researcher.db import jdump
        from ai_researcher.util import iso, utcnow
        now = utcnow()
        # the release itself, from a high-weight source
        rel = add_item(db, source="hf", title="DeepSeek-v4 released", url="https://hf.co/d4",
                       entities=["DeepSeek"], importance=0.9)
        db.execute("UPDATE sources SET weight=1.8, tier='research' WHERE key='hf'")
        db.execute("UPDATE enrichment SET category='model-release' WHERE item_id=?", (rel,))
        # five forum threads about it, all classified as chatter
        for i in range(5):
            iid = add_item(db, source=f"forum{i}", title="DeepSeek-v4 released",
                           url=f"https://f{i}.com/x", entities=["DeepSeek"], importance=0.3)
            db.execute("UPDATE enrichment SET category='tooling-oss' WHERE item_id=?", (iid,))
        build_clusters(db)
        assert db.scalar("SELECT category FROM clusters ORDER BY size DESC LIMIT 1") == "model-release"


class TestPrune:
    def test_chunks_large_deletes_and_keeps_saved(self, db, tmp_path):
        """A first prune after an outage can match far more rows than SQLite
        allows bound parameters for."""
        from ai_researcher.config import Settings
        from ai_researcher.pipeline import Pipeline
        from ai_researcher.util import iso, utcnow
        from datetime import timedelta

        old = iso(utcnow() - timedelta(days=400))
        ids = []
        for i in range(1200):
            cur = db.execute(
                "INSERT INTO items (source_key, external_id, fetched_at, published_at, title) "
                "VALUES ('s',?,?,?,'old item')", (str(i), old, old))
            ids.append(cur.lastrowid)
        db.execute("INSERT INTO saved (item_id, saved_at) VALUES (?,?)", (ids[0], iso(utcnow())))

        settings = Settings()
        settings.retention_days = 120
        removed = Pipeline.prune(types.SimpleNamespace(settings=settings, db=db))
        assert removed == 1199
        assert db.scalar("SELECT COUNT(*) FROM items") == 1   # the starred one survives


class TestRunLock:
    def test_second_holder_is_rejected(self, tmp_path):
        """Concurrent runs corrupted embeddings; the lock must be exclusive."""
        from ai_researcher.pipeline import RunLockBusy, run_lock
        import pytest as _pytest
        with run_lock(tmp_path):
            with _pytest.raises(RunLockBusy):
                with run_lock(tmp_path):
                    pass

    def test_lock_is_released_after_use(self, tmp_path):
        from ai_researcher.pipeline import run_lock
        with run_lock(tmp_path):
            pass
        with run_lock(tmp_path):   # must not raise
            pass

    def test_lock_released_on_exception(self, tmp_path):
        from ai_researcher.pipeline import run_lock
        try:
            with run_lock(tmp_path):
                raise ValueError("boom")
        except ValueError:
            pass
        with run_lock(tmp_path):
            pass
