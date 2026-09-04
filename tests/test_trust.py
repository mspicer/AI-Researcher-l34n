"""Brief validator, relevance filter, freshness, eval corpus, cache, HTTP."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from ai_researcher.backup import backup_database, integrity_check, restore_database
from ai_researcher.config import Settings
from ai_researcher.db import Database
from ai_researcher.eval import CASES, CORPUS_VERSION, LAYERS, run_case, run_corpus
from ai_researcher.eval.corpus import case_by_id
from ai_researcher.enrich.chat import consume_daily_budget
from ai_researcher.enrich.relevance import score_relevance
from ai_researcher.http import Fetcher
from ai_researcher.trends.brief import (
    _fallback_markdown,
    brief_fingerprint,
    generate_brief,
)
from ai_researcher.trends.freshness import classify_freshness
from ai_researcher.trends.validate import validate_brief
from ai_researcher.util import content_hash, iso, local_day, url_hash, utcnow


def _valid_brief(**kwargs) -> str:
    return (
        "## The one thing\n"
        "Acme released 7B GGUF weights, covered by three sources. [S1]\n\n"
        "## Also today\n"
        "- **Weights** — Acme 7B open weights landed on Hugging Face. [S1]\n"
        "- **Serving** — vLLM 0.8 shipped an OpenAI-compatible server. [S2]\n"
        "- **Policy** — EU AI Act date was confirmed. [S3]\n"
        "- **Paper** — DeepSeek posted an attention variant. [S4]\n\n"
        "## Worth a closer look\n"
        "- **Card** — Confirm the GGUF quant and license on the model card.\n"
        "- **Server** — The vLLM release is the gated experiment.\n"
        + (kwargs.get("ready") or "")
    )


class TestValidateBrief:
    def test_requires_the_one_thing_first(self):
        md = "## Also today\n- **x** — y\n"
        result = validate_brief(md, strict_counts=False)
        assert not result.ok
        assert any("first heading" in e for e in result.errors)

    def test_rejects_prompt_echo_and_thinking(self):
        md = (
            "## The one thing\n"
            "Write exactly this structure in Markdown.\n"
            "<think>planning</think>\n"
        )
        result = validate_brief(md, strict_counts=False)
        assert not result.ok
        assert any("prompt-echo" in e for e in result.errors)

    def test_rejects_ready_when_nothing_gated(self):
        md = _valid_brief(ready="\n## Ready to build\n- **adopt** — Invented tool\n")
        result = validate_brief(md, ready=[], stories=[{"id": 1, "label": "Acme 7B"}])
        assert not result.ok
        assert any("no gated" in e for e in result.errors)

    def test_rejects_ungated_recommendation_title(self):
        md = _valid_brief(ready="\n## Ready to build\n- **spike** — Totally Fake Product 12B\n")
        result = validate_brief(
            md,
            stories=[{"id": 1, "label": "Acme 7B", "item_ids": [1]}],
            ready=[{"id": 9, "title": "vLLM 0.8", "decision": "spike"}],
        )
        assert not result.ok
        assert any("ungated" in e for e in result.errors)

    def test_accepts_gated_ready_title(self):
        md = _valid_brief(ready="\n## Ready to build\n- **spike** — vLLM 0.8: run the README server.\n")
        result = validate_brief(
            md,
            stories=[{"id": 1, "label": "Acme 7B open weights", "item_ids": [1]}],
            ready=[{"id": 9, "item_id": 2, "title": "vLLM 0.8", "decision": "spike"}],
        )
        assert result.ok, result.errors

    def test_trims_trailing_commentary(self):
        padding = " extra word" * 400
        md = _valid_brief() + "\n\nNote: " + padding
        result = validate_brief(md, stories=[{"id": 1, "label": "Acme 7B"}], strict_counts=True)
        assert result.word_count <= 360
        assert result.ok or any("word limit" in e for e in result.errors)

    def test_empty_day_fallback_is_schema_valid(self):
        md = _fallback_markdown([], [], [])
        result = validate_brief(md, strict_counts=False)
        assert result.ok, result.errors
        assert md.startswith("## The one thing")
        assert "## Ready to build" not in md


class TestRelevance:
    def test_drops_sports_headline(self):
        hit = score_relevance(
            "Premier League: City thrash United 4-0",
            "Match report from the Etihad. No AI.",
            kind="hackernews",
        )
        assert hit["relevant"] is False

    def test_drops_hn_hiring(self):
        hit = score_relevance("Ask HN: who is hiring? (January)", "Monthly hiring thread.",
                              kind="hackernews")
        assert hit["relevant"] is False

    def test_keeps_model_release(self):
        hit = score_relevance(
            "Acme releases 7B GGUF weights on Hugging Face",
            "Open weights, Apache-2.0.",
            kind="hf_models",
        )
        assert hit["relevant"] is True

    def test_muted_source_is_dropped(self):
        hit = score_relevance(
            "GPT-5 is out", "weights", kind="rss",
            source_key="hn", muted_sources={"hn"},
        )
        assert hit["relevant"] is False


class TestFreshness:
    def test_undated_is_aging_not_fresh(self):
        assert classify_freshness(published_at=None, fetched_at=None) == "aging"

    def test_recent_item_is_fresh(self):
        now = utcnow()
        assert classify_freshness(
            published_at=now - timedelta(hours=2),
            fetched_at=now,
            kind="rss",
            now=now,
        ) == "fresh"

    def test_old_hn_item_is_stale(self):
        now = utcnow()
        assert classify_freshness(
            published_at=now - timedelta(hours=80),
            fetched_at=now - timedelta(hours=80),
            kind="hackernews",
            now=now,
        ) == "stale"

    def test_superseded_wins(self):
        now = utcnow()
        assert classify_freshness(
            published_at=now, fetched_at=now, superseded=True, now=now,
        ) == "superseded"


class TestEvalCorpus:
    def test_corpus_is_versioned_and_covers_families(self):
        families = {c["family"] for c in CASES}
        for needed in (
            "prompt-injection", "empty-ready", "malformed-model",
            "irrelevant", "gating-decisions",
        ):
            assert needed in families
        assert CORPUS_VERSION

    def test_injection_and_empty_ready_are_rejected(self):
        inject = run_case(case_by_id("inject-direct"), layer="schema")
        assert inject["validate_ok"] is False
        ready = run_case(case_by_id("ready-empty"), layer="fallback")
        assert ready["hallucinated_ready"] or ready["fallback"]
        malformed = run_case(case_by_id("malformed-echo"), layer="fallback")
        assert malformed["fallback"] == 1.0

    def test_valid_shape_passes_schema_layer(self):
        row = run_case(case_by_id("valid-shape"), layer="schema")
        assert row["validate_ok"] is True
        assert row["fallback"] == 0.0

    def test_fallback_layer_recovers_from_garbage(self):
        row = run_case(case_by_id("malformed-empty"), layer="fallback")
        assert row["fallback"] == 1.0
        assert row.get("format_compliance") in (0.0, 1.0)

    def test_schema_layer_beats_plain_on_injection(self):
        report = run_corpus(layers=("plain", "schema", "fallback"))
        plain = report["layers"]["plain"]["metrics"]
        schema = report["layers"]["schema"]["metrics"]
        # Plain ships the hostile fixture; schema must not treat it as valid.
        assert schema["hallucinated_recommendation_rate"] <= plain["hallucinated_recommendation_rate"]
        assert report["best_layer"] in LAYERS


class TestBriefCache:
    def test_fingerprint_changes_with_model_and_stories(self):
        stories = [{"id": 1, "label": "A", "summary": "x", "source_count": 1}]
        a = brief_fingerprint(day="2026-01-01", model="gemma3:4b", stories=stories, ready=[], rising=[])
        b = brief_fingerprint(day="2026-01-01", model="qwen3:8b", stories=stories, ready=[], rising=[])
        c = brief_fingerprint(
            day="2026-01-01", model="gemma3:4b",
            stories=[{**stories[0], "summary": "changed"}], ready=[], rising=[],
        )
        assert a != b
        assert a != c

    def test_generate_brief_skips_matching_fingerprint(self, tmp_path: Path):
        db = Database(tmp_path / "t.db")
        day = local_day()
        stories = [{"id": 1, "label": "A", "summary": "x", "source_count": 1, "item_ids": [1]}]
        fp = brief_fingerprint(day=day, model="", stories=[], ready=[], rising=[])
        db.execute(
            "INSERT INTO briefs (day, markdown, model, created_at, fingerprint, stale) "
            "VALUES (?,?,?,?,?,0)",
            (day, "## The one thing\ncached\n", "", iso(utcnow()), fp),
        )

        class Silent:
            settings = Settings()
            async def probe(self):
                return False
            def model_for(self, **_k):
                return ""
            async def aclose(self):
                return None

        result = asyncio.run(generate_brief(db, Silent(), day=day, force=False))
        assert result["status"] == "cached"


class TestHttpRetry:
    def test_does_not_retry_404(self):
        hits = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(request.url.path)
            return httpx.Response(404, text="gone")

        fetcher = Fetcher("test-agent", concurrency=1)
        fetcher._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        resp = asyncio.run(fetcher.get("https://example.com/missing"))
        asyncio.run(fetcher.aclose())
        assert resp is not None and resp.status_code == 404
        assert len(hits) == 1

    def test_retries_429_with_retry_after(self):
        hits = []

        def handler(request: httpx.Request) -> httpx.Response:
            hits.append(1)
            if len(hits) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, text="slow")
            return httpx.Response(200, text="ok")

        fetcher = Fetcher("test-agent", concurrency=1)
        fetcher._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        resp = asyncio.run(fetcher.get("https://example.com/limited"))
        asyncio.run(fetcher.aclose())
        assert resp is not None and resp.status_code == 200
        assert len(hits) == 2


class TestBackup:
    def test_backup_roundtrip(self, tmp_path: Path):
        src = tmp_path / "live.db"
        db = Database(src)
        db.execute(
            "INSERT INTO items (source_key, external_id, title, fetched_at) VALUES (?,?,?,?)",
            ("s", "1", "hello", iso(utcnow())),
        )
        dest = tmp_path / "copy.db"
        result = backup_database(db, dest)
        assert result["ok"] is True
        ok, msg = integrity_check(dest)
        assert ok, msg
        restored = tmp_path / "restored.db"
        restore_database(dest, restored)
        other = Database(restored)
        assert other.scalar("SELECT title FROM items") == "hello"


class TestModelBudget:
    def test_exhausts_then_blocks(self, tmp_path: Path):
        assert consume_daily_budget(tmp_path, limit=2) is True
        assert consume_daily_budget(tmp_path, limit=2) is True
        assert consume_daily_budget(tmp_path, limit=2) is False
        assert consume_daily_budget(tmp_path, limit=0) is True


class TestBulletPromotion:
    """A brief whose bullets lack markers is complete, not malformed."""

    BRIEF = (
        "## The one thing\n"
        "**Astra ships** with better benchmarks [S1].\n\n"
        "## Also today\n"
        "**Nvidia buys HF** to own the hub [S2].  \n"
        "**Gemini 3.8 Flash** adds thinking levels [S3].  \n"
        "**Muse Spark 1.3** trims the decoder [S4].  \n"
        "**Qwen 3.8 on Cerebras** hits 2k tok/s [S5].\n\n"
        "## Worth a closer look\n"
        "1. **Provider outages** all landed at once [S3].\n"
        "2. **Daybreak fund** names no timeline [S4].\n"
    )

    def test_bold_lead_and_numbered_lines_count_as_bullets(self):
        from ai_researcher.trends.validate import bullets_of, promote_bullets, validate_brief

        promoted = promote_bullets(self.BRIEF)
        assert promoted.count("\n- **") == 6
        # The one-thing paragraph keeps its bold lead without a marker.
        assert "\n- **Astra" not in promoted
        result = validate_brief(self.BRIEF)
        assert result.ok, result.errors
        sections = dict(__import__("ai_researcher.trends.validate", fromlist=["split_sections"]).split_sections(result.markdown))
        assert len(bullets_of(sections["Also today"])) == 4
        assert len(bullets_of(sections["Worth a closer look"])) == 2

    def test_existing_markers_are_left_alone(self):
        from ai_researcher.trends.validate import promote_bullets

        text = "## Also today\n- **A** x [S1].\n* **B** y [S2].\n"
        assert promote_bullets(text) == text
