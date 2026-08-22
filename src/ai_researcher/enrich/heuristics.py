"""Rule-based classification and entity extraction.

This is both the fallback when Ollama is unavailable and a prior that keeps a
7B model honest — small models happily label a funding round as "research", so
strong keyword evidence overrides them.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..config import CATEGORIES

# ── entity vocabulary ────────────────────────────────────────────────
# Canonical name -> regex alternatives. Ordered longest-first at match time so
# "Google DeepMind" wins over "Google".
ORGS: dict[str, list[str]] = {
    "OpenAI": ["openai", "chatgpt"],
    "Anthropic": ["anthropic", "claude"],
    "Google DeepMind": ["deepmind", "google deepmind"],
    "Google": ["google", "alphabet"],
    "Meta": ["meta ai", "meta platforms", r"\bmeta\b", "facebook ai", "fair"],
    "Microsoft": ["microsoft", "azure ai", "copilot"],
    "NVIDIA": ["nvidia"],
    "Mistral AI": ["mistral"],
    "Hugging Face": ["hugging ?face", r"\bhf\b"],
    "Amazon": ["amazon", r"\baws\b", "bedrock"],
    "Apple": ["apple intelligence", "apple ml"],
    "xAI": [r"\bxai\b", r"\bgrok\b"],
    "Alibaba": ["alibaba", "qwen"],
    "DeepSeek": ["deepseek"],
    "Moonshot AI": ["moonshot", "kimi"],
    "Z.ai": [r"\bglm-", r"\bzhipu\b"],
    "Cohere": ["cohere"],
    "Stability AI": ["stability ai", "stable diffusion"],
    "Perplexity": ["perplexity"],
    "Scale AI": ["scale ai"],
    "Databricks": ["databricks"],
    "Together AI": ["together ai"],
    "Groq": ["groq"],
    "Cerebras": ["cerebras"],
    "AMD": [r"\bamd\b", "instinct mi"],
    "Intel": ["intel", "gaudi"],
    "AI2": ["allen institute", r"\bai2\b", "olmo"],
    "EleutherAI": ["eleuther"],
    "Cursor": ["cursor"],
    "GitHub": ["github copilot", "github"],
    "Runway": ["runway"],
    "ElevenLabs": ["elevenlabs"],
    "Midjourney": ["midjourney"],
    "TSMC": ["tsmc"],
    "Safe Superintelligence": ["safe superintelligence", r"\bssi\b"],
    "Reflection AI": ["reflection ai"],
    "Baidu": ["baidu", "ernie"],
    "ByteDance": ["bytedance", "doubao", "seed-"],
    "Tencent": ["tencent", "hunyuan"],
    "IBM": [r"\bibm\b", "granite"],
}

MODEL_FAMILIES: dict[str, list[str]] = {
    "GPT": [r"gpt-?[0-9o]+(?:\.\d+)?(?:-\w+)?", r"\bo[1-4]\b(?:-\w+)?"],
    "Claude": [r"claude(?:\s+\d(?:\.\d)?)?(?:\s+(?:opus|sonnet|haiku))?"],
    "Gemini": [r"gemini(?:\s+\d(?:\.\d)?)?(?:\s+(?:pro|flash|ultra|nano))?"],
    "Llama": [r"llama\s?-?\d(?:\.\d)?"],
    "Qwen": [r"qwen\s?-?\d(?:\.\d)?"],
    "DeepSeek": [r"deepseek[- ]?(?:r|v)\d"],
    "Mistral": [r"mistral(?:\s+(?:large|small|medium|nemo))?", r"mixtral"],
    "Grok": [r"grok\s?-?\d?"],
    "Gemma": [r"gemma\s?-?\d?"],
    "Phi": [r"\bphi-?\d\b"],
    "Command": [r"command\s?-?r\+?"],
    "Nova": [r"\bnova\s+(?:pro|lite|micro|premier)\b"],
    "Kimi": [r"kimi\s?-?k?\d?"],
    "GLM": [r"\bglm-?\d(?:\.\d)?"],
    "OLMo": [r"\bolmo\s?-?\d?"],
}

TECH_TERMS = [
    "rag", "retrieval augmented generation", "fine-tuning", "lora", "qlora",
    "quantization", "distillation", "mixture of experts", "moe", "rlhf",
    "reinforcement learning", "chain of thought", "reasoning model",
    "test-time compute", "inference scaling", "context window", "long context",
    "multimodal", "vision language model", "vlm", "diffusion", "transformer",
    "state space model", "mamba", "attention", "flash attention", "kv cache",
    "speculative decoding", "agent", "agentic", "tool use", "function calling",
    "mcp", "model context protocol", "embeddings", "vector database",
    "world model", "robotics", "text-to-video", "text-to-image", "tts",
    "speech recognition", "code generation", "benchmark", "evaluation",
    "hallucination", "alignment", "interpretability", "jailbreak",
    "prompt injection", "guardrails", "synthetic data", "pretraining",
    "post-training", "open weights", "open source model", "distributed training",
]

# ── category signals ─────────────────────────────────────────────────
# (regex, category, strength). Strength >= 3 overrides an LLM disagreement.
_SIGNALS: list[tuple[str, str, int]] = [
    # funding / M&A
    (r"\b(raises?|raised|funding round|series\s+[a-f]\b|seed round|valuation)\b", "funding-acquisition", 3),
    (r"\b(acquires?|acquired|acquisition|merger|buyout|to buy)\b", "funding-acquisition", 3),
    (r"\$\s?\d+(\.\d+)?\s?(m|b|bn|million|billion)\b", "funding-acquisition", 2),
    (r"\b(ipo|s-1 filing|goes public)\b", "funding-acquisition", 2),
    # model releases
    (r"\b(introduc\w+|announc\w+|releas\w+|launch\w+|unveil\w+|present\w+)\b.{0,40}\b(model|llm)\b", "model-release", 3),
    (r"\bnew model on hugging face\b", "model-release", 4),
    (r"\b(open[- ]?weights?|open[- ]?sourc\w+)\b.{0,30}\b(model|llm|weights)\b", "model-release", 3),
    (r"\b(gpt-\d|claude\s+\d|gemini\s+\d|llama\s?\d|qwen\s?\d|deepseek-[rv]\d|mistral\s+large|grok-?\d)\b", "model-release", 2),
    (r"\b(checkpoint|model card|weights are|now available on hugging face)\b", "model-release", 2),
    # research
    (r"^(?:we|this paper|in this (?:paper|work))\b", "research", 2),
    (r"\b(we propose|we introduce|we present|our method|empirical study|ablation)\b", "research", 2),
    (r"\barxiv\b", "research", 2),
    # benchmarks
    (r"\b(benchmark|leaderboard|eval(?:uation)? (?:suite|harness)|state[- ]of[- ]the[- ]art|sota)\b", "benchmark-eval", 2),
    (r"\b(mmlu|gpqa|swe-bench|humaneval|arc-agi|aime|lmarena|chatbot arena|frontiermath)\b", "benchmark-eval", 3),
    # product
    (r"\b(now available|general availability|\bga\b|public preview|beta|early access|rolling out|pricing|free tier)\b", "product-launch", 2),
    (r"\b(app|feature|integration|plugin|extension|api)\b.{0,25}\b(launch\w+|ship\w+|available)\b", "product-launch", 2),
    # tooling / oss
    (r"\b(v?\d+\.\d+(\.\d+)?\s+released|release notes|changelog)\b", "tooling-oss", 3),
    (r"\breleased\b.{0,20}\bgithub\b", "tooling-oss", 2),
    (r"\b(library|framework|sdk|cli|toolkit|repo(?:sitory)?)\b", "tooling-oss", 1),
    (r"★ in its first weeks", "tooling-oss", 4),
    # infra
    (r"\b(gpu|tpu|datacenter|data cent(?:er|re)|cluster|supercomputer|h100|h200|b200|gb200|mi300|tsmc|fab|wafer|power grid|megawatt|gigawatt)\b", "infrastructure-compute", 2),
    (r"\b(inference cost|throughput|latency|tokens per second|serving)\b", "infrastructure-compute", 1),
    # policy
    (r"\b(regulation|regulator|eu ai act|executive order|legislation|bill|senate|congress|parliament|lawsuit|copyright|antitrust|ban(?:ned|s)?|compliance)\b", "policy-regulation", 3),
    (r"\b(nist|ftc|eu commission|white house|state ag)\b", "policy-regulation", 2),
    # safety
    (r"\b(safety|misuse|red[- ]team|vulnerability|exploit|data breach|deepfake|csam|harm|incident|shut down)\b", "safety-incident", 2),
    (r"\b(prompt injection|jailbreak|model poisoning|supply chain attack)\b", "safety-incident", 3),
    # opinion
    (r"\b(opinion|why i|i think|thoughts on|lessons|retrospective|deep dive|explained|a guide to|tutorial)\b", "opinion-analysis", 2),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), c, s) for p, c, s in _SIGNALS]

# Sources whose items are structurally one category, no matter the wording.
KIND_CATEGORY = {
    "arxiv": "research",
    "hf_papers": "research",
    "hf_models": "model-release",
    "github_releases": "tooling-oss",
    "github_trending": "tooling-oss",
}


def category_signals(text: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    for pattern, category, strength in _COMPILED:
        if pattern.search(text):
            scores[category] = scores.get(category, 0) + strength
    return scores


def classify(title: str, body: str, *, kind: str = "", hint: str = "") -> tuple[str, int]:
    """Return (category, confidence-strength). Strength 0 means "just a guess"."""
    if kind in KIND_CATEGORY:
        return KIND_CATEGORY[kind], 4

    # Title carries far more signal than body boilerplate.
    scores = category_signals(title)
    for category, strength in category_signals(body[:1200]).items():
        scores[category] = scores.get(category, 0) + max(1, strength // 2)

    if hint in CATEGORIES:
        scores[hint] = scores.get(hint, 0) + 1

    if not scores:
        return (hint if hint in CATEGORIES else "opinion-analysis"), 0
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0], best[1]


def _find(text: str, vocab: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    for canonical, patterns in vocab.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                found.append(canonical)
                break
    return found


def extract_entities(title: str, body: str = "") -> list[str]:
    """Orgs and model families named in the text, most-salient first."""
    haystack = f"{title}\n{body[:1500]}"
    orgs = _find(haystack, ORGS)
    models = _find(haystack, MODEL_FAMILIES)

    # Anything appearing in the title outranks a body-only mention.
    title_hits = set(_find(title, ORGS)) | set(_find(title, MODEL_FAMILIES))
    ordered = sorted(
        dict.fromkeys(models + orgs),
        key=lambda e: (e not in title_hits, e),
    )
    return ordered[:8]


def extract_tags(title: str, body: str = "") -> list[str]:
    haystack = f"{title} {body[:1500]}".lower()
    hits = [t for t in TECH_TERMS if t in haystack]
    # Prefer the specific term when a general one is a substring of it.
    hits.sort(key=len, reverse=True)
    kept: list[str] = []
    for term in hits:
        if not any(term in existing for existing in kept):
            kept.append(term)
    return kept[:8]


# Words that mark something as consequential rather than incremental.
_HIGH_SIGNAL = re.compile(
    r"\b(state[- ]of[- ]the[- ]art|sota|breakthrough|first|record|beats?|outperform\w*|"
    r"surpass\w*|acquir\w+|raises?|billion|open[- ]?sourc\w+|open weights?|"
    r"deprecat\w+|shut(?:ting)? down|lawsuit|ban(?:s|ned)?|leak\w*)\b",
    re.IGNORECASE,
)
_LOW_SIGNAL = re.compile(
    r"\b(how to|tutorial|guide|beginner|top \d+|listicle|roundup|weekly digest|"
    r"opinion|rant|question|help|noob|discussion thread|what do you think)\b",
    re.IGNORECASE,
)


def heuristic_importance(title: str, body: str, *, category: str, tier: str) -> float:
    """0..1 estimate of "would a busy practitioner want to see this"."""
    score = 0.45
    if _HIGH_SIGNAL.search(title):
        score += 0.20
    if _LOW_SIGNAL.search(title):
        score -= 0.20
    # A primary source announcing its own thing beats coverage of it.
    score += {"lab": 0.15, "vendor": 0.06, "research": 0.05, "analyst": 0.05}.get(tier, 0.0)
    score += {
        "model-release": 0.12,
        "funding-acquisition": 0.06,
        "policy-regulation": 0.04,
        "safety-incident": 0.04,
        "opinion-analysis": -0.06,
    }.get(category, 0.0)
    if len(title) < 25:
        score -= 0.05
    if len(body) > 600:
        score += 0.03
    return max(0.05, min(1.0, score))


def dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


# Small models mangle proper nouns ("ChatG:PT", "Claude 3.5 ."). Entities are
# displayed as filter chips and grouped across items, so a single stray
# character silently forks one entity into two.
_ENTITY_JUNK = re.compile(r"[^\w\s\.\-\+&/']")
_ENTITY_ALIASES = {
    "chatgpt": "ChatGPT", "openai": "OpenAI", "anthropic": "Anthropic",
    "google": "Google", "deepmind": "Google DeepMind", "meta": "Meta",
    "microsoft": "Microsoft", "nvidia": "NVIDIA", "huggingface": "Hugging Face",
    "hugging face": "Hugging Face", "mistral": "Mistral AI", "xai": "xAI",
    "llm": "", "ai": "", "api": "",  # too generic to be an entity
}


def clean_entity(value: str) -> str:
    """Normalise one model-supplied entity, or return '' to drop it."""
    text = _ENTITY_JUNK.sub("", str(value or "")).strip(" .-_/")
    text = re.sub(r"\s{2,}", " ", text)
    if len(text) < 2 or len(text) > 48:
        return ""
    alias = _ENTITY_ALIASES.get(text.casefold())
    if alias is not None:
        return alias
    # A token that is all lowercase and a single word is usually a common noun
    # the model mistook for a name.
    if text.islower() and " " not in text:
        return text.capitalize()
    return text


def clean_entities(values: Iterable[str]) -> list[str]:
    return dedupe_preserving_order(clean_entity(v) for v in values)
