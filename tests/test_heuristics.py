"""Rule-based classification: the layer that runs on every single item."""

import pytest

from ai_researcher.config import CATEGORIES
from ai_researcher.enrich import heuristics as H


class TestClassify:
    @pytest.mark.parametrize("title,expected", [
        ("Anthropic raises $2B at a $60B valuation", "funding-acquisition"),
        ("Nvidia acquires Run:ai for $700M", "funding-acquisition"),
        ("Introducing our new frontier model", "model-release"),
        ("EU AI Act enforcement begins next month", "policy-regulation"),
        ("New prompt injection attack bypasses guardrails", "safety-incident"),
        ("vllm v0.8.2 released", "tooling-oss"),
        ("Model tops SWE-bench leaderboard", "benchmark-eval"),
    ])
    def test_strong_signals(self, title, expected):
        category, strength = H.classify(title, "")
        assert category == expected
        assert strength >= 2

    def test_structural_kind_always_wins(self):
        # An arXiv paper is research no matter how it is worded.
        category, strength = H.classify("We acquire a new dataset", "", kind="arxiv")
        assert category == "research"
        assert strength == 4

    def test_always_returns_valid_category(self):
        category, _ = H.classify("completely unremarkable text", "")
        assert category in CATEGORIES


class TestEntities:
    def test_maps_aliases_to_canonical_names(self):
        assert "OpenAI" in H.extract_entities("ChatGPT gets a new feature")
        assert "Anthropic" in H.extract_entities("Claude can now use tools")

    def test_prefers_specific_org(self):
        found = H.extract_entities("Google DeepMind published a paper")
        assert "Google DeepMind" in found

    def test_title_hits_rank_before_body_hits(self):
        found = H.extract_entities("Mistral ships a model", "Meanwhile OpenAI responded")
        assert found.index("Mistral AI") < found.index("OpenAI")


class TestCleanEntity:
    @pytest.mark.parametrize("raw,expected", [
        ("ChatG:PT Ads", "ChatGPT Ads"),     # small models mangle punctuation
        ("  meta  ", "Meta"),
        ("hugging face", "Hugging Face"),
        ("llm", ""),                          # too generic to be an entity
        ("a", ""),                            # too short
    ])
    def test_cleaning(self, raw, expected):
        assert H.clean_entity(raw) == expected

    def test_clean_entities_dedupes(self):
        assert H.clean_entities(["OpenAI", "openai", "llm"]) == ["OpenAI"]


class TestImportance:
    def test_within_bounds(self):
        for title in ["x", "Anthropic raises $2B", "How to use RAG: a tutorial"]:
            score = H.heuristic_importance(title, "", category="research", tier="news")
            assert 0.0 <= score <= 1.0

    def test_primary_source_outranks_aggregator(self):
        lab = H.heuristic_importance("New model", "", category="model-release", tier="lab")
        news = H.heuristic_importance("New model", "", category="model-release", tier="news")
        assert lab > news

    def test_tutorials_rank_below_announcements(self):
        tut = H.heuristic_importance("A guide to fine-tuning", "", category="opinion-analysis", tier="news")
        ann = H.heuristic_importance("OpenAI open sources weights", "", category="model-release", tier="lab")
        assert ann > tut
