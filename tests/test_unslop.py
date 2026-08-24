"""Deterministic unslop pass — the safety net after the prompt rule."""

from ai_researcher.enrich.unslop import UNSLOP_RULE, unslop_text
from ai_researcher.research.schema import SCHEMA
from ai_researcher.trends.brief import SYSTEM as BRIEF_SYSTEM, _clean


class TestUnslopRule:
    def test_rule_is_wired_into_long_form_prompts(self):
        assert "em dash" in UNSLOP_RULE.lower() or "em dashes" in UNSLOP_RULE.lower()
        assert "delve" in UNSLOP_RULE
        assert UNSLOP_RULE in SCHEMA
        assert UNSLOP_RULE in BRIEF_SYSTEM


class TestUnslopText:
    def test_em_dash_becomes_a_comma(self):
        assert "—" not in unslop_text("Adopt — serve the Q4 this week.")
        assert "serve the Q4" in unslop_text("Adopt — serve the Q4 this week.")

    def test_en_dash_becomes_a_hyphen(self):
        assert unslop_text("3–5B parameters") == "3-5B parameters"

    def test_curly_quotes_become_straight(self):
        assert unslop_text("“hello” and ‘there’") == '"hello" and \'there\''

    def test_chatbot_opener_is_stripped(self):
        text = unslop_text("Of course! The repo is public.\n\n## Decision")
        assert not text.lower().startswith("of course")
        assert "## Decision" in text

    def test_ai_vocabulary_is_replaced(self):
        out = unslop_text("Researchers delve into the tapestry of results.")
        assert "delve" not in out.lower()
        assert "tapestry" not in out.lower()

    def test_filler_is_cut(self):
        out = unslop_text("In order to run it, clone the repo.")
        assert out.lower().startswith("to run it")

    def test_clean_unslops_model_markdown(self):
        raw = (
            "## The one thing\n"
            "This is a pivotal moment — the weights are on Hugging Face.\n"
        )
        cleaned = _clean(raw)
        assert "—" not in cleaned
        assert "pivotal" not in cleaned.lower()
        assert cleaned.startswith("## The one thing")
